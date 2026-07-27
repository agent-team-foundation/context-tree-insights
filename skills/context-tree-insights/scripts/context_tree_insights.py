#!/usr/bin/env python3
"""Build task-first Context Tree insights from First Tree Chats and Codex traces.

Collection remains deliberately conservative and read-only.  Semantic value is
judged at Task level after authorized Chat evidence has been collected.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence
from urllib.parse import urlsplit

SCHEMA_VERSION = 1
AUTHORIZATION_VALUES = {"explicit_agent", "explicit_chat"}
EFFECT_VALUES = {"confirmed", "constrained", "redirected", "conflicted"}
EXPOSURE_VALUES = {"confirmed", "unresolved"}
TASK_STATUS_VALUES = {"clear", "excluded"}
TASK_TYPE_VALUES = {
    "solution_design",
    "implementation_delivery",
    "review_qa_debugging",
    "research_explanation",
    "coordination_progress",
}
LINKAGE_VALUES = {
    "work_item",
    "explicit_handoff",
    "same_objective_delivery",
}
SATURATION_SIGNAL_VALUES = {
    "new_effect_type",
    "key_counterexample",
    "conclusion_change",
}
RUBRIC_KEYS = (
    "real_read",
    "decision_bearing_normal_passage",
    "task_relevant",
    "read_before_choice",
    "influence_visible",
)
TRACE_PREFLIGHT_MAX_BYTES = 512 * 1024
TRACE_PREFLIGHT_MAX_LINES = 512
PURE_READ_COMMANDS = {"bat", "cat", "head", "nl", "sed", "tail"}
EXEC_COMMAND_TOOLS = {"exec_command", "functions.exec_command"}
DIRECT_READ_TOOLS = {
    "read_file",
    "view_file",
    "functions.read_file",
    "functions.view_file",
}
SHELL_CONTINUATION_TOOLS = {"write_stdin", "functions.write_stdin"}
CELL_CONTINUATION_TOOLS = {"wait", "functions.wait"}
MIXED_OR_MUTATING_TOOLS = {
    "exec",
    "functions.exec",
    "apply_patch",
    "functions.apply_patch",
}
_ARTIFACT_LEXICAL_ROOTS: dict[Path, Path] = {}
UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
# Current Agent names are 1-64 lowercase ASCII slug characters. First Tree
# still runs older, grandfathered 1-100 character names, so an audit must not
# reject an already-bound runtime merely because it predates the tighter
# create-time limit.
AGENT_SLUG_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,99}")
CHAT_CONTEXT_PATTERN = re.compile(
    r"<first-tree-current-chat-context[\s\S]*?</first-tree-current-chat-context>",
    re.UNICODE,
)
CHAT_ID_PATTERN = re.compile(rf'"chatId"\s*:\s*"({UUID_PATTERN})"', re.UNICODE)
TREE_MENTION_PATTERN = re.compile(
    r"context[\s-]+tree|tree\s+(?:node|节点|decision|决策|constraint|约束|rationale|现行|current)|"
    r"(?:^|[\s\"'`(])(?:[^\s/\"'`()]+/)+[^\s\"'`()]+\.md(?=$|[\s\"'`,;:)])",
    re.IGNORECASE | re.UNICODE,
)
SHELL_SESSION_PATTERN = re.compile(r"(?:session ID|session_id[\"']?\s*[:=])\s*([0-9]+)", re.IGNORECASE)
CELL_SESSION_PATTERN = re.compile(r"(?:cell ID|cell_id[\"']?\s*[:=])\s*([A-Za-z0-9_.:-]+)", re.IGNORECASE)


class AuditError(RuntimeError):
    """Raised for invalid input or an incomplete deterministic audit step."""


@dataclass(frozen=True)
class Window:
    start: datetime | None
    end: datetime


@dataclass(frozen=True)
class ScopedChat:
    chat_id: str
    agent: str
    agent_id: str
    authorization: str


@dataclass(frozen=True)
class ScopedAgent:
    name: str
    agent_id: str
    authorization: str


@dataclass(frozen=True)
class Scope:
    agents: tuple[ScopedAgent, ...]
    chats: tuple[ScopedChat, ...]


@dataclass(frozen=True)
class WorkspaceIdentity:
    agent_name: str
    agent_display_name: str
    agent_id: str
    workspace_lexical: Path
    workspace: Path
    bound_tree_root: Path


@dataclass(frozen=True)
class TracePreflight:
    path: Path
    trace_id: str
    audit_id: str
    agent_id: str
    workspace: Path


def parse_datetime(value: str, *, field: str = "timestamp") -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise AuditError(f"Invalid {field}: {value}") from error
    if parsed.tzinfo is None:
        raise AuditError(f"{field} must include a timezone: {value}")
    return parsed.astimezone(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def resolve_window(days: int | None, now_text: str | None) -> Window:
    if days is not None and days <= 0:
        raise AuditError("--days must be greater than zero.")
    end = parse_datetime(now_text, field="--now") if now_text else datetime.now(timezone.utc)
    return Window(start=end - timedelta(days=days) if days is not None else None, end=end)


def in_window(value: str | None, window: Window) -> bool:
    if not value:
        return False
    try:
        timestamp = parse_datetime(value)
    except AuditError:
        return False
    return timestamp <= window.end and (window.start is None or timestamp >= window.start)


def strictly_before_window(value: Any, window: Window) -> bool:
    if not isinstance(value, str) or not value or window.start is None:
        return False
    try:
        timestamp = parse_datetime(value)
    except AuditError:
        return False
    return timestamp < window.start


def window_start_text(window: Window) -> str | None:
    return isoformat(window.start) if window.start is not None else None


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"Could not read JSON from {path}: {error}") from error


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise AuditError(f"Invalid JSONL at {path}:{line_number}: {error}") from error
                if not isinstance(value, dict):
                    raise AuditError(f"Expected a JSON object at {path}:{line_number}.")
                yield value
    except OSError as error:
        raise AuditError(f"Could not read {path}: {error}") from error


def resolve_artifact_root(value: str, workspace_identity: WorkspaceIdentity) -> Path:
    raw = Path(value).expanduser()
    lexical = Path(os.path.abspath(raw))
    if lexical.is_symlink():
        raise AuditError("--artifact-root must not be a symbolic link.")
    try:
        lexical_relative = lexical.relative_to(workspace_identity.workspace_lexical)
    except ValueError as error:
        raise AuditError(
            "--artifact-root must be a strict descendant of the authorized Agent workspace."
        ) from error
    if not lexical_relative.parts:
        raise AuditError(
            "--artifact-root must be a dedicated directory below the authorized Agent workspace."
        )
    current = workspace_identity.workspace_lexical
    for part in lexical_relative.parts:
        current = current / part
        if current.is_symlink():
            raise AuditError("--artifact-root must not traverse a symbolic link.")
    try:
        prospective = lexical.resolve(strict=False)
        resolved_relative = prospective.relative_to(workspace_identity.workspace)
    except (OSError, ValueError) as error:
        raise AuditError(
            "--artifact-root must resolve inside the authorized Agent workspace."
        ) from error
    if not resolved_relative.parts:
        raise AuditError(
            "--artifact-root must be a dedicated directory below the authorized Agent workspace."
        )
    try:
        lexical.mkdir(mode=0o700, parents=True, exist_ok=True)
        root = lexical.resolve(strict=True)
    except OSError as error:
        raise AuditError(f"Could not prepare --artifact-root {lexical}: {error}") from error
    try:
        root_stat = root.stat()
    except OSError as error:
        raise AuditError(f"Could not inspect --artifact-root {root}: {error}") from error
    if not stat.S_ISDIR(root_stat.st_mode):
        raise AuditError(f"--artifact-root must be a directory: {root}")
    try:
        final_relative = root.relative_to(workspace_identity.workspace)
    except ValueError as error:
        raise AuditError(
            "--artifact-root must resolve inside the authorized Agent workspace."
        ) from error
    if not final_relative.parts:
        raise AuditError(
            "--artifact-root must be a dedicated directory below the authorized Agent workspace."
        )
    if hasattr(os, "geteuid") and root_stat.st_uid != os.geteuid():
        raise AuditError("--artifact-root must be owned by the current user.")
    try:
        os.chmod(root, 0o700)
    except OSError as error:
        raise AuditError(f"Could not restrict --artifact-root permissions: {error}") from error
    _ARTIFACT_LEXICAL_ROOTS[root] = lexical
    return root


def artifact_path(root: Path, value: str, *, field: str, must_exist: bool) -> Path:
    raw = Path(value).expanduser()
    candidate = raw if raw.is_absolute() else root / raw
    lexical = Path(os.path.abspath(candidate))
    lexical_root: Path | None = None
    allowed_lexical_roots = (root, _ARTIFACT_LEXICAL_ROOTS.get(root, root))
    for allowed_root in allowed_lexical_roots:
        try:
            lexical.relative_to(allowed_root)
        except ValueError:
            continue
        lexical_root = allowed_root
        break
    if lexical_root is None:
        raise AuditError(f"{field} must stay lexically inside --artifact-root.")
    lexical_relative = lexical.relative_to(lexical_root)
    current = lexical_root
    for part in lexical_relative.parts:
        current = current / part
        if current.is_symlink():
            raise AuditError(f"{field} must not traverse a symbolic link.")
    try:
        resolved = lexical.resolve(strict=must_exist)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise AuditError(f"{field} must resolve inside --artifact-root {root}: {candidate}") from error
    if must_exist:
        if not resolved.is_file() or resolved.is_symlink():
            raise AuditError(f"{field} must be a regular file inside --artifact-root: {resolved}")
    else:
        try:
            resolved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            parent = resolved.parent.resolve(strict=True)
            parent.relative_to(root)
        except (OSError, ValueError) as error:
            raise AuditError(f"Could not prepare {field} inside --artifact-root: {resolved}") from error
        if resolved.exists() and (not resolved.is_file() or resolved.is_symlink()):
            raise AuditError(f"{field} must be a regular file path: {resolved}")
    return resolved


def require_distinct_paths(paths: Mapping[str, Path]) -> None:
    reverse: dict[Path, list[str]] = {}
    for field, path in paths.items():
        reverse.setdefault(path, []).append(field)
    duplicates = {path: fields for path, fields in reverse.items() if len(fields) > 1}
    if duplicates:
        detail = "; ".join(f"{path}: {', '.join(fields)}" for path, fields in duplicates.items())
        raise AuditError(f"Artifact inputs and outputs must be distinct ({detail}).")


def atomic_write(path: Path, text: str) -> None:
    temporary: str | None = None
    try:
        if path.is_symlink():
            raise AuditError(f"Refusing to replace symbolic-link artifact: {path}")
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = handle.name
        if path.is_symlink():
            raise AuditError(f"Refusing to replace symbolic-link artifact: {path}")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        temporary = None
    except AuditError:
        raise
    except OSError as error:
        raise AuditError(f"Could not write {path}: {error}") from error
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink()
            except OSError:
                pass


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    text = "".join(f"{json.dumps(row, ensure_ascii=False, sort_keys=True)}\n" for row in rows)
    atomic_write(path, text)


def write_text(path: Path, text: str) -> None:
    atomic_write(path, text)


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuditError(f"{field} must be a non-empty string.")
    return value.strip()


def validate_authorization(value: Any, field: str) -> str:
    authorization = require_string(value, field)
    if authorization not in AUTHORIZATION_VALUES:
        raise AuditError(f"{field} must be one of: {', '.join(sorted(AUTHORIZATION_VALUES))}.")
    return authorization


def require_uuid(value: Any, field: str) -> str:
    result = require_string(value, field)
    if re.fullmatch(UUID_PATTERN, result) is None:
        raise AuditError(f"{field} must be a UUID.")
    return result


def audit_id(chat_id: str, agent_id: str) -> str:
    return f"{chat_id}@{agent_id}"


def load_scope(path: Path) -> Scope:
    raw = read_json(path)
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise AuditError(f"{path} must be a schema_version {SCHEMA_VERSION} scope object.")

    agents: list[ScopedAgent] = []
    for index, value in enumerate(raw.get("agents", [])):
        if not isinstance(value, dict):
            raise AuditError(f"agents[{index}] must be an object.")
        authorization = validate_authorization(value.get("authorization"), f"agents[{index}].authorization")
        if authorization != "explicit_agent":
            raise AuditError(
                f"agents[{index}].authorization must be explicit_agent."
            )
        agents.append(
            ScopedAgent(
                name=require_string(value.get("name"), f"agents[{index}].name"),
                agent_id=require_uuid(value.get("agent_id"), f"agents[{index}].agent_id"),
                authorization=authorization,
            )
        )

    chats: list[ScopedChat] = []
    for index, value in enumerate(raw.get("chats", [])):
        if not isinstance(value, dict):
            raise AuditError(f"chats[{index}] must be an object.")
        chat_id = require_uuid(value.get("chat_id"), f"chats[{index}].chat_id")
        agent = require_string(value.get("agent"), f"chats[{index}].agent")
        authorization = validate_authorization(value.get("authorization"), f"chats[{index}].authorization")
        if authorization != "explicit_chat":
            raise AuditError(
                f"chats[{index}].authorization must be explicit_chat."
            )
        chats.append(
            ScopedChat(
                chat_id=chat_id,
                agent=agent,
                agent_id=require_uuid(value.get("agent_id"), f"chats[{index}].agent_id"),
                authorization=authorization,
            )
        )

    if bool(agents) == bool(chats):
        raise AuditError(
            "Scope must choose exactly one mode: one explicit_agent entry or one-or-more explicit_chat entries."
        )
    if agents and len(agents) != 1:
        raise AuditError("explicit_agent scope must contain exactly one Agent.")
    if len({(chat.chat_id, chat.agent_id) for chat in chats}) != len(chats):
        raise AuditError("The scope contains duplicate Chat and audited-Agent pairs.")
    identities = {
        (agent.name, agent.agent_id) for agent in agents
    } | {
        (chat.agent, chat.agent_id) for chat in chats
    }
    if len(identities) != 1:
        raise AuditError("Scope must name one exact Agent name and UUID.")
    return Scope(agents=tuple(agents), chats=tuple(chats))


def run_first_tree_data(binary: str, arguments: Sequence[str]) -> Any:
    command = [binary, "--json", *arguments]
    completed = subprocess.run(command, capture_output=True, check=False, text=True)
    if completed.returncode != 0:
        raise AuditError(
            f"Read-only First Tree command failed: {' '.join(command)} "
            f"(exit {completed.returncode}; output withheld)."
        )
    output = completed.stdout.strip()
    if not output:
        raise AuditError(f"Read-only First Tree command produced no JSON: {' '.join(command)}")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise AuditError(f"Invalid JSON from {' '.join(command)}: {error}") from error
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise AuditError(f"First Tree command did not succeed: {' '.join(command)}")
    return payload.get("data")


def run_first_tree_json(binary: str, arguments: Sequence[str]) -> dict[str, Any]:
    data = run_first_tree_data(binary, arguments)
    if not isinstance(data, dict):
        raise AuditError(f"First Tree command returned no data object: {' '.join(arguments)}")
    return data


def resolve_first_tree_binary(cli_value: str | None) -> str:
    """Resolve one executable without invoking a shell or probing product state."""
    requested = cli_value or os.environ.get("FIRST_TREE_BIN")
    candidates = [requested] if requested else ["first-tree", "first-tree-staging"]
    for candidate in candidates:
        if not candidate:
            continue
        if os.path.sep in candidate:
            raw = Path(candidate).expanduser()
            try:
                resolved = raw.resolve(strict=True)
            except OSError:
                continue
            if resolved.is_file() and os.access(resolved, os.X_OK):
                return str(resolved)
            continue
        discovered = shutil.which(candidate)
        if discovered:
            return discovered
    if requested:
        raise AuditError(
            "The explicitly configured First Tree binary is missing or not executable."
        )
    raise AuditError(
        "Could not find a First Tree CLI; set FIRST_TREE_BIN or pass --first-tree-bin."
    )


def verify_cli_agent_identity(binary: str, agent_slug: str, agent_id: str) -> None:
    """Cross-check the runtime slug through the CLI's local binding resolver."""
    command = [binary, "agent", "list"]
    environment = os.environ.copy()
    environment.pop("FIRST_TREE_JSON", None)
    completed = subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
        env=environment,
    )
    if completed.returncode != 0:
        raise AuditError(
            "The invoking Agent slug could not be resolved from local First Tree bindings "
            f"(exit {completed.returncode}; output withheld)."
        )
    resolved_ids = re.findall(
        rf"^[ \t]*{re.escape(agent_slug)}[ \t]+runtime:[ \t]+"
        rf"[^ \t\r\n]+[ \t]+uuid:[ \t]+({UUID_PATTERN})[ \t]*$",
        f"{completed.stdout}\n{completed.stderr}",
        re.MULTILINE,
    )
    if len(resolved_ids) != 1 or require_uuid(
        resolved_ids[0], "First Tree CLI Agent UUID"
    ) != agent_id:
        raise AuditError(
            "The invoking Agent's local CLI binding does not resolve to the "
            "authorized workspace UUID."
        )


def parse_agent_workspace(value: str) -> WorkspaceIdentity:
    agent_id_text, separator, workspace_text = value.partition("=")
    agent_id = require_uuid(agent_id_text, "--agent-workspace Agent UUID")
    if not separator or not workspace_text.strip():
        raise AuditError("--agent-workspace must use AGENT_UUID=/absolute/workspace syntax.")
    raw_workspace = Path(workspace_text).expanduser()
    if not raw_workspace.is_absolute():
        raise AuditError("--agent-workspace must name an absolute workspace path.")
    workspace_lexical = Path(os.path.abspath(raw_workspace))
    if workspace_lexical.is_symlink():
        raise AuditError("Authorized Agent workspace must not be a symbolic link.")
    try:
        workspace = workspace_lexical.resolve(strict=True)
    except OSError as error:
        raise AuditError(f"Could not resolve the authorized Agent workspace: {error}") from error
    if not workspace.is_dir():
        raise AuditError("Authorized Agent workspace is not a directory.")

    runtime_dir = workspace / ".first-tree-workspace"
    identity_path = runtime_dir / "identity.json"
    if runtime_dir.is_symlink() or identity_path.is_symlink():
        raise AuditError("Managed workspace identity must not traverse a symbolic link.")
    try:
        resolved_identity = identity_path.resolve(strict=True)
        resolved_identity.relative_to(workspace)
    except (OSError, ValueError) as error:
        raise AuditError("Managed workspace identity is missing or outside the workspace.") from error
    if not resolved_identity.is_file():
        raise AuditError("Managed workspace identity is not a regular file.")
    identity = read_json(resolved_identity)
    if (
        not isinstance(identity, dict)
        or identity.get("agentId") != agent_id
        or identity.get("type") != "agent"
    ):
        raise AuditError(f"Managed workspace identity does not match Agent {agent_id}.")
    agent_display_name = identity.get("displayName")
    if not isinstance(agent_display_name, str) or not agent_display_name.strip():
        raise AuditError("Managed workspace identity does not declare an Agent display name.")
    runtime_agent_id_text = os.environ.get("FIRST_TREE_AGENT_ID")
    runtime_agent_slug = os.environ.get("FIRST_TREE_AGENT_SLUG")
    if not runtime_agent_id_text:
        raise AuditError(
            "FIRST_TREE_AGENT_ID is required to bind the audit to the invoking runtime Agent."
        )
    runtime_agent_id = require_uuid(runtime_agent_id_text, "FIRST_TREE_AGENT_ID")
    if runtime_agent_id != agent_id:
        raise AuditError(
            "FIRST_TREE_AGENT_ID does not match the authorized workspace Agent UUID."
        )
    if (
        not isinstance(runtime_agent_slug, str)
        or AGENT_SLUG_PATTERN.fullmatch(runtime_agent_slug) is None
    ):
        raise AuditError(
            "FIRST_TREE_AGENT_SLUG must contain the invoking Agent's lowercase CLI selector."
        )
    tree_value = identity.get("contextTreePath")
    if not isinstance(tree_value, str) or not tree_value.strip():
        raise AuditError("Managed workspace identity does not declare a bound Context Tree.")
    raw_tree = Path(tree_value).expanduser()
    if not raw_tree.is_absolute() or raw_tree.is_symlink():
        raise AuditError("Bound Context Tree must be an absolute, non-symbolic-link path.")
    try:
        bound_tree = raw_tree.resolve(strict=True)
    except OSError as error:
        raise AuditError(f"Could not resolve the bound Context Tree: {error}") from error
    if not bound_tree.is_dir():
        raise AuditError("Bound Context Tree is not a directory.")
    return WorkspaceIdentity(
        agent_name=runtime_agent_slug,
        agent_display_name=agent_display_name.strip(),
        agent_id=agent_id,
        workspace_lexical=workspace_lexical,
        workspace=workspace,
        bound_tree_root=bound_tree,
    )


def paginated_items(binary: str, arguments: Sequence[str], *, agent: str | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        page_args = [*arguments, "-l", "100"]
        if cursor is not None:
            page_args.extend(["--cursor", cursor])
        if agent is not None:
            page_args.extend(["--agent", agent])
        data = run_first_tree_json(binary, page_args)
        page_items = data.get("items")
        if not isinstance(page_items, list):
            raise AuditError(f"Expected data.items from {' '.join(page_args)}.")
        for item in page_items:
            if isinstance(item, dict):
                items.append(item)
        next_cursor = data.get("nextCursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            break
        if next_cursor in seen_cursors:
            raise AuditError(f"Pagination cursor repeated for {' '.join(page_args)}.")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    return items


def supported_repository_identity(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    repository = value.strip()
    if (
        not repository
        or any(character.isspace() or ord(character) < 32 for character in repository)
        or repository.startswith(("/", "./", "../", "~"))
    ):
        return None

    scp_match = re.fullmatch(
        r"git@(?P<host>[A-Za-z0-9.-]+):(?P<path>[^?#]+)",
        repository,
    )
    if scp_match is not None:
        host = scp_match.group("host")
        path = scp_match.group("path")
    else:
        try:
            parsed = urlsplit(repository)
            parsed_host = parsed.hostname
            parsed.port
        except ValueError:
            return None
        if parsed.scheme not in {"http", "https", "ssh", "git"}:
            return None
        if parsed.query or parsed.fragment or not parsed_host:
            return None
        if parsed.password is not None:
            return None
        if parsed.scheme in {"http", "https", "git"} and parsed.username is not None:
            return None
        if parsed.scheme == "ssh" and parsed.username not in {None, "git"}:
            return None
        host = parsed_host
        path = parsed.path.lstrip("/")

    lowered_host = host.lower().rstrip(".")
    if lowered_host == "localhost" or "%" in lowered_host:
        return None
    try:
        address = ipaddress.ip_address(lowered_host)
    except ValueError:
        numeric_components = lowered_host.split(".")
        if re.fullmatch(r"[0-9.]+", lowered_host) or all(
            re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", component)
            for component in numeric_components
        ):
            return None
        address = None
    if address is not None:
        mapped_address = getattr(address, "ipv4_mapped", None)
        if (
            address.is_loopback
            or address.is_unspecified
            or (
                mapped_address is not None
                and (mapped_address.is_loopback or mapped_address.is_unspecified)
            )
        ):
            return None
    path_parts = path.removesuffix(".git").split("/")
    if (
        len(path_parts) < 2
        or any(part in {"", ".", ".."} for part in path_parts)
    ):
        return None
    return repository


def normalize_context_decision(value: Any) -> dict[str, Any] | None:
    """Return the minimal valid contextDecision v1 projection.

    The message path is intentionally tolerant: malformed analysis metadata is
    diagnosed by the caller, never allowed to block Chat export.
    """
    if not isinstance(value, Mapping):
        return None
    effect = value.get("effect")
    if (
        value.get("version") != 1
        or not isinstance(effect, str)
        or effect not in EFFECT_VALUES
    ):
        return None
    summary = value.get("summary")
    evidence = value.get("evidence")
    if not isinstance(summary, str) or not summary.strip():
        return None
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 3:
        return None
    projected_evidence: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, Mapping):
            return None
        repo_url = supported_repository_identity(item.get("repoUrl"))
        commit = item.get("commit")
        node_path = item.get("nodePath")
        heading = item.get("heading")
        normalized_node_path = node_path.strip() if isinstance(node_path, str) else ""
        if (
            repo_url is None
            or not isinstance(commit, str)
            or re.fullmatch(r"[0-9a-fA-F]{40}", commit) is None
            or not normalized_node_path
            or "\\" in normalized_node_path
            or Path(normalized_node_path).is_absolute()
            or ".." in Path(normalized_node_path).parts
            or not normalized_node_path.endswith(".md")
            or (heading is not None and (not isinstance(heading, str) or not heading.strip()))
        ):
            return None
        projected = {
            "repoUrl": repo_url,
            "commit": commit.lower(),
            "nodePath": normalized_node_path,
        }
        if heading is not None:
            projected["heading"] = heading.strip()
        projected_evidence.append(projected)
    return {
        "version": 1,
        "effect": effect,
        "summary": summary.strip(),
        "evidence": projected_evidence,
    }


def message_record(value: Mapping[str, Any]) -> dict[str, Any]:
    created_at = value.get("createdAt") or value.get("created_at")
    content = value.get("content")
    record = {
        "message_id": value.get("id") or value.get("message_id"),
        "created_at": created_at if isinstance(created_at, str) else None,
        "sender_id": value.get("senderId") or value.get("sender_id"),
        "sender_kind": value.get("sender_kind"),
        "content": content if isinstance(content, str) else payload_text(content),
    }
    metadata = value.get("metadata")
    raw_receipt: Any = None
    receipt_present = False
    if isinstance(metadata, Mapping) and "contextDecision" in metadata:
        raw_receipt = metadata.get("contextDecision")
        receipt_present = True
    elif "decision_receipt" in value:
        raw_receipt = value.get("decision_receipt")
        receipt_present = True
    if receipt_present:
        receipt = normalize_context_decision(raw_receipt)
        if receipt is None:
            record["_context_decision_invalid"] = True
        else:
            record["decision_receipt"] = receipt
    return record


def normalize_message_records(
    values: Iterable[Mapping[str, Any]],
    *,
    window: Window | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    records: list[dict[str, Any]] = []
    invalid_receipt = False
    for value in values:
        record = message_record(value)
        invalid = record.pop("_context_decision_invalid", False) is True
        if invalid and (
            window is None
            or (
                isinstance(record.get("created_at"), str)
                and in_window(record["created_at"], window)
            )
        ):
            invalid_receipt = True
        records.append(record)
    return records, invalid_receipt


def export_chats(args: argparse.Namespace) -> None:
    workspace_identity = parse_agent_workspace(args.agent_workspace)
    artifact_root = resolve_artifact_root(args.artifact_root, workspace_identity)
    scope_path = artifact_path(artifact_root, args.scope, field="--scope", must_exist=True)
    output_path = artifact_path(artifact_root, args.output, field="--output", must_exist=False)
    require_distinct_paths({"--scope": scope_path, "--output": output_path})
    scope = load_scope(scope_path)
    scoped_identities = {
        (agent.name, agent.agent_id) for agent in scope.agents
    } | {
        (chat.agent, chat.agent_id) for chat in scope.chats
    }
    scoped_agent_name, scoped_agent_id = next(iter(scoped_identities))
    if (
        workspace_identity.agent_name != scoped_agent_name
        or workspace_identity.agent_id != scoped_agent_id
    ):
        raise AuditError(
            "--agent-workspace identity must match the one exact Agent name and UUID in --scope."
        )
    first_tree_binary = resolve_first_tree_binary(args.first_tree_bin)
    verify_cli_agent_identity(
        first_tree_binary,
        workspace_identity.agent_name,
        workspace_identity.agent_id,
    )
    window = resolve_window(args.days, args.now)
    chat_sources: dict[tuple[str, str], dict[str, Any]] = {}

    for scoped_agent in scope.agents:
        for chat in paginated_items(first_tree_binary, ["chat", "list"], agent=scoped_agent.name):
            chat_id = chat.get("id")
            if not isinstance(chat_id, str) or re.fullmatch(UUID_PATTERN, chat_id) is None:
                continue
            last_message_at = chat.get("lastMessageAt")
            if strictly_before_window(last_message_at, window):
                continue
            key = (chat_id, scoped_agent.agent_id)
            chat_sources.setdefault(
                key,
                {
                    "agent": scoped_agent.name,
                    "agent_id": scoped_agent.agent_id,
                    "authorization": scoped_agent.authorization,
                    "chat": chat,
                    "exact_chat": False,
                },
            )

    for scoped_chat in scope.chats:
        key = (scoped_chat.chat_id, scoped_chat.agent_id)
        chat_sources[key] = {
            "agent": scoped_chat.agent,
            "agent_id": scoped_chat.agent_id,
            "authorization": scoped_chat.authorization,
            "chat": {},
            "exact_chat": True,
        }

    exported: list[dict[str, Any]] = []
    for (chat_id, source_agent_id), source in sorted(chat_sources.items()):
        history = paginated_items(
            first_tree_binary,
            ["chat", "history", chat_id],
            agent=source["agent"],
        )
        messages, invalid_receipt = normalize_message_records(history, window=window)
        messages = [
            message
            for message in messages
            if isinstance(message.get("created_at"), str) and in_window(message["created_at"], window)
        ]
        messages.sort(key=lambda message: (message["created_at"], str(message.get("message_id") or "")))
        if not messages and not source["exact_chat"]:
            continue
        chat_metadata = source["chat"]
        title = chat_metadata.get("topic") or chat_metadata.get("title") or chat_id
        exported.append(
            {
                "schema_version": SCHEMA_VERSION,
                "audit_id": audit_id(chat_id, source_agent_id),
                "chat_id": chat_id,
                "title": title,
                "authorization": source["authorization"],
                "source_agent": source["agent"],
                "source_agent_id": source["agent_id"],
                "window": {"start": window_start_text(window), "end": isoformat(window.end)},
                "messages": messages,
                "coverage_gaps": sorted(
                    (["context_decision_invalid"] if invalid_receipt else [])
                    + ([] if messages else ["no_visible_messages_in_window"])
                ),
            }
        )

    write_jsonl(output_path, exported)


def payload_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (payload_text(item) for item in value)))
    if not isinstance(value, dict):
        return ""
    values = []
    for key in ("text", "content", "output", "message"):
        if key in value:
            text = payload_text(value[key])
            if text:
                values.append(text)
    return "\n".join(values)


def chat_ids_from_text(text: str) -> list[str]:
    chat_ids: list[str] = []
    for block in CHAT_CONTEXT_PATTERN.findall(text):
        chat_ids.extend(match.group(1) for match in CHAT_ID_PATTERN.finditer(block))
    return chat_ids


def parse_tool_arguments(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = payload.get("arguments")
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
        return parsed if isinstance(parsed, dict) else {"raw": raw}
    raw_input = payload.get("input")
    if isinstance(raw_input, dict):
        return dict(raw_input)
    if isinstance(raw_input, str):
        try:
            parsed = json.loads(raw_input)
        except json.JSONDecodeError:
            return {"raw": raw_input}
        return parsed if isinstance(parsed, dict) else {"raw": raw_input}
    return {}


def tool_raw(payload: Mapping[str, Any]) -> str:
    arguments = parse_tool_arguments(payload)
    return "\n".join(
        filter(
            None,
            (
                str(payload.get("name") or ""),
                payload_text(payload.get("input")),
                payload_text(payload.get("arguments")),
                payload_text(arguments),
            ),
        )
    )


def relative_tree_path(candidate: Path, tree_roots: Sequence[Path]) -> str | None:
    try:
        resolved = candidate.expanduser().resolve(strict=False)
    except OSError:
        return None
    for tree_root in tree_roots:
        try:
            relative = resolved.relative_to(tree_root)
        except ValueError:
            continue
        if relative.suffix.lower() == ".md" and ".." not in relative.parts and relative.parts:
            return relative.as_posix()
    return None


def extract_node_paths(
    payload: Mapping[str, Any],
    tree_roots: Sequence[Path],
    default_workdir: Path,
) -> list[str]:
    raw = tool_raw(payload).replace("\\/", "/")
    paths: set[str] = set()

    for tree_root in tree_roots:
        root_text = tree_root.as_posix().rstrip("/")
        absolute_pattern = re.compile(
            rf"{re.escape(root_text)}/(?P<relative>[^\"'`\r\n;|&<>]+?\.md)(?=$|[\s\"'`,;:)|&<>])",
            re.UNICODE,
        )
        for match in absolute_pattern.finditer(raw):
            relative = match.group("relative").strip()
            candidate = relative_tree_path(tree_root / relative, tree_roots)
            if candidate is not None:
                paths.add(candidate)

    arguments = parse_tool_arguments(payload)
    workdir_value = arguments.get("workdir")
    workdirs = {default_workdir}
    if isinstance(workdir_value, str) and workdir_value.strip():
        workdirs.add(Path(workdir_value).expanduser())
    for match in re.finditer(r"""workdir\s*:\s*["'`]([^"'`]+)["'`]""", raw, re.UNICODE):
        workdirs.add(Path(match.group(1)).expanduser())

    for value in arguments.values():
        if not isinstance(value, str):
            continue
        try:
            tokens = shlex.split(value)
        except ValueError:
            tokens = value.split()
        for token in tokens:
            cleaned = token.strip(" \t\r\n\"'`,;:()[]{}")
            if not cleaned.lower().endswith(".md") or any(character.isspace() for character in cleaned):
                continue
            token_path = Path(cleaned).expanduser()
            candidates = [token_path] if token_path.is_absolute() else [workdir / token_path for workdir in workdirs]
            for candidate in candidates:
                relative = relative_tree_path(candidate, tree_roots)
                if relative is not None:
                    paths.add(relative)

    relative_pattern = re.compile(
        r"""(?<![A-Za-z0-9_.@/-])((?:[^\s/"'`(){}[\],;:|&<>]+/)+[^\s/"'`(){}[\],;:|&<>]+\.md)""",
        re.UNICODE,
    )
    for match in relative_pattern.finditer(raw):
        token_path = Path(match.group(1))
        for workdir in workdirs:
            relative = relative_tree_path(workdir / token_path, tree_roots)
            if relative is not None:
                paths.add(relative)
    return sorted(paths)


def shell_tokens(command: str) -> list[str] | None:
    if "\n" in command or "\r" in command or "`" in command or "$(" in command:
        return None
    try:
        lexer = shlex.shlex(
            command,
            posix=True,
            punctuation_chars=";&|<>()",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return None
    if any(token and set(token) <= set(";&|<>()") for token in tokens):
        return None
    return tokens


def pure_markdown_read_gap(
    tool_name: str,
    payload: Mapping[str, Any],
    node_paths: Sequence[str],
) -> str | None:
    """Return a coverage gap unless this is one provable, single-file read.

    The collector deliberately recognizes a very small command grammar. A false
    negative becomes a coverage gap; a false positive could combine unrelated
    output with a Tree passage and is therefore unacceptable.
    """
    if not node_paths:
        return "not_a_tree_markdown_read"
    if len(node_paths) != 1:
        return "composite_or_multi_file_tree_read_rejected"

    if tool_name in MIXED_OR_MUTATING_TOOLS:
        return "mixed_or_mutating_tool_output_rejected"
    if tool_name in DIRECT_READ_TOOLS:
        return None
    if tool_name not in EXEC_COMMAND_TOOLS:
        return "unsupported_tree_read_tool"

    arguments = parse_tool_arguments(payload)
    command = arguments.get("cmd")
    if not isinstance(command, str) or not command.strip():
        return "unprovable_tree_read_command"
    tokens = shell_tokens(command)
    if not tokens:
        return "composite_shell_tree_read_rejected"
    if "-" in tokens[1:]:
        return "stdin_tree_read_rejected"
    executable = Path(tokens[0]).name
    if executable not in PURE_READ_COMMANDS:
        return "unprovable_tree_read_command"
    if executable == "sed":
        non_path_tokens = [
            token
            for token in tokens[1:]
            if not token.strip(" \t\"'").lower().endswith(".md")
        ]
        allowed_flags = {"-n", "--quiet", "--silent"}
        expressions = [token for token in non_path_tokens if token not in allowed_flags]
        if (
            len(expressions) != 1
            or re.fullmatch(r"(?:\d+|\$)(?:,(?:\d+|\$))?p", expressions[0]) is None
        ):
            return "unprovable_tree_read_command"
    markdown_tokens = [
        token
        for token in tokens[1:]
        if token.strip(" \t\"'").lower().endswith(".md")
    ]
    if len(markdown_tokens) != 1:
        return "composite_or_multi_file_tree_read_rejected"
    if executable != "sed":
        extra_positionals = [
            token
            for token in tokens[1:]
            if token != markdown_tokens[0]
            and not token.startswith("-")
            and not (
                executable in {"head", "tail"}
                and re.fullmatch(r"\+?\d+", token) is not None
            )
        ]
        if extra_positionals:
            return "composite_or_multi_file_tree_read_rejected"
    return None


def content_class_hint(paths: Sequence[str]) -> str:
    classes = {
        "non-normal" if path == "AGENTS.md" or path.startswith(("members/", "raw-context/")) else "normal"
        for path in paths
    }
    if len(classes) == 1:
        return next(iter(classes))
    return "mixed"


def output_success(output: str) -> bool | None:
    lowered = output.lower()
    if re.search(r"(?:process exited with code|exit[_ ]code[\"']?\s*[:=])\s*[1-9][0-9]*", lowered):
        return False
    if re.search(r"(?:process exited with code|exit[_ ]code[\"']?\s*[:=])\s*0", lowered):
        return True
    return None


def is_root_managed_session(meta: Mapping[str, Any], workspace_roots: set[str]) -> bool:
    cwd = meta.get("cwd")
    if not isinstance(cwd, str) or str(Path(cwd).resolve()) not in workspace_roots:
        return False
    if meta.get("originator") != "first-tree" or meta.get("model_provider") != "openai":
        return False
    if meta.get("agent_path") or meta.get("parent_thread_id") or meta.get("forked_from_id"):
        return False
    if meta.get("thread_source") == "subagent" or isinstance(meta.get("source"), dict):
        return False
    return True


def trace_root_default() -> Path:
    codex_root = os.environ.get("CODEX_HOME")
    return Path(codex_root).expanduser() / "sessions" if codex_root else Path.home() / ".codex" / "sessions"


def normalize_chat(value: Mapping[str, Any], window: Window) -> dict[str, Any]:
    chat_id = value.get("chat_id") or value.get("source_id")
    if not isinstance(chat_id, str) or re.fullmatch(UUID_PATTERN, chat_id) is None:
        raise AuditError("Every Chat record must contain chat_id/source_id as a UUID.")
    raw_messages = value.get("messages") or value.get("visible_messages") or []
    if not isinstance(raw_messages, list):
        raise AuditError(f"Chat {chat_id} messages must be an array.")
    messages, invalid_receipt = normalize_message_records(
        (message for message in raw_messages if isinstance(message, dict)),
        window=window,
    )
    messages = [
        message
        for message in messages
        if isinstance(message.get("created_at"), str) and in_window(message["created_at"], window)
    ]
    messages.sort(key=lambda message: (message["created_at"], str(message.get("message_id") or "")))
    gaps = value.get("coverage_gaps")
    coverage_gaps = [str(gap) for gap in gaps] if isinstance(gaps, list) else []
    if invalid_receipt:
        coverage_gaps.append("context_decision_invalid")
    source_agent_id = require_uuid(value.get("source_agent_id"), f"Chat {chat_id} source_agent_id")
    expected_audit_id = audit_id(chat_id, source_agent_id)
    supplied_audit_id = value.get("audit_id")
    if supplied_audit_id is not None and supplied_audit_id != expected_audit_id:
        raise AuditError(f"Chat {chat_id} audit_id does not match its Chat and audited-Agent UUIDs.")
    return {
        "audit_id": expected_audit_id,
        "chat_id": chat_id,
        "title": str(value.get("title") or value.get("topic") or chat_id),
        "authorization": validate_authorization(
            value.get("authorization"),
            f"Chat {chat_id} authorization",
        ),
        "source_agent": require_string(
            value.get("source_agent"),
            f"Chat {chat_id} source_agent",
        ),
        "source_agent_id": source_agent_id,
        "messages": messages,
        "coverage_gaps": coverage_gaps,
    }


def recent_trace_files(trace_root: Path, window: Window) -> list[Path]:
    """Return traces that could contain an in-window call without reading their contents."""
    minimum_mtime = window.start.timestamp() if window.start is not None else None
    files: list[Path] = []
    for path in trace_root.rglob("*.jsonl"):
        try:
            if path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve(strict=True)
            resolved.relative_to(trace_root)
            if minimum_mtime is None or resolved.stat().st_mtime >= minimum_mtime:
                files.append(resolved)
        except (OSError, ValueError):
            continue
    return sorted(files)


def opaque_identity(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def trace_identity(path: Path, trace_root: Path) -> str:
    try:
        relative = path.relative_to(trace_root).as_posix()
    except ValueError:
        relative = path.name
    return opaque_identity("trace", relative)


def tree_identity(identity: WorkspaceIdentity) -> str:
    value = f"{identity.agent_id}\0{identity.bound_tree_root}"
    return opaque_identity("tree", value)


def preflight_trace(
    path: Path,
    trace_root: Path,
    workspace_identity: WorkspaceIdentity,
    authorized_audits: Mapping[tuple[str, str], str],
) -> tuple[TracePreflight | None, dict[str, set[str]]]:
    """Map a trace to one authorized Chat without scanning its full contents."""
    all_audit_ids = set(authorized_audits.values())
    gaps: dict[str, set[str]] = {item: set() for item in all_audit_ids}
    metadata: list[Mapping[str, Any]] = []
    context_chat_ids: set[str] = set()
    relevant_malformed = False
    malformed_metadata_might_match = False
    last_canonical_ids: set[str] | None = None
    last_canonical_line: int | None = None
    bytes_seen = 0
    lines_seen = 0
    workspace_bytes = str(workspace_identity.workspace).encode("utf-8")

    try:
        with path.open("rb") as handle:
            while (
                bytes_seen < TRACE_PREFLIGHT_MAX_BYTES
                and lines_seen < TRACE_PREFLIGHT_MAX_LINES
            ):
                remaining = TRACE_PREFLIGHT_MAX_BYTES - bytes_seen
                raw_line = handle.readline(remaining + 1)
                if not raw_line:
                    break
                if len(raw_line) > remaining:
                    break
                bytes_seen += len(raw_line)
                lines_seen += 1
                if b'"session_meta"' not in raw_line and (
                    b"<first-tree-current-chat-context" not in raw_line
                ):
                    continue
                try:
                    line = raw_line.decode("utf-8")
                    row = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    relevant_malformed = True
                    if b'"session_meta"' in raw_line and workspace_bytes in raw_line:
                        malformed_metadata_might_match = True
                    continue
                if not isinstance(row, dict):
                    relevant_malformed = True
                    continue
                if row.get("type") == "session_meta":
                    payload = row.get("payload")
                    if isinstance(payload, dict):
                        metadata.append(payload)
                    else:
                        relevant_malformed = True
                    continue
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    if row.get("type") in {"response_item", "event_msg"}:
                        relevant_malformed = True
                    continue

                is_canonical = (
                    row.get("type") == "response_item"
                    and payload.get("type") == "message"
                    and payload.get("role") == "user"
                )
                if is_canonical:
                    user_text = payload_text(payload.get("content"))
                    if CHAT_CONTEXT_PATTERN.search(user_text) is None:
                        continue
                    found_ids = set(chat_ids_from_text(user_text))
                    if len(found_ids) != 1:
                        relevant_malformed = True
                    else:
                        context_chat_ids.update(found_ids)
                    last_canonical_ids = found_ids
                    last_canonical_line = lines_seen
                    continue

                is_user_message_mirror = (
                    row.get("type") == "event_msg"
                    and payload.get("type") == "user_message"
                )
                if is_user_message_mirror:
                    mirror_text = payload_text(payload)
                    if CHAT_CONTEXT_PATTERN.search(mirror_text) is None:
                        continue
                    mirror_ids = set(chat_ids_from_text(mirror_text))
                    if last_canonical_line == lines_seen - 1 and (
                        len(mirror_ids) != 1 or mirror_ids != last_canonical_ids
                    ):
                        relevant_malformed = True
                    continue

                # Context blocks echoed by tool output, compaction, or another
                # non-canonical trace row are neither identity evidence nor a
                # reason to reject an otherwise valid bounded header.
    except OSError:
        return None, gaps

    workspace_roots = {str(workspace_identity.workspace)}
    matching_metadata = [
        item for item in metadata if is_root_managed_session(item, workspace_roots)
    ]
    if not matching_metadata:
        if malformed_metadata_might_match:
            for item in all_audit_ids:
                gaps[item].add("codex_trace_preflight_malformed_or_ambiguous")
        return None, gaps
    if len(metadata) != 1 or len(matching_metadata) != 1 or relevant_malformed:
        for item in all_audit_ids:
            gaps[item].add("codex_trace_preflight_malformed_or_ambiguous")
        return None, gaps
    if len(context_chat_ids) != 1:
        matched = {
            authorized_audits[(chat_id, workspace_identity.agent_id)]
            for chat_id in context_chat_ids
            if (chat_id, workspace_identity.agent_id) in authorized_audits
        }
        for item in matched or all_audit_ids:
            gaps[item].add(
                "codex_trace_preflight_unmapped"
                if not context_chat_ids
                else "codex_trace_preflight_ambiguous_chat"
            )
        return None, gaps

    chat_id = next(iter(context_chat_ids))
    current_audit_id = authorized_audits.get((chat_id, workspace_identity.agent_id))
    if current_audit_id is None:
        # The bounded header proves this is a different Chat.  Exact-Chat scope
        # does not authorize opening any more of it, and it is not a coverage
        # gap for the Chats that were explicitly selected.
        return None, gaps
    return (
        TracePreflight(
            path=path,
            trace_id=trace_identity(path, trace_root),
            audit_id=current_audit_id,
            agent_id=workspace_identity.agent_id,
            workspace=workspace_identity.workspace,
        ),
        gaps,
    )


def clipped(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def redact_local_roots(
    text: str,
    workspace: Path,
    tree_root: Path,
) -> str:
    result = text
    replacements = (
        (tree_root.as_posix(), "<tree-root>"),
        (workspace.as_posix(), "<agent-workspace>"),
    )
    for raw, replacement in replacements:
        result = result.replace(raw, replacement)
        result = result.replace(raw.replace("/", "\\/"), replacement)
    return result


def trace_reads(
    preflight: TracePreflight,
    tree_root: Path,
    tree_id: str,
    window: Window,
    max_passage_chars: int,
) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    """Read one trace only after its exact Chat-Agent preflight was accepted."""
    reads: list[dict[str, Any]] = []
    sessions = {preflight.trace_id}
    gaps: set[str] = set()
    expected_chat_id = preflight.audit_id.split("@", 1)[0]
    default_workdir = preflight.workspace

    calls: dict[str, dict[str, Any]] = {}
    outputs: dict[str, tuple[str, str | None, bool]] = {}
    try:
        with preflight.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict) or row.get("type") != "response_item":
                    continue
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    continue
                payload_type = payload.get("type")
                if payload_type == "message" and payload.get("role") == "user":
                    user_text = payload_text(payload.get("content"))
                    if CHAT_CONTEXT_PATTERN.search(user_text) is None:
                        continue
                    all_ids = set(chat_ids_from_text(user_text))
                    if all_ids != {expected_chat_id}:
                        gaps.add("trace_chat_boundary_changed_after_preflight")
                        # Do not read any rows beyond an unexpected Chat
                        # boundary.  Evidence already seen remains associated
                        # with the preflight-authorized Chat only.
                        break
                    continue
                if payload_type in {"custom_tool_call", "function_call"}:
                    call_id = payload.get("call_id")
                    if not isinstance(call_id, str):
                        continue
                    tool_name = str(payload.get("name") or "")
                    is_continuation = (
                        tool_name in SHELL_CONTINUATION_TOOLS | CELL_CONTINUATION_TOOLS
                    )
                    node_paths = extract_node_paths(payload, (tree_root,), default_workdir)
                    if not is_continuation:
                        read_gap = pure_markdown_read_gap(tool_name, payload, node_paths)
                        if read_gap == "not_a_tree_markdown_read":
                            continue
                        if read_gap is not None:
                            gaps.add(read_gap)
                            continue
                    calls[call_id] = {
                        "timestamp": row.get("timestamp"),
                        "payload": payload,
                        "arguments": parse_tool_arguments(payload),
                        "node_paths": node_paths,
                    }
                    continue
                if payload_type in {"custom_tool_call_output", "function_call_output"}:
                    call_id = payload.get("call_id")
                    if not isinstance(call_id, str) or call_id not in calls:
                        continue
                    output, output_truncated = clipped(
                        redact_local_roots(
                            payload_text(payload.get("output")),
                            preflight.workspace,
                            tree_root,
                        ),
                        max_passage_chars,
                    )
                    outputs[call_id] = (
                        output,
                        row.get("timestamp"),
                        output_truncated,
                    )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        gaps.add("codex_trace_malformed_or_partially_cleaned")
        return reads, sessions, gaps

    shell_sessions: dict[str, str] = {}
    cell_sessions: dict[str, str] = {}
    continuation_outputs: dict[str, list[tuple[str, str | None, str | None, bool]]] = {}
    for call_id, call in calls.items():
        payload = call["payload"]
        tool_name = str(payload.get("name") or "")
        output, output_completed_at, output_truncated = outputs.get(call_id, ("", None, False))
        if tool_name in EXEC_COMMAND_TOOLS:
            match = SHELL_SESSION_PATTERN.search(output)
            if match:
                shell_sessions[match.group(1)] = call_id
        elif tool_name == "functions.exec":
            match = CELL_SESSION_PATTERN.search(output)
            if match:
                cell_sessions[match.group(1)] = call_id
        if tool_name in SHELL_CONTINUATION_TOOLS:
            session_id = call["arguments"].get("session_id")
            original_call_id = shell_sessions.get(str(session_id))
            if original_call_id is not None:
                continuation_outputs.setdefault(original_call_id, []).append(
                    (output, output_completed_at, call.get("timestamp"), output_truncated)
                )
        elif tool_name in CELL_CONTINUATION_TOOLS:
            cell_id = call["arguments"].get("cell_id")
            original_call_id = cell_sessions.get(str(cell_id))
            if original_call_id is not None:
                continuation_outputs.setdefault(original_call_id, []).append(
                    (output, output_completed_at, call.get("timestamp"), output_truncated)
                )

    for items in continuation_outputs.values():
        items.sort(key=lambda item: str(item[2] or ""))

    for call_id, call in calls.items():
        timestamp = call.get("timestamp")
        if not isinstance(timestamp, str) or not in_window(timestamp, window):
            continue
        payload = call["payload"]
        tool_name = str(payload.get("name") or "")
        if tool_name in SHELL_CONTINUATION_TOOLS | CELL_CONTINUATION_TOOLS:
            continue
        node_paths = call["node_paths"]
        initial_output, completed_at, initial_truncated = outputs.get(call_id, ("", None, False))
        continuations = continuation_outputs.get(call_id, [])
        output = initial_output
        output_was_truncated = initial_truncated
        if continuations:
            output = "\n".join([output, *(item[0] for item in continuations)])
            completed_at = continuations[-1][1]
            output_was_truncated = output_was_truncated or any(item[3] for item in continuations)
        initial_handle = (
            SHELL_SESSION_PATTERN.search(initial_output)
            if tool_name in EXEC_COMMAND_TOOLS
            else CELL_SESSION_PATTERN.search(initial_output)
            if tool_name == "functions.exec"
            else None
        )
        if initial_handle is not None:
            last_output = continuations[-1][0] if continuations else ""
            last_pending = (
                SHELL_SESSION_PATTERN.search(last_output)
                if tool_name in EXEC_COMMAND_TOOLS
                else CELL_SESSION_PATTERN.search(last_output)
            )
            if not continuations or last_pending is not None:
                gaps.add("tree_read_output_pending")
                continue
        if not output.strip():
            gaps.add("tree_read_output_missing")
            continue
        success = output_success(output)
        if success is False:
            gaps.add("tree_read_command_failed")
            continue
        if success is None:
            success = True
        passage, passage_truncated = clipped(output, max_passage_chars)
        passage_truncated = passage_truncated or output_was_truncated
        if passage_truncated:
            gaps.add("tree_read_passage_truncated")
        normalized_name = tool_name.rsplit(".", 1)[-1]
        command = f"{normalized_name} {node_paths[0]}"
        command_truncated = False
        read_id = hashlib.sha256(
            f"{preflight.trace_id}:{call_id}".encode()
        ).hexdigest()[:20]
        reads.append(
            {
                "read_id": read_id,
                "timestamp": timestamp,
                "completed_at": completed_at,
                "session_file": preflight.trace_id,
                "call_id": call_id,
                "tool_name": tool_name,
                "reader_agent_id": preflight.agent_id,
                "tree_identity": tree_id,
                "node_paths": node_paths,
                "content_class_hint": content_class_hint(node_paths),
                "command": command,
                "command_truncated": command_truncated,
                "passage": passage,
                "passage_truncated": passage_truncated,
                "success": success,
            }
        )
    return reads, sessions, gaps


def collect_evidence(args: argparse.Namespace) -> None:
    workspace_identity = parse_agent_workspace(args.agent_workspace)
    artifact_root = resolve_artifact_root(args.artifact_root, workspace_identity)
    chats_path = artifact_path(artifact_root, args.chats, field="--chats", must_exist=True)
    output_path = artifact_path(artifact_root, args.output, field="--output", must_exist=False)
    require_distinct_paths({"--chats": chats_path, "--output": output_path})
    window = resolve_window(args.days, args.now)
    chat_rows = [normalize_chat(row, window) for row in iter_jsonl(chats_path)]
    if not chat_rows:
        raise AuditError("No authorized Chat records were provided.")
    if len({chat["audit_id"] for chat in chat_rows}) != len(chat_rows):
        raise AuditError("The Chat export contains duplicate Chat and audited-Agent pairs.")
    scoped_identities = {
        (str(chat["source_agent"]), chat["source_agent_id"]) for chat in chat_rows
    }
    if len(scoped_identities) != 1:
        raise AuditError("Chat export must contain one exact Agent name and UUID.")
    authorizations = {chat["authorization"] for chat in chat_rows}
    if len(authorizations) != 1:
        raise AuditError("Chat export must not mix Agent-level and Chat-level authorization.")
    chats = {chat["audit_id"]: chat for chat in chat_rows}
    authorized_audits = {
        (chat["chat_id"], chat["source_agent_id"]): chat["audit_id"] for chat in chat_rows
    }
    scoped_agent_name, scoped_agent_id = next(iter(scoped_identities))
    if (
        workspace_identity.agent_name != scoped_agent_name
        or workspace_identity.agent_id != scoped_agent_id
    ):
        raise AuditError(
            "--agent-workspace identity must match the one exact Agent name and UUID in --chats."
        )

    raw_tree_root = Path(args.tree_root).expanduser()
    if not raw_tree_root.is_absolute() or raw_tree_root.is_symlink():
        raise AuditError("--tree-root must be an absolute, non-symbolic-link directory.")
    try:
        tree_root = raw_tree_root.resolve(strict=True)
    except OSError as error:
        raise AuditError(f"Could not resolve --tree-root: {error}") from error
    if not tree_root.is_dir():
        raise AuditError("--tree-root is not a directory.")
    if tree_root != workspace_identity.bound_tree_root:
        raise AuditError(
            "--tree-root must exactly match the Context Tree bound in workspace identity."
        )
    current_tree_id = tree_identity(workspace_identity)

    raw_trace_root = (
        Path(args.trace_root).expanduser()
        if args.trace_root
        else trace_root_default()
    )
    if raw_trace_root.is_symlink():
        raise AuditError("--trace-root must not be a symbolic link.")
    trace_root = raw_trace_root.resolve()
    if not trace_root.is_dir():
        for chat in chats.values():
            chat["coverage_gaps"].append("codex_trace_root_missing_or_cleaned")
        trace_files: list[Path] = []
    else:
        trace_files = recent_trace_files(trace_root, window)

    per_audit_reads: dict[str, list[dict[str, Any]]] = {item: [] for item in chats}
    per_audit_sessions: dict[str, set[str]] = {item: set() for item in chats}
    per_audit_gaps: dict[str, set[str]] = {item: set() for item in chats}

    for trace_file in trace_files:
        preflight, preflight_gaps = preflight_trace(
            trace_file,
            trace_root,
            workspace_identity,
            authorized_audits,
        )
        for item in chats:
            per_audit_gaps[item].update(preflight_gaps[item])
        if preflight is None:
            continue
        reads, sessions, gaps = trace_reads(
            preflight,
            tree_root,
            current_tree_id,
            window,
            args.max_passage_chars,
        )
        per_audit_reads[preflight.audit_id].extend(reads)
        per_audit_sessions[preflight.audit_id].update(sessions)
        per_audit_gaps[preflight.audit_id].update(gaps)

    output_rows: list[dict[str, Any]] = []
    for current_audit_id, chat in sorted(chats.items()):
        chat_id = chat["chat_id"]
        reads = sorted(
            per_audit_reads[current_audit_id], key=lambda item: (item["timestamp"], item["read_id"])
        )
        messages = []
        for message in chat["messages"]:
            sanitized = dict(message)
            sanitized["content"] = redact_local_roots(
                str(message.get("content") or ""),
                workspace_identity.workspace,
                tree_root,
            )
            messages.append(sanitized)
        visible_tree_mentions = [
            message
            for message in messages
            if TREE_MENTION_PATTERN.search(str(message.get("content") or "")) is not None
        ]
        choice_messages = []
        agent_messages = [
            message for message in messages if message.get("sender_id") == chat["source_agent_id"]
        ]
        receipt_messages = [
            message for message in agent_messages if "decision_receipt" in message
        ]
        if reads:
            earliest_read = parse_datetime(reads[0]["timestamp"])
            choice_messages = [
                message
                for message in agent_messages
                if isinstance(message.get("created_at"), str)
                and parse_datetime(message["created_at"]) >= earliest_read
            ]
        elif visible_tree_mentions or receipt_messages:
            choice_messages_by_id = {
                message["message_id"]: message
                for message in [
                    *visible_tree_mentions,
                    *receipt_messages,
                ]
                if message.get("sender_id") == chat["source_agent_id"]
                and isinstance(message.get("message_id"), str)
            }
            choice_messages = sorted(
                choice_messages_by_id.values(),
                key=lambda message: (
                    str(message.get("created_at") or ""),
                    str(message.get("message_id") or ""),
                ),
            )
        candidate_status = (
            "candidate"
            if reads or visible_tree_mentions or receipt_messages
            else "outside_candidate_set"
        )
        gaps = set(chat["coverage_gaps"]) | per_audit_gaps[current_audit_id]
        if not per_audit_sessions[current_audit_id]:
            gaps.add("no_mapped_codex_trace")
        elif (
            per_audit_sessions[current_audit_id]
            and not reads
            and (visible_tree_mentions or receipt_messages)
        ):
            gaps.add("no_successful_tree_content_read")
        output_rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "audit_id": current_audit_id,
                "chat": {
                    "chat_id": chat_id,
                    "title": chat["title"],
                    "authorization": chat["authorization"],
                    "source_agent": chat["source_agent"],
                    "source_agent_id": chat["source_agent_id"],
                    "message_count": len(messages),
                },
                "window": {"start": window_start_text(window), "end": isoformat(window.end)},
                "tree_identity": current_tree_id,
                "candidate_status": candidate_status,
                "mapped_trace_files": sorted(per_audit_sessions[current_audit_id]),
                "reads": reads,
                "visible_messages": messages,
                "visible_choice_candidates": choice_messages,
                "visible_tree_mentions": visible_tree_mentions,
                "coverage_gaps": sorted(gaps),
            }
        )
    write_jsonl(output_path, output_rows)


def string_id_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise AuditError(f"{field} must be an array.")
    items = [require_string(item, field) for item in value]
    if len(set(items)) != len(items):
        raise AuditError(f"{field} must not contain duplicate IDs.")
    return items


def optional_text(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AuditError(f"{field} must be a string or null.")
    return value.strip() or None


def validate_effect_rubric(
    value: Any,
    *,
    field: str,
    original_judgment: str,
) -> dict[str, bool | None]:
    if not isinstance(value, dict):
        raise AuditError(f"{field} must be an object.")
    rubric: dict[str, bool | None] = {}
    for key in RUBRIC_KEYS:
        item = value.get(key)
        if item is not True and item is not False and item is not None:
            raise AuditError(f"{field}.{key} must be true, false, or null.")
        rubric[key] = item
    if original_judgment == "verified":
        if any(rubric[key] is not True for key in RUBRIC_KEYS):
            raise AuditError(
                f"{field} must make all five checks true for verified."
            )
    elif (
        any(rubric[key] is not True for key in RUBRIC_KEYS[:4])
        or rubric["influence_visible"] is True
    ):
        raise AuditError(
            f"{field} requires the first four checks true and influence_visible false or null for probable."
        )
    return rubric


def load_task_judgments(path: Path) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    task_ids: set[str] = set()
    for row in iter_jsonl(path):
        if row.get("schema_version") != SCHEMA_VERSION:
            raise AuditError(
                f"Every Task judgment must use schema_version {SCHEMA_VERSION}."
            )
        task_id = require_string(row.get("task_id"), "task.task_id")
        if task_id in task_ids:
            raise AuditError(f"Duplicate Task judgment {task_id}.")
        task_ids.add(task_id)
        status = require_string(row.get("status"), f"task[{task_id}].status")
        if status not in TASK_STATUS_VALUES:
            raise AuditError(
                f"task[{task_id}].status must be one of: {', '.join(sorted(TASK_STATUS_VALUES))}."
            )
        if "support" in row:
            raise AuditError(
                f"task[{task_id}] must not persist support; the reporter derives it."
            )
        normalized = dict(row)
        normalized["task_id"] = task_id
        normalized["status"] = status
        normalized["objective"] = optional_text(
            row.get("objective"), field=f"task[{task_id}].objective"
        )
        normalized["object_scope"] = optional_text(
            row.get("object_scope"), field=f"task[{task_id}].object_scope"
        )
        normalized["outcome"] = optional_text(
            row.get("outcome"), field=f"task[{task_id}].outcome"
        )
        task_type = row.get("task_type")
        if task_type is not None and (
            not isinstance(task_type, str) or task_type not in TASK_TYPE_VALUES
        ):
            raise AuditError(
                f"task[{task_id}].task_type must be one of: {', '.join(sorted(TASK_TYPE_VALUES))}."
            )
        normalized["task_type"] = task_type
        normalized["started_at"] = isoformat(
            parse_datetime(
                require_string(row.get("started_at"), f"task[{task_id}].started_at"),
                field=f"task {task_id} started_at",
            )
        )
        normalized["ended_at"] = isoformat(
            parse_datetime(
                require_string(row.get("ended_at"), f"task[{task_id}].ended_at"),
                field=f"task {task_id} ended_at",
            )
        )
        if parse_datetime(normalized["started_at"]) > parse_datetime(normalized["ended_at"]):
            raise AuditError(f"task[{task_id}] starts after it ends.")

        fragments = row.get("source_fragments")
        if not isinstance(fragments, list) or not fragments:
            raise AuditError(f"task[{task_id}].source_fragments must be a non-empty array.")
        normalized_fragments: list[dict[str, Any]] = []
        for index, fragment in enumerate(fragments):
            field = f"task[{task_id}].source_fragments[{index}]"
            if not isinstance(fragment, dict):
                raise AuditError(f"{field} must be an object.")
            current_audit_id = require_string(fragment.get("audit_id"), f"{field}.audit_id")
            message_ids = string_id_list(
                fragment.get("message_ids"), field=f"{field}.message_ids"
            )
            if not message_ids:
                raise AuditError(f"{field}.message_ids must not be empty.")
            projected_fragment: dict[str, Any] = {
                "audit_id": current_audit_id,
                "message_ids": message_ids,
            }
            linkage = fragment.get("linkage")
            if linkage is not None:
                if not isinstance(linkage, dict):
                    raise AuditError(f"{field}.linkage must be an object.")
                kind = require_string(linkage.get("kind"), f"{field}.linkage.kind")
                if kind not in LINKAGE_VALUES:
                    raise AuditError(
                        f"{field}.linkage.kind must be one of: {', '.join(sorted(LINKAGE_VALUES))}."
                    )
                projected_fragment["linkage"] = {
                    "kind": kind,
                    "key": require_string(linkage.get("key"), f"{field}.linkage.key"),
                }
            normalized_fragments.append(projected_fragment)
        normalized["source_fragments"] = normalized_fragments

        if status == "excluded":
            if any(field in row for field in ("exposure", "effects")):
                raise AuditError(
                    f"Excluded task[{task_id}] must not contain exposure or effects."
                )
            normalized["exclusion_reason"] = require_string(
                row.get("exclusion_reason"), f"task[{task_id}].exclusion_reason"
            )
            if "sampling_order" in row or "saturation_signals" in row:
                raise AuditError(
                    f"Excluded task[{task_id}] must not participate in clear-Task sampling."
                )
            tasks.append(normalized)
            continue

        if not all(
            normalized[field] is not None
            for field in ("objective", "object_scope", "outcome")
        ):
            raise AuditError(
                f"Clear task[{task_id}] requires objective, object_scope, and outcome."
            )
        if task_type not in TASK_TYPE_VALUES:
            raise AuditError(f"Clear task[{task_id}] requires a valid task_type.")
        sampling_order = row.get("sampling_order")
        if not isinstance(sampling_order, int) or isinstance(sampling_order, bool) or sampling_order <= 0:
            raise AuditError(f"Clear task[{task_id}].sampling_order must be a positive integer.")
        normalized["sampling_order"] = sampling_order
        signals = row.get("saturation_signals", [])
        if not isinstance(signals, list) or any(
            not isinstance(signal, str) or signal not in SATURATION_SIGNAL_VALUES
            for signal in signals
        ):
            raise AuditError(
                f"task[{task_id}].saturation_signals contains an unknown signal."
            )
        if len(set(signals)) != len(signals):
            raise AuditError(f"task[{task_id}].saturation_signals must not contain duplicates.")
        normalized["saturation_signals"] = sorted(signals)

        exposure = row.get("exposure")
        if not isinstance(exposure, dict):
            raise AuditError(f"Clear task[{task_id}] requires an exposure object.")
        exposure_status = require_string(
            exposure.get("status"), f"task[{task_id}].exposure.status"
        )
        if exposure_status not in EXPOSURE_VALUES:
            raise AuditError(
                f"task[{task_id}].exposure.status must be confirmed or unresolved."
            )
        exposure_reads = string_id_list(
            exposure.get("read_ids", []),
            field=f"task[{task_id}].exposure.read_ids",
        )
        reason = optional_text(
            exposure.get("reason"), field=f"task[{task_id}].exposure.reason"
        )
        if exposure_status == "confirmed" and not exposure_reads:
            raise AuditError(f"Confirmed exposure for task[{task_id}] requires read_ids.")
        if exposure_status == "unresolved" and reason is None:
            raise AuditError(f"Unresolved exposure for task[{task_id}] requires a reason.")
        if exposure_status == "unresolved" and exposure_reads:
            raise AuditError(
                f"Unresolved exposure for task[{task_id}] must not contain read_ids."
            )
        normalized["exposure"] = {
            "status": exposure_status,
            "read_ids": exposure_reads,
            "reason": reason,
        }

        effects = row.get("effects")
        if not isinstance(effects, list):
            raise AuditError(f"task[{task_id}].effects must be an array.")
        normalized_effects: list[dict[str, Any]] = []
        for index, effect in enumerate(effects):
            field = f"task[{task_id}].effects[{index}]"
            if not isinstance(effect, dict):
                raise AuditError(f"{field} must be an object.")
            if "support" in effect:
                raise AuditError(
                    f"{field} must not persist support; the reporter derives it."
                )
            effect_value = require_string(effect.get("effect"), f"{field}.effect")
            if effect_value not in EFFECT_VALUES:
                raise AuditError(
                    f"{field}.effect must be one of: {', '.join(sorted(EFFECT_VALUES))}."
                )
            original_judgment = require_string(
                effect.get("original_judgment"), f"{field}.original_judgment"
            )
            if original_judgment not in {"verified", "probable"}:
                raise AuditError(
                    f"{field}.original_judgment must be verified or probable."
                )
            rubric = validate_effect_rubric(
                effect.get("rubric"),
                field=f"{field}.rubric",
                original_judgment=original_judgment,
            )
            effect_reads = string_id_list(
                effect.get("read_ids"), field=f"{field}.read_ids"
            )
            choice_ids = string_id_list(
                effect.get("choice_message_ids"),
                field=f"{field}.choice_message_ids",
            )
            if not effect_reads or not choice_ids:
                raise AuditError(f"{field} requires read_ids and choice_message_ids.")
            normalized_effects.append(
                {
                    "effect": effect_value,
                    "original_judgment": original_judgment,
                    "rubric": rubric,
                    "read_ids": effect_reads,
                    "choice_message_ids": choice_ids,
                    "outcome_anchor": require_string(
                        effect.get("outcome_anchor"), f"{field}.outcome_anchor"
                    ),
                    "summary": require_string(effect.get("summary"), f"{field}.summary"),
                }
            )
        normalized["effects"] = normalized_effects
        if exposure_status == "unresolved" and normalized_effects:
            raise AuditError(
                f"Unresolved exposure for task[{task_id}] must not contain effects."
            )
        tasks.append(normalized)
    return tasks


def timestamp_in_task(value: Any, *, start: datetime, end: datetime, field: str) -> datetime:
    timestamp = parse_datetime(require_string(value, field), field=field)
    if not start <= timestamp <= end:
        raise AuditError(f"{field} is outside the Task window.")
    return timestamp


def validate_task_refs(
    candidates: Sequence[Mapping[str, Any]],
    tasks: Sequence[dict[str, Any]],
) -> None:
    candidates_by_id = {candidate["audit_id"]: candidate for candidate in candidates}
    messages_by_audit: dict[str, dict[str, Mapping[str, Any]]] = {}
    choices: dict[str, tuple[str, Mapping[str, Any]]] = {}
    reads: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for candidate in candidates:
        current_audit_id = candidate["audit_id"]
        visible_messages = candidate.get("visible_messages")
        if not isinstance(visible_messages, list):
            visible_messages = [
                *candidate.get("visible_choice_candidates", []),
                *candidate.get("visible_tree_mentions", []),
            ]
        message_index = {
            message.get("message_id"): message
            for message in visible_messages
            if isinstance(message, dict) and isinstance(message.get("message_id"), str)
        }
        messages_by_audit[current_audit_id] = message_index
        for choice in candidate["visible_choice_candidates"]:
            message_id = choice.get("message_id")
            if isinstance(message_id, str):
                if message_id in choices:
                    raise AuditError(f"Choice message ID {message_id} is not globally unique.")
                choices[message_id] = (current_audit_id, choice)
        for read in candidate["reads"]:
            read_id = read.get("read_id")
            if isinstance(read_id, str):
                if read_id in reads:
                    raise AuditError(f"Read ID {read_id} is not globally unique.")
                reads[read_id] = (current_audit_id, read)

    read_owners: dict[str, str] = {}
    choice_owners: dict[str, str] = {}
    clear_orders: list[int] = []
    for task in tasks:
        task_id = task["task_id"]
        start = parse_datetime(task["started_at"], field=f"task {task_id} started_at")
        end = parse_datetime(task["ended_at"], field=f"task {task_id} ended_at")
        source_audits: set[str] = set()
        source_message_ids: set[str] = set()
        linkages: set[tuple[str, str]] = set()
        for index, fragment in enumerate(task["source_fragments"]):
            field = f"task[{task_id}].source_fragments[{index}]"
            current_audit_id = fragment["audit_id"]
            candidate = candidates_by_id.get(current_audit_id)
            if candidate is None:
                raise AuditError(
                    f"{field} references an unauthorized Chat-Agent audit {current_audit_id}."
                )
            source_audits.add(current_audit_id)
            window = candidate["window"]
            acquisition_start = (
                parse_datetime(window["start"], field=f"{field} acquisition start")
                if isinstance(window.get("start"), str)
                else None
            )
            acquisition_end = parse_datetime(
                require_string(window.get("end"), f"{field} acquisition end"),
                field=f"{field} acquisition end",
            )
            if end > acquisition_end or (acquisition_start is not None and start < acquisition_start):
                raise AuditError(f"task[{task_id}] is outside its authorized acquisition window.")
            for message_id in fragment["message_ids"]:
                if message_id in source_message_ids:
                    raise AuditError(
                        f"task[{task_id}] duplicates source message {message_id}."
                    )
                source_message_ids.add(message_id)
                message = messages_by_audit[current_audit_id].get(message_id)
                if message is None:
                    raise AuditError(
                        f"{field} references message {message_id} outside its authorized Chat."
                    )
                timestamp_in_task(
                    message.get("created_at"),
                    start=start,
                    end=end,
                    field=f"task {task_id} source message {message_id}",
                )
            linkage = fragment.get("linkage")
            if isinstance(linkage, dict):
                linkages.add((linkage["kind"], linkage["key"]))
        if len(source_audits) > 1:
            if len(linkages) != 1 or any(
                "linkage" not in fragment for fragment in task["source_fragments"]
            ):
                raise AuditError(
                    f"Cross-Chat task[{task_id}] requires one explicit shared linkage."
                )
        elif linkages:
            raise AuditError(
                f"Single-Chat task[{task_id}] must not claim cross-Chat linkage."
            )

        if task["status"] == "excluded":
            continue
        clear_orders.append(task["sampling_order"])
        exposure_reads = set(task["exposure"]["read_ids"])
        for read_id in exposure_reads:
            item = reads.get(read_id)
            if item is None:
                raise AuditError(f"task[{task_id}] references unknown read {read_id}.")
            current_audit_id, read = item
            if current_audit_id not in source_audits:
                raise AuditError(
                    f"task[{task_id}] read {read_id} is outside its source Chat fragments."
                )
            timestamp_in_task(
                read.get("timestamp"),
                start=start,
                end=end,
                field=f"task {task_id} read {read_id} timestamp",
            )
            timestamp_in_task(
                read.get("completed_at"),
                start=start,
                end=end,
                field=f"task {task_id} read {read_id} completion",
            )
            previous = read_owners.setdefault(read_id, task_id)
            if previous != task_id:
                raise AuditError(
                    f"Read {read_id} is copied across incompatible Tasks {previous} and {task_id}."
                )

        for effect in task["effects"]:
            if not set(effect["read_ids"]).issubset(exposure_reads):
                raise AuditError(
                    f"Effect in task[{task_id}] references reads outside its exposure."
                )
            read_times = [
                parse_datetime(
                    reads[read_id][1]["completed_at"],
                    field=f"task {task_id} read {read_id} completion",
                )
                for read_id in effect["read_ids"]
            ]
            choice_times: list[datetime] = []
            for message_id in effect["choice_message_ids"]:
                item = choices.get(message_id)
                if item is None:
                    raise AuditError(
                        f"Effect in task[{task_id}] references unknown choice {message_id}."
                    )
                current_audit_id, choice = item
                if current_audit_id not in source_audits:
                    raise AuditError(
                        f"task[{task_id}] choice {message_id} is outside its source Chat fragments."
                    )
                choice_times.append(
                    timestamp_in_task(
                        choice.get("created_at"),
                        start=start,
                        end=end,
                        field=f"task {task_id} choice {message_id}",
                    )
                )
                previous = choice_owners.setdefault(message_id, task_id)
                if previous != task_id:
                    raise AuditError(
                        f"Choice {message_id} is copied across incompatible Tasks {previous} and {task_id}."
                    )
            if max(read_times) > min(choice_times):
                raise AuditError(
                    f"Effect in task[{task_id}] cites a read completed after its earliest choice."
                )

    if sorted(clear_orders) != list(range(1, len(clear_orders) + 1)):
        raise AuditError(
            "Clear Task sampling_order values must be unique and contiguous from 1."
        )
    sampling_summary(tasks)


def table_row(columns: Sequence[Any]) -> str:
    return "| " + " | ".join(str(column).replace("|", "\\|") for column in columns) + " |"


def independent_effect_id(effect: Mapping[str, Any]) -> str:
    identity = {
        "effect": effect["effect"],
        "read_ids": sorted(effect["read_ids"]),
        "choice_message_ids": sorted(effect["choice_message_ids"]),
        "outcome_anchor": effect["outcome_anchor"],
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return f"effect-{digest}"


def build_task_evidence(tasks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for task in sorted(
        tasks,
        key=lambda item: (
            item["status"] != "clear",
            int(item.get("sampling_order") or 0),
            item["task_id"],
        ),
    ):
        row = dict(task)
        if task["status"] == "clear":
            effects = []
            for effect in task["effects"]:
                projected = dict(effect)
                projected["independent_effect_id"] = independent_effect_id(effect)
                projected["derived_support"] = (
                    "definite"
                    if task["exposure"]["status"] == "confirmed"
                    and effect["original_judgment"] == "verified"
                    else "limited"
                )
                effects.append(projected)
            row["effects"] = effects
        evidence.append(row)
    return evidence


def sampling_summary(tasks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    clear = sorted(
        (task for task in tasks if task["status"] == "clear"),
        key=lambda task: task["sampling_order"],
    )
    expansions: list[dict[str, Any]] = []
    initial_task_types = {task["task_type"] for task in clear[:100]}
    missing_task_types = sorted(TASK_TYPE_VALUES - initial_task_types)
    type_coverage_complete = not missing_task_types and len(clear) >= 100
    cumulative_effect_types = {
        effect["effect"]
        for task in clear[:100]
        for effect in task["effects"]
    }
    consecutive_empty = 0
    saturated_at: int | None = None
    for offset in range(100, len(clear), 20):
        batch = clear[offset : offset + 20]
        if len(batch) < 20:
            break
        signals = sorted(
            {
                signal
                for task in batch
                for signal in task.get("saturation_signals", [])
            }
        )
        batch_effect_types = {
            effect["effect"] for task in batch for effect in task["effects"]
        }
        new_effect_types = sorted(batch_effect_types - cumulative_effect_types)
        declares_new_effect_type = "new_effect_type" in signals
        if bool(new_effect_types) != declares_new_effect_type:
            expectation = (
                "must declare new_effect_type"
                if new_effect_types
                else "must not declare new_effect_type"
            )
            raise AuditError(
                f"Sampling expansion {offset + 1}-{offset + 20} {expectation}; "
                "the annotation disagrees with observed effect types."
            )
        cumulative_effect_types.update(batch_effect_types)
        non_effect_signals = {
            signal for signal in signals if signal != "new_effect_type"
        }
        batch_has_novelty = bool(new_effect_types or non_effect_signals)
        consecutive_empty = 0 if batch_has_novelty else consecutive_empty + 1
        expansions.append(
            {
                "start": offset + 1,
                "end": offset + 20,
                "signals": signals,
                "new_effect_types": new_effect_types,
            }
        )
        if consecutive_empty == 2 and type_coverage_complete:
            saturated_at = offset + 20
            break
    if len(clear) < 100:
        status = "minimum_not_met"
    elif not type_coverage_complete:
        status = "task_type_coverage_not_met"
    elif saturated_at is not None:
        status = "saturated"
    else:
        status = "continue_sampling"
    if saturated_at is not None and len(clear) > saturated_at:
        raise AuditError(
            f"Task sample continued past reproducible saturation at {saturated_at} clear Tasks."
        )
    return {
        "clear_tasks": len(clear),
        "status": status,
        "saturated_at": saturated_at,
        "expansions": expansions,
        "missing_task_types": missing_task_types,
    }


def render_report(
    candidates: Sequence[Mapping[str, Any]],
    tasks: Sequence[Mapping[str, Any]],
    generated_at: datetime,
) -> str:
    clear_tasks = [task for task in tasks if task["status"] == "clear"]
    excluded_tasks = [task for task in tasks if task["status"] == "excluded"]
    confirmed_exposure_tasks = [
        task for task in clear_tasks if task["exposure"]["status"] == "confirmed"
    ]
    unresolved_exposure_tasks = [
        task for task in clear_tasks if task["exposure"]["status"] == "unresolved"
    ]
    effect_tasks = [task for task in clear_tasks if task["effects"]]
    independent_effects: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    for task in clear_tasks:
        for effect in task["effects"]:
            independent_effects.setdefault(
                effect["independent_effect_id"],
                (task, effect),
            )
    effect_counts = Counter(
        effect["effect"] for _, effect in independent_effects.values()
    )
    task_type_effect = Counter(
        (task["task_type"], effect["effect"])
        for task, effect in independent_effects.values()
    )
    support_counts = Counter(
        effect["derived_support"] for _, effect in independent_effects.values()
    )
    if len(confirmed_exposure_tasks) + len(unresolved_exposure_tasks) != len(clear_tasks):
        raise AuditError("Task exposure counts do not conserve clear Tasks.")
    if sum(task_type_effect.values()) != len(independent_effects):
        raise AuditError("Task type × effect counts do not conserve independent effects.")
    if len(effect_tasks) > len(clear_tasks):
        raise AuditError("Effect Task count cannot exceed clear Task count.")

    mapped_audits = sum(1 for row in candidates if row["mapped_trace_files"])
    chat_message_counts: dict[str, int] = {}
    mapped_chat_ids: set[str] = set()
    for row in candidates:
        chat_id = row["chat"]["chat_id"]
        chat_message_counts[chat_id] = max(
            chat_message_counts.get(chat_id, 0),
            int(row["chat"]["message_count"]),
        )
        if row["mapped_trace_files"]:
            mapped_chat_ids.add(chat_id)
    message_count = sum(chat_message_counts.values())
    gap_counts = Counter(gap for row in candidates for gap in row["coverage_gaps"])
    bounded_starts = {
        row["window"]["start"]
        for row in candidates
        if isinstance(row["window"].get("start"), str)
    }
    window_start = min(bounded_starts) if bounded_starts else "unbounded"
    window_end = max(row["window"]["end"] for row in candidates)
    sampling = sampling_summary(tasks)

    lines = [
        "# Context Tree Insights: Task-First Value Audit",
        "",
        f"Generated: {isoformat(generated_at)}",
        f"Acquisition bound: {window_start} – {window_end}",
        "",
        "## Outcome",
        "",
        table_row(["Measure", "Count"]),
        table_row(["---", "---:"]),
        table_row(["Clear Tasks", len(clear_tasks)]),
        table_row(["Excluded Tasks", len(excluded_tasks)]),
        table_row(["Confirmed exposure Tasks", len(confirmed_exposure_tasks)]),
        table_row(["Unresolved exposure Tasks", len(unresolved_exposure_tasks)]),
        table_row(["Effect Tasks", len(effect_tasks)]),
        table_row(["Independent effects", len(independent_effects)]),
        "",
        "Unresolved exposure is unknown coverage, not an unused/no-value denominator. Receipt absence is also unknown.",
        "",
        "These counts are auditable lower bounds, not a global effectiveness rate. A read, selector call, or decision receipt is evidence, not causal proof by itself.",
        "",
        "## Sampling",
        "",
        f"Status: `{sampling['status']}`; clear Tasks: **{sampling['clear_tasks']}**"
        + (
            f"; saturation reached at **{sampling['saturated_at']}**."
            if sampling["saturated_at"] is not None
            else "."
        ),
        "",
        "The default judgment quota is 100 clear Tasks, followed by 20-Task expansions until two consecutive complete batches add no new effect type, key counterexample, or conclusion change.",
        "",
    ]
    if sampling["missing_task_types"]:
        lines.extend(
            [
                "Task-type coverage still missing from the initial cohort: "
                + ", ".join(f"`{item}`" for item in sampling["missing_task_types"])
                + ".",
                "",
            ]
        )
    if sampling["expansions"]:
        lines.extend(
            [
                table_row(["Expansion", "Saturation signals"]),
                table_row(["---", "---"]),
            ]
        )
        for batch in sampling["expansions"]:
            lines.append(
                table_row(
                    [
                        f"{batch['start']}–{batch['end']}",
                        ", ".join(batch["signals"]) if batch["signals"] else "none",
                    ]
                )
            )
        lines.append("")

    lines.extend(
        [
        "## Effect Distribution",
        "",
        table_row(["Effect", "Independent effects"]),
        table_row(["---", "---:"]),
        ]
    )
    for effect in ("confirmed", "constrained", "redirected", "conflicted"):
        lines.append(table_row([effect, effect_counts[effect]]))
    lines.extend(
        [
            "",
            f"Derived support: definite **{support_counts['definite']}**, limited **{support_counts['limited']}**. Support is derived during reporting and is never accepted from task-judgments input.",
            "",
            "## Task Type × Effect",
            "",
            table_row(["Task type", "confirmed", "constrained", "redirected", "conflicted", "Total"]),
            table_row(["---", "---:", "---:", "---:", "---:", "---:"]),
        ]
    )
    for task_type in sorted(TASK_TYPE_VALUES):
        counts = [task_type_effect[(task_type, effect)] for effect in (
            "confirmed", "constrained", "redirected", "conflicted"
        )]
        lines.append(table_row([task_type, *counts, sum(counts)]))

    lines.extend(
        [
            "",
            "## Representative Cases",
            "",
        ]
    )
    representatives = effect_tasks[:5]
    if not representatives:
        lines.append("No representative effect Task was selected.")
        lines.append("")
    for task in representatives:
        effects = task["effects"]
        effect_labels = ", ".join(f"`{effect['effect']}`" for effect in effects)
        lines.extend(
            [
                f"### {task['objective']} (`{task['task_id']}`)",
                "",
                f"- Task type: `{task['task_type']}`",
                f"- Exposure: `{task['exposure']['status']}`",
                f"- Effects: {effect_labels}",
                f"- Outcome: {task['outcome']}",
                f"- Influence: {'; '.join(effect['summary'] for effect in effects)}",
                "",
            ]
        )

    lines.extend(
        [
            "## Coverage",
            "",
            table_row(["Measure", "Count"]),
            table_row(["---", "---:"]),
            table_row(["Authorized Chats acquired", len(chat_message_counts)]),
            table_row(["Authorized Chat-Agent audit units", len(candidates)]),
            table_row(["Visible messages", message_count]),
            table_row(["Chats mapped to local Codex traces", len(mapped_chat_ids)]),
            table_row(["Audit units mapped to local Codex traces", mapped_audits]),
            table_row(["Chat-Agent evidence rows", len(candidates)]),
            table_row(["Task judgments", len(tasks)]),
            "",
            "Historical collection is best-effort. Missing reads, absent receipts, and unresolved exposure do not establish that a Task did not use Context Tree.",
            "",
            "### Coverage gaps",
            "",
        ]
    )
    if not gap_counts:
        lines.append("- None recorded.")
    else:
        for gap, count in sorted(gap_counts.items()):
            lines.append(f"- `{gap}`: {count} audit unit(s)")

    lines.extend(
        [
            "",
            "## Rubric and Boundaries",
            "",
            "A clear Task requires a concrete objective, object scope, outcome, bounded source fragments, and one of the five task types. Excluded Tasks do not carry exposure or effects.",
            "",
            "Effects retain the four strict values `confirmed`, `constrained`, `redirected`, and `conflicted`. `verified` and `probable` preserve the original passage-level confidence; neither a receipt nor aligned output is server-verified causality.",
            "",
            "This audit uses local Codex traces mapped by runtime-injected `chatId`. It remains read-only and limited to one explicitly authorized Agent, one workspace, and one bound Tree.",
            "",
        ]
    )
    return "\n".join(lines)


def validate_report_candidate(
    value: Mapping[str, Any],
    workspace_identity: WorkspaceIdentity,
) -> dict[str, Any]:
    if value.get("schema_version") != SCHEMA_VERSION:
        raise AuditError(
            f"Every candidate must use schema_version {SCHEMA_VERSION}."
        )
    chat = value.get("chat")
    if not isinstance(chat, dict):
        raise AuditError("Every candidate must contain a chat object.")
    chat_id = require_uuid(chat.get("chat_id"), "candidate.chat.chat_id")
    source_agent_id = require_uuid(
        chat.get("source_agent_id"),
        f"candidate[{chat_id}].chat.source_agent_id",
    )
    source_agent = require_string(
        chat.get("source_agent"),
        f"candidate[{chat_id}].chat.source_agent",
    )
    if (
        source_agent_id != workspace_identity.agent_id
        or source_agent != workspace_identity.agent_name
    ):
        raise AuditError(
            f"Candidate {chat_id} does not match the authorized Agent workspace identity."
        )
    expected_audit_id = audit_id(chat_id, source_agent_id)
    if value.get("audit_id") != expected_audit_id:
        raise AuditError(
            f"Candidate {chat_id} audit_id does not match its Chat and Agent UUIDs."
        )
    validate_authorization(
        chat.get("authorization"),
        f"candidate[{expected_audit_id}].chat.authorization",
    )
    if not isinstance(chat.get("title"), str) or not isinstance(
        chat.get("message_count"), int
    ):
        raise AuditError(
            f"Candidate {expected_audit_id} must contain a title and integer message_count."
        )
    candidate_status = value.get("candidate_status")
    if candidate_status not in {"candidate", "outside_candidate_set"}:
        raise AuditError(
            f"Candidate {expected_audit_id} has an invalid candidate_status."
        )
    expected_tree_id = tree_identity(workspace_identity)
    if value.get("tree_identity") != expected_tree_id:
        raise AuditError(
            f"Candidate {expected_audit_id} does not match the workspace-bound Tree."
        )
    window = value.get("window")
    if not isinstance(window, dict):
        raise AuditError(f"Candidate {expected_audit_id} must contain a window.")
    parsed_window_start = None
    if window.get("start") is not None:
        parsed_window_start = parse_datetime(
            require_string(window.get("start"), f"candidate[{expected_audit_id}].window.start"),
            field=f"candidate {expected_audit_id} window start",
        )
    parsed_window_end = parse_datetime(
        require_string(window.get("end"), f"candidate[{expected_audit_id}].window.end"),
        field=f"candidate {expected_audit_id} window end",
    )
    if parsed_window_start is not None and parsed_window_start > parsed_window_end:
        raise AuditError(f"Candidate {expected_audit_id} window starts after it ends.")
    mapped_traces = value.get("mapped_trace_files")
    reads = value.get("reads")
    visible_messages = value.get("visible_messages")
    choices = value.get("visible_choice_candidates")
    mentions = value.get("visible_tree_mentions")
    coverage_gaps = value.get("coverage_gaps")
    if not all(
        isinstance(item, list)
        for item in (
            mapped_traces,
            reads,
            visible_messages,
            choices,
            mentions,
            coverage_gaps,
        )
    ):
        raise AuditError(
            f"Candidate {expected_audit_id} evidence and coverage fields must be arrays."
        )
    if chat["message_count"] != len(visible_messages):
        raise AuditError(
            f"Candidate {expected_audit_id} message_count does not match visible_messages."
        )
    if not all(
        isinstance(item, str) and item.startswith("trace-")
        for item in mapped_traces
    ):
        raise AuditError(
            f"Candidate {expected_audit_id} has an invalid mapped trace identity."
        )
    for read in reads:
        if not isinstance(read, dict):
            raise AuditError(
                f"Candidate {expected_audit_id} contains a malformed read."
            )
        if (
            read.get("reader_agent_id") != workspace_identity.agent_id
            or read.get("tree_identity") != expected_tree_id
            or not isinstance(read.get("read_id"), str)
            or not isinstance(read.get("node_paths"), list)
            or not isinstance(read.get("passage"), str)
            or read.get("success") is not True
        ):
            raise AuditError(
                f"Candidate {expected_audit_id} contains a read outside its Agent/Tree scope."
            )
    visible_messages_by_id: dict[str, Mapping[str, Any]] = {}
    for message in visible_messages:
        if (
            not isinstance(message, dict)
            or not isinstance(message.get("message_id"), str)
            or not isinstance(message.get("created_at"), str)
        ):
            raise AuditError(
                f"Candidate {expected_audit_id} contains an invalid visible message."
            )
        message_id = message["message_id"]
        if message_id in visible_messages_by_id:
            raise AuditError(
                f"Candidate {expected_audit_id} contains duplicate visible message {message_id}."
            )
        visible_messages_by_id[message_id] = message
        receipt = message.get("decision_receipt")
        if receipt is not None and normalize_context_decision(receipt) != receipt:
            raise AuditError(
                f"Candidate {expected_audit_id} contains an invalid decision receipt."
            )
    choice_ids: set[str] = set()
    for message in choices:
        if (
            not isinstance(message, dict)
            or message.get("sender_id") != workspace_identity.agent_id
            or not isinstance(message.get("message_id"), str)
            or not isinstance(message.get("created_at"), str)
        ):
            raise AuditError(
                f"Candidate {expected_audit_id} contains an invalid visible choice."
            )
        if message["message_id"] in choice_ids:
            raise AuditError(
                f"Candidate {expected_audit_id} contains duplicate visible choices."
            )
        choice_ids.add(message["message_id"])
        source_message = visible_messages_by_id.get(message["message_id"])
        if source_message is None or any(
            source_message.get(field) != message.get(field)
            for field in ("created_at", "sender_id", "content")
        ):
            raise AuditError(
                f"Candidate {expected_audit_id} choice is not an exact authorized visible message."
            )
    return dict(value)


def finalize_report(args: argparse.Namespace) -> None:
    workspace_identity = parse_agent_workspace(args.agent_workspace)
    artifact_root = resolve_artifact_root(args.artifact_root, workspace_identity)
    candidates_path = artifact_path(
        artifact_root, args.candidates, field="--candidates", must_exist=True
    )
    task_judgments_path = artifact_path(
        artifact_root,
        args.task_judgments,
        field="--task-judgments",
        must_exist=True,
    )
    evidence_path = artifact_path(
        artifact_root, args.evidence_output, field="--evidence-output", must_exist=False
    )
    report_path = artifact_path(
        artifact_root, args.report_output, field="--report-output", must_exist=False
    )
    require_distinct_paths(
        {
            "--candidates": candidates_path,
            "--task-judgments": task_judgments_path,
            "--evidence-output": evidence_path,
            "--report-output": report_path,
        }
    )
    candidates = [
        validate_report_candidate(candidate, workspace_identity)
        for candidate in iter_jsonl(candidates_path)
    ]
    if not candidates:
        raise AuditError("No candidate records were provided.")
    if len({candidate["audit_id"] for candidate in candidates}) != len(candidates):
        raise AuditError("Candidate evidence contains duplicate Chat-Agent audit rows.")
    tasks = load_task_judgments(task_judgments_path)
    if not tasks:
        raise AuditError("No Task judgments were provided.")
    validate_task_refs(candidates, tasks)
    evidence = build_task_evidence(tasks)

    generated_at = parse_datetime(args.generated_at, field="--generated-at") if args.generated_at else datetime.now(timezone.utc)
    write_jsonl(evidence_path, evidence)
    write_text(report_path, f"{render_report(candidates, evidence, generated_at)}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Context Tree Insights collector with deterministic "
            "Task-first judgment validation and reporting."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export-chats", help="Export only the Chats named by an authorization scope.")
    export_parser.add_argument(
        "--artifact-root",
        required=True,
        help="Exact triggering-agent artifact directory; every input and output must stay inside it.",
    )
    export_parser.add_argument(
        "--scope",
        required=True,
        help="Scope JSON for one explicitly authorized Agent or its exact authorized Chats.",
    )
    export_parser.add_argument("--output", required=True, help="Destination Chat JSONL.")
    export_parser.add_argument(
        "--days",
        type=int,
        help="Optional acquisition lookback bound in days; Task quota controls sample size.",
    )
    export_parser.add_argument("--now", help="Fixed RFC 3339 window end for reproducible runs.")
    export_parser.add_argument(
        "--agent-workspace",
        required=True,
        help="Exact AGENT_UUID=/absolute/workspace identity for the one scoped Agent.",
    )
    export_parser.add_argument(
        "--first-tree-bin",
        help=(
            "First Tree CLI executable (default: FIRST_TREE_BIN, then safe "
            "discovery of first-tree or first-tree-staging)."
        ),
    )
    export_parser.set_defaults(handler=export_chats)

    collect_parser = subparsers.add_parser("collect", help="Pair authorized Chat records with local Codex trace evidence.")
    collect_parser.add_argument(
        "--artifact-root",
        required=True,
        help="Exact triggering-agent artifact directory; every input and output must stay inside it.",
    )
    collect_parser.add_argument("--chats", required=True, help="Authorized Chat JSONL from export-chats.")
    collect_parser.add_argument("--output", required=True, help="Destination candidate evidence JSONL.")
    collect_parser.add_argument(
        "--days",
        type=int,
        help="Optional acquisition lookback bound in days; Task quota controls sample size.",
    )
    collect_parser.add_argument("--now", help="Fixed RFC 3339 window end for reproducible runs.")
    collect_parser.add_argument(
        "--trace-root",
        help="Codex sessions root (default: CODEX_HOME/sessions or ~/.codex/sessions).",
    )
    collect_parser.add_argument(
        "--agent-workspace",
        required=True,
        help="Exact AGENT_UUID=/absolute/workspace identity for the one scoped Agent.",
    )
    collect_parser.add_argument(
        "--tree-root",
        required=True,
        help="Exact Context Tree root bound in the scoped workspace identity.",
    )
    collect_parser.add_argument(
        "--max-passage-chars",
        type=int,
        default=24000,
        help="Maximum stored tool-output characters per read (default: 24000).",
    )
    collect_parser.set_defaults(handler=collect_evidence)

    report_parser = subparsers.add_parser(
        "report",
        help="Validate Task judgments and render final evidence/report artifacts.",
    )
    report_parser.add_argument(
        "--artifact-root",
        required=True,
        help="Exact triggering-agent artifact directory; every input and output must stay inside it.",
    )
    report_parser.add_argument(
        "--agent-workspace",
        required=True,
        help="Exact AGENT_UUID=/absolute/workspace identity for the one scoped Agent.",
    )
    report_parser.add_argument("--candidates", required=True, help="Candidate JSONL from collect.")
    report_parser.add_argument(
        "--task-judgments",
        required=True,
        help="Task-level Agent judgment JSONL.",
    )
    report_parser.add_argument("--evidence-output", required=True, help="Destination final evidence JSONL.")
    report_parser.add_argument("--report-output", required=True, help="Destination Markdown report.")
    report_parser.add_argument("--generated-at", help="Fixed RFC 3339 report timestamp for reproducible runs.")
    report_parser.set_defaults(handler=finalize_report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    os.umask(0o077)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if getattr(args, "max_passage_chars", 1) <= 0:
            raise AuditError("--max-passage-chars must be greater than zero.")
        args.handler(args)
    except AuditError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
