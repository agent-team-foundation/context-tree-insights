#!/usr/bin/env python3
"""Build task-first Context Tree insights from First Tree Chats and Codex traces.

Collection remains deliberately conservative and read-only.  Semantic value is
judged at Task level after authorized Chat evidence has been collected.
"""

from __future__ import annotations

import argparse
import ast
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
EXEC_ORCHESTRATION_TOOLS = {"exec", "functions.exec"}
DIRECT_READ_TOOLS = {
    "read_file",
    "view_file",
    "functions.read_file",
    "functions.view_file",
}
SHELL_CONTINUATION_TOOLS = {"write_stdin", "functions.write_stdin"}
CELL_CONTINUATION_TOOLS = {"wait", "functions.wait"}
MUTATING_TOOLS = {
    "apply_patch",
    "functions.apply_patch",
}
READ_ATTEMPT_STATUSES = (
    "accepted_exact",
    "accepted_read_only_composite",
    "unresolved_opaque",
    "rejected_unsafe",
)
KNOWN_UNSAFE_PROGRAMS = {
    "bash",
    "chmod",
    "chown",
    "cp",
    "curl",
    "dd",
    "eval",
    "install",
    "ln",
    "mv",
    "nc",
    "perl",
    "python",
    "python3",
    "rm",
    "rsync",
    "scp",
    "sh",
    "source",
    "ssh",
    "tee",
    "truncate",
    "wget",
    "xargs",
    "zsh",
}
SAFE_GIT_DIAGNOSTICS = {
    "diff",
    "log",
    "merge-base",
    "remote",
    "rev-parse",
    "show",
    "status",
}
MUTATING_GIT_COMMANDS = {
    "add",
    "am",
    "apply",
    "bisect",
    "branch",
    "checkout",
    "cherry-pick",
    "clean",
    "clone",
    "commit",
    "fetch",
    "gc",
    "init",
    "merge",
    "mv",
    "pull",
    "push",
    "rebase",
    "reset",
    "restore",
    "revert",
    "rm",
    "stash",
    "submodule",
    "switch",
    "tag",
    "worktree",
}
UNSAFE_GIT_OPTIONS = {
    "--exec-path",
    "--ext-diff",
    "--no-index",
    "--output",
    "--textconv",
}
UNSAFE_FIND_ACTIONS = {
    "-delete",
    "-exec",
    "-execdir",
    "-fls",
    "-fprint",
    "-fprint0",
    "-fprintf",
    "-ok",
    "-okdir",
}
UNSAFE_RG_OPTIONS = {
    "--generate",
    "--pre",
    "--pre-glob",
    "--replace",
    "-r",
}
_ARTIFACT_LEXICAL_ROOTS: dict[Path, Path] = {}
UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
# Current Agent names use the tighter 1-64 grammar with an alphanumeric first
# character. First Tree still runs older names created under
# `[a-z0-9_-]{1,100}`, including leading separators, so an audit must accept
# that complete path-safe grandfathered grammar and let the producer-owned
# local binding UUID check establish the exact identity.
AGENT_SLUG_PATTERN = re.compile(r"[a-z0-9_-]{1,100}")
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
SHELL_SESSION_PATTERN = re.compile(
    r"\A\s*Script running with session ID\s+([0-9]+)\s*\Z",
    re.IGNORECASE,
)
CELL_SESSION_PATTERN = re.compile(
    r"\A\s*Script running with cell ID\s+([A-Za-z0-9_.:-]+)\s*\Z",
    re.IGNORECASE,
)


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


@dataclass(frozen=True)
class ReadComponent:
    reader: str
    node_paths: tuple[str, ...]


@dataclass(frozen=True)
class ReadPlan:
    node_paths: tuple[str, ...]
    components: tuple[ReadComponent, ...]
    command: str
    mode: str
    auxiliary_output_possible: bool = False
    auxiliary_literals: tuple[str, ...] = ()
    output_requires_separation: bool = False


@dataclass(frozen=True)
class ReadAssessment:
    plan: ReadPlan | None
    status: str | None
    reason: str | None
    subplans: tuple[ReadPlan, ...] = ()


@dataclass(frozen=True)
class ShellSegment:
    tokens: tuple[str, ...]
    input_mode: str
    output_discarded: bool = False


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
            # The historical Agent-name grammar permits leading `-`, including
            # option-looking names such as `--json`. The `--option=value`
            # form keeps the selector bound to this argument instead of
            # allowing the CLI parser to reinterpret it as another option.
            page_args.append(f"--agent={agent}")
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

    def string_values(value: Any) -> Iterator[str]:
        if isinstance(value, str):
            yield value
        elif isinstance(value, Mapping):
            for child in value.values():
                yield from string_values(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from string_values(child)

    for value in string_values(arguments):
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


def has_literal_non_tree_markdown(
    payload: Mapping[str, Any],
    tree_root: Path,
) -> bool:
    raw = tool_raw(payload).replace("\\/", "/")
    for match in re.finditer(
        r"(?<![A-Za-z0-9_.@-])(/[^\s\"'`,;|&<>]+\.md)"
        r"(?=$|[\s\"'`,;:)|&<>])",
        raw,
        re.UNICODE,
    ):
        candidate = Path(match.group(1)).expanduser().resolve(strict=False)
        if not path_is_within(candidate, tree_root):
            return True
    return False


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def normalize_shell_newlines(command: str) -> str | None:
    """Turn unquoted newlines into shell separators without changing quotes."""
    output: list[str] = []
    quote: str | None = None
    escaped = False
    for character in command:
        if escaped:
            output.append(character)
            escaped = False
            continue
        if character == "\\" and quote != "'":
            output.append(character)
            escaped = True
            continue
        if quote is None and character in {"'", '"'}:
            quote = character
            output.append(character)
            continue
        if quote == character:
            quote = None
            output.append(character)
            continue
        if quote is None and character in {"\n", "\r"}:
            output.append(";")
            continue
        output.append(character)
    if quote is not None or escaped:
        return None
    return "".join(output)


def shell_segments(
    command: str,
) -> tuple[list[ShellSegment] | None, str | None]:
    normalized = normalize_shell_newlines(command)
    if normalized is None:
        return None, "unresolved_shell_syntax"
    try:
        lexer = shlex.shlex(
            normalized,
            posix=True,
            punctuation_chars=";&|<>()`",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return None, "unresolved_shell_syntax"
    if not tokens:
        return None, "unresolved_empty_command"

    segments: list[ShellSegment] = []
    current: list[str] = []
    input_mode = "none"
    output_discarded = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {";", "&&", "||", "|"}:
            if not current:
                return None, "unresolved_shell_syntax"
            segments.append(
                ShellSegment(
                    tokens=tuple(current),
                    input_mode=input_mode,
                    output_discarded=output_discarded,
                )
            )
            current = []
            input_mode = "pipe" if token == "|" else "none"
            output_discarded = False
            index += 1
            continue
        if (
            token in {">", ">>", "&>"}
            and index + 1 < len(tokens)
            and tokens[index + 1] == "/dev/null"
        ):
            descriptor = "1"
            if current and current[-1] in {"0", "1", "2"}:
                descriptor = current.pop()
            if descriptor in {"1", "&"}:
                output_discarded = True
            index += 2
            continue
        if (
            token in {"0", "1", "2"}
            and index + 2 < len(tokens)
            and tokens[index + 1] == ">&"
            and tokens[index + 2] in {"0", "1", "2"}
        ):
            index += 3
            continue
        if token and any(character in token for character in "<>"):
            return None, "unsafe_shell_redirection"
        if token == "&":
            return None, "unsafe_background_shell"
        if token in {"(", ")"}:
            return None, "unresolved_shell_grouping"
        if token == "`" or "$(" in token:
            return None, "unresolved_command_substitution"
        current.append(token)
        index += 1
    if not current:
        return None, "unresolved_shell_syntax"
    segments.append(
        ShellSegment(
            tokens=tuple(current),
            input_mode=input_mode,
            output_discarded=output_discarded,
        )
    )
    return segments, None


def expand_static_for_loop(
    segments: Sequence[ShellSegment],
) -> tuple[list[ShellSegment] | None, str | None]:
    control_indexes = [
        index
        for index, segment in enumerate(segments)
        if segment.tokens
        and segment.tokens[0] in {"for", "do", "done"}
    ]
    if not control_indexes:
        return list(segments), None
    for_indexes = [
        index
        for index in control_indexes
        if segments[index].tokens[0] == "for"
    ]
    done_indexes = [
        index
        for index in control_indexes
        if segments[index].tokens[0] == "done"
    ]
    if len(for_indexes) != 1 or len(done_indexes) != 1:
        return None, "unresolved_shell_loop"
    for_index = for_indexes[0]
    done_index = done_indexes[0]
    if done_index <= for_index:
        return None, "unresolved_shell_loop"
    header = segments[for_index]
    if (
        header.input_mode != "none"
        or len(header.tokens) < 4
        or header.tokens[2] != "in"
    ):
        return None, "unresolved_shell_loop"
    variable = header.tokens[1]
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable) is None:
        return None, "unresolved_shell_loop"
    values = list(header.tokens[3:])
    if (
        not values
        or tokens_have_dynamic_expansion(values)
        or any(not value.lower().endswith(".md") for value in values)
    ):
        return None, "unresolved_shell_loop"

    body = list(segments[for_index + 1 : done_index])
    if body and body[0].tokens and body[0].tokens[0] == "do":
        first = body.pop(0)
        if len(first.tokens) > 1:
            body.insert(
                0,
                ShellSegment(
                    tokens=first.tokens[1:],
                    input_mode=first.input_mode,
                    output_discarded=first.output_discarded,
                ),
            )
    if not body or any(
        segment.tokens
        and segment.tokens[0] in {"for", "do", "done"}
        for segment in body
    ):
        return None, "unresolved_shell_loop"

    expanded: list[ShellSegment] = list(segments[:for_index])
    variable_forms = {f"${variable}", f"${{{variable}}}"}
    for value in values:
        for segment in body:
            if any(token in variable_forms for token in segment.tokens):
                expanded.append(
                    ShellSegment(
                        tokens=tuple(
                            value if token in variable_forms else token
                            for token in segment.tokens
                        ),
                        input_mode=segment.input_mode,
                        output_discarded=segment.output_discarded,
                    )
                )
            else:
                expanded.append(segment)
    suffix = list(segments[done_index + 1 :])
    if any(
        segment.tokens
        and segment.tokens[0] in {"for", "do", "done"}
        for segment in suffix
    ):
        return None, "unresolved_shell_loop"
    expanded.extend(suffix)
    return expanded, None


def expand_literal_if_guard(
    segments: Sequence[ShellSegment],
) -> tuple[list[ShellSegment] | None, str | None]:
    """Flatten one literal if/test guard while preserving its guarded body."""
    control_indexes = [
        index
        for index, segment in enumerate(segments)
        if segment.tokens
        and segment.tokens[0] in {"if", "then", "elif", "else", "fi"}
    ]
    if not control_indexes:
        return list(segments), None
    if any(
        segments[index].tokens[0] in {"elif", "else"}
        for index in control_indexes
    ):
        return None, "unresolved_shell_conditional"
    if_indexes = [
        index
        for index in control_indexes
        if segments[index].tokens[0] == "if"
    ]
    fi_indexes = [
        index
        for index in control_indexes
        if segments[index].tokens[0] == "fi"
    ]
    then_indexes = [
        index
        for index in control_indexes
        if segments[index].tokens[0] == "then"
    ]
    if (
        len(if_indexes) != 1
        or len(fi_indexes) != 1
        or len(then_indexes) != 1
    ):
        return None, "unresolved_shell_conditional"
    if_index = if_indexes[0]
    then_index = then_indexes[0]
    fi_index = fi_indexes[0]
    if not if_index < then_index < fi_index:
        return None, "unresolved_shell_conditional"

    header = segments[if_index]
    terminator = segments[fi_index]
    if (
        header.input_mode != "none"
        or header.output_discarded
        or len(header.tokens) < 2
        or terminator.tokens != ("fi",)
        or terminator.input_mode != "none"
        or terminator.output_discarded
    ):
        return None, "unresolved_shell_conditional"
    guard_tokens = header.tokens[1:]
    if Path(guard_tokens[0]).name not in {"test", "["}:
        return None, "unresolved_shell_conditional"

    body = list(segments[then_index:fi_index])
    first = body.pop(0)
    if len(first.tokens) > 1:
        body.insert(
            0,
            ShellSegment(
                tokens=first.tokens[1:],
                input_mode=first.input_mode,
                output_discarded=first.output_discarded,
            ),
        )
    if not body or any(
        segment.tokens
        and segment.tokens[0] in {"if", "then", "elif", "else", "fi"}
        for segment in body
    ):
        return None, "unresolved_shell_conditional"

    prefix = list(segments[:if_index])
    suffix = list(segments[fi_index + 1 :])
    if any(
        segment.tokens
        and segment.tokens[0] in {"if", "then", "elif", "else", "fi"}
        for segment in (*prefix, *suffix)
    ):
        return None, "unresolved_shell_conditional"
    return [
        *prefix,
        ShellSegment(
            tokens=guard_tokens,
            input_mode="none",
            output_discarded=False,
        ),
        *body,
        *suffix,
    ], None


def markdown_token_path(
    token: str,
    workdir: Path,
    tree_roots: Sequence[Path],
) -> str | None:
    cleaned = token.strip(" \t\r\n\"'`,;:()[]{}")
    if (
        not cleaned.lower().endswith(".md")
        or any(character.isspace() for character in cleaned)
        or any(character in cleaned for character in "*?[]{}")
    ):
        return None
    candidate = Path(cleaned).expanduser()
    return relative_tree_path(
        candidate if candidate.is_absolute() else workdir / candidate,
        tree_roots,
    )


def markdown_read_component(
    tokens: Sequence[str],
    workdir: Path,
    tree_roots: Sequence[Path],
) -> ReadComponent | None:
    if not tokens:
        return None
    executable = Path(tokens[0]).name
    if executable not in PURE_READ_COMMANDS:
        return None
    arguments = list(tokens[1:])
    if not arguments or "-" in arguments:
        return None

    paths: list[str] = []
    if executable == "sed":
        expressions: list[str] = []
        index = 0
        while index < len(arguments):
            token = arguments[index]
            if token in {"-n", "--quiet", "--silent"}:
                index += 1
                continue
            if token in {"-e", "--expression"}:
                if index + 1 >= len(arguments):
                    return None
                expressions.append(arguments[index + 1])
                index += 2
                continue
            if token.startswith("--expression="):
                expressions.append(token.split("=", 1)[1])
                index += 1
                continue
            if token.startswith("-"):
                return None
            node_path = markdown_token_path(token, workdir, tree_roots)
            if node_path is not None:
                paths.append(node_path)
            elif not expressions:
                expressions.append(token)
            else:
                return None
            index += 1
        if not expressions or any(
            re.fullmatch(r"(?:\d+|\$)(?:,(?:\d+|\$))?p", expression) is None
            for expression in expressions
        ):
            return None
    else:
        option_arguments = {
            "head": {"-c", "--bytes", "-n", "--lines"},
            "tail": {"-c", "--bytes", "-n", "--lines"},
            "nl": {"-b", "--body-numbering", "-d", "--section-delimiter", "-f",
                   "--footer-numbering", "-h", "--header-numbering", "-i",
                   "--line-increment", "-l", "--join-blank-lines", "-n",
                   "--number-format", "-s", "--number-separator", "-v",
                   "--starting-line-number", "-w", "--number-width"},
        }
        needs_value = option_arguments.get(executable, set())
        no_value_options = {
            "cat": {
                "-A", "--show-all", "-b", "--number-nonblank", "-e", "-E",
                "--show-ends", "-n", "--number", "-s", "--squeeze-blank",
                "-t", "-T", "--show-tabs", "-u", "-v", "--show-nonprinting",
            },
            "head": {"-q", "--quiet", "--silent", "-v", "--verbose", "-z", "--zero-terminated"},
            "tail": {"-q", "--quiet", "--silent", "-v", "--verbose", "-z", "--zero-terminated"},
            "nl": {"-p", "--no-renumber"},
            "bat": {"-p", "--plain", "-n", "--number", "--no-paging"},
        }.get(executable, set())
        index = 0
        after_options = False
        while index < len(arguments):
            token = arguments[index]
            if not after_options and token == "--":
                after_options = True
                index += 1
                continue
            if not after_options and token in needs_value:
                if index + 1 >= len(arguments):
                    return None
                index += 2
                continue
            if not after_options and any(
                token.startswith(f"{option}=")
                for option in needs_value
                if option.startswith("--")
            ):
                index += 1
                continue
            if (
                not after_options
                and executable in {"head", "tail"}
                and (
                    re.fullmatch(r"-[cn]\+?\d+", token)
                    or re.fullmatch(r"-\d+", token)
                )
            ):
                index += 1
                continue
            if not after_options and token in no_value_options:
                index += 1
                continue
            if (
                not after_options
                and executable == "nl"
                and token.startswith("-")
                and len(token) > 1
            ):
                # All `nl` switches are output-format controls. Compact forms
                # such as `-ba` are common on the left side of `nl | sed`.
                index += 1
                continue
            if (
                not after_options
                and executable == "cat"
                and re.fullmatch(r"-[AbeEnstTuv]+", token)
            ):
                index += 1
                continue
            if (
                not after_options
                and executable == "bat"
                and any(
                    token.startswith(prefix)
                    for prefix in (
                        "--color=",
                        "--decorations=",
                        "--language=",
                        "--line-range=",
                        "--paging=",
                        "--style=",
                        "--tabs=",
                        "--terminal-width=",
                        "--wrap=",
                    )
                )
            ):
                index += 1
                continue
            if not after_options and token.startswith("-"):
                return None
            if executable in {"head", "tail"} and re.fullmatch(r"\+?\d+", token):
                index += 1
                continue
            node_path = markdown_token_path(token, workdir, tree_roots)
            if node_path is None:
                return None
            paths.append(node_path)
            index += 1

    if not paths:
        return None
    return ReadComponent(reader=executable, node_paths=tuple(sorted(set(paths))))


def diagnostic_path(token: str, workdir: Path) -> Path | None:
    if token in {".", ".."} or token.startswith(("./", "../", "/")):
        candidate = Path(token).expanduser()
        return (candidate if candidate.is_absolute() else workdir / candidate).resolve(
            strict=False
        )
    return None


def tokens_have_dynamic_expansion(tokens: Sequence[str]) -> bool:
    return any("$" in token or "`" in token for token in tokens)


def safe_pipeline_filter(tokens: Sequence[str]) -> bool:
    """Accept filters that consume only a preceding, already-safe pipe."""
    if not tokens or tokens_have_dynamic_expansion(tokens):
        return False
    executable = Path(tokens[0]).name
    arguments = list(tokens[1:])
    if executable == "sed":
        expressions: list[str] = []
        index = 0
        while index < len(arguments):
            token = arguments[index]
            if token in {"-n", "--quiet", "--silent"}:
                index += 1
                continue
            if token in {"-e", "--expression"}:
                if index + 1 >= len(arguments):
                    return False
                expressions.append(arguments[index + 1])
                index += 2
                continue
            if token.startswith("--expression="):
                expressions.append(token.split("=", 1)[1])
                index += 1
                continue
            if token.startswith("-"):
                return False
            if expressions:
                return False
            expressions.append(token)
            index += 1
        return bool(expressions) and all(
            re.fullmatch(r"(?:\d+|\$)(?:,(?:\d+|\$))?p", expression)
            is not None
            for expression in expressions
        )
    if executable in {"head", "tail"}:
        return all(
            argument.startswith("-")
            or re.fullmatch(r"\+?\d+", argument) is not None
            for argument in arguments
        )
    if executable == "nl":
        return all(argument.startswith("-") for argument in arguments)
    if executable == "wc":
        return all(
            argument in {
                "-c",
                "--bytes",
                "-l",
                "--lines",
                "-m",
                "--chars",
                "-w",
                "--words",
                "-L",
                "--max-line-length",
            }
            for argument in arguments
        )
    return False


def safe_test_command(
    tokens: Sequence[str],
    workdir: Path,
    workspace: Path,
    tree_root: Path,
) -> bool:
    if not tokens:
        return False
    executable = Path(tokens[0]).name
    arguments = list(tokens[1:])
    if executable == "[":
        if not arguments or arguments[-1] != "]":
            return False
        arguments = arguments[:-1]
    elif executable != "test":
        return False
    if tokens_have_dynamic_expansion(arguments):
        return False
    allowed_operators = {
        "!",
        "-a",
        "-d",
        "-e",
        "-f",
        "-h",
        "-L",
        "-n",
        "-o",
        "-r",
        "-s",
        "-w",
        "-x",
        "-z",
    }
    saw_predicate = False
    for argument in arguments:
        if argument in allowed_operators:
            if argument.startswith("-") and argument not in {"-a", "-o"}:
                saw_predicate = True
            continue
        candidate_path = Path(argument).expanduser()
        candidate = (
            candidate_path
            if candidate_path.is_absolute()
            else workdir / candidate_path
        ).resolve(strict=False)
        if not (
            path_is_within(candidate, tree_root)
        ):
            return False
    return saw_predicate


def safe_static_output(tokens: Sequence[str]) -> bool:
    return static_output_literal(tokens) is not None


def shell_backslash_expansion(value: str) -> str | None:
    output: list[str] = []
    index = 0
    replacements = {
        "\\": "\\",
        "a": "\a",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
    }
    while index < len(value):
        if value[index] != "\\":
            output.append(value[index])
            index += 1
            continue
        if index + 1 >= len(value):
            return None
        escaped = value[index + 1]
        replacement = replacements.get(escaped)
        if replacement is None:
            return None
        output.append(replacement)
        index += 2
    return "".join(output)


def static_output_literal(tokens: Sequence[str]) -> str | None:
    """Render the small, deterministic label subset accepted in composites."""
    if not tokens or tokens_have_dynamic_expansion(tokens[1:]):
        return None
    executable = Path(tokens[0]).name
    arguments = list(tokens[1:])
    if executable == "echo":
        newline = True
        if arguments and arguments[0] == "-n":
            newline = False
            arguments.pop(0)
        if any(argument.startswith("-") for argument in arguments):
            return None
        return " ".join(arguments) + ("\n" if newline else "")
    if executable != "printf" or not arguments:
        return None

    format_value = shell_backslash_expansion(arguments.pop(0))
    if format_value is None:
        return None
    marker = "\0PERCENT\0"
    protected = format_value.replace("%%", marker)
    if re.search(r"%(?!s)", protected):
        return None
    placeholders = protected.count("%s")
    if placeholders != len(arguments):
        return None
    rendered = protected
    for argument in arguments:
        rendered = rendered.replace("%s", argument, 1)
    return rendered.replace(marker, "%")


def safe_wc_command(
    tokens: Sequence[str],
    workdir: Path,
    tree_root: Path,
    *,
    pipe_input: bool,
) -> bool:
    if not tokens or Path(tokens[0]).name != "wc":
        return False
    paths = 0
    for argument in tokens[1:]:
        if argument == "-l":
            continue
        if argument.startswith("-"):
            return False
        candidate = Path(argument).expanduser()
        resolved = (
            candidate if candidate.is_absolute() else workdir / candidate
        ).resolve(strict=False)
        if not path_is_within(resolved, tree_root):
            return False
        paths += 1
    return pipe_input or paths > 0


def safe_tree_cli(tokens: Sequence[str]) -> bool:
    if not tokens:
        return False
    executable = Path(tokens[0]).name
    if executable not in {"first-tree", "first-tree-staging"}:
        return False
    if tokens_have_dynamic_expansion(tokens[1:]):
        return False
    return any(
        tuple(tokens[index : index + 2]) == ("tree", "tree")
        for index in range(1, len(tokens) - 1)
    )


def git_command_parts(
    tokens: Sequence[str],
    workdir: Path,
) -> tuple[Path, str, list[str]] | None:
    if not tokens or Path(tokens[0]).name != "git":
        return None
    arguments = list(tokens[1:])
    git_workdir = workdir
    index = 0
    if len(arguments) >= 2 and arguments[0] == "-C":
        candidate = Path(arguments[1]).expanduser()
        git_workdir = (
            candidate if candidate.is_absolute() else workdir / candidate
        ).resolve(strict=False)
        index = 2
    if index >= len(arguments) or arguments[index].startswith("-"):
        return None
    return git_workdir, arguments[index], arguments[index + 1 :]


def git_has_unsafe_option(arguments: Sequence[str]) -> bool:
    return any(
        argument in UNSAFE_GIT_OPTIONS
        or any(
            argument.startswith(f"{option}=")
            for option in UNSAFE_GIT_OPTIONS
        )
        for argument in arguments
    )


def safe_git_diagnostic(
    tokens: Sequence[str],
    workdir: Path,
    tree_root: Path,
) -> bool:
    parts = git_command_parts(tokens, workdir)
    if parts is None:
        return False
    git_workdir, subcommand, arguments = parts
    if (
        not path_is_within(git_workdir, tree_root)
        or subcommand not in SAFE_GIT_DIAGNOSTICS
        or git_has_unsafe_option(arguments)
        or tokens_have_dynamic_expansion(arguments)
    ):
        return False
    if subcommand == "remote":
        if not arguments:
            return True
        if all(argument in {"-v", "--verbose"} for argument in arguments):
            return True
        if arguments[0] == "get-url":
            remainder = list(arguments[1:])
            while remainder and remainder[0] in {"--all", "--push"}:
                remainder.pop(0)
            return len(remainder) == 1 and not remainder[0].startswith("-")
        return False
    for argument in arguments:
        if argument.startswith(("../", "./", "/")):
            candidate = Path(argument).expanduser()
            resolved = (
                candidate
                if candidate.is_absolute()
                else git_workdir / candidate
            ).resolve(strict=False)
            if not path_is_within(resolved, tree_root):
                return False
    return True


def rg_read_component(
    tokens: Sequence[str],
    workdir: Path,
    tree_roots: Sequence[Path],
) -> ReadComponent | None:
    if not tokens or Path(tokens[0]).name != "rg":
        return None
    arguments = list(tokens[1:])
    if "--files" in arguments:
        return None

    value_options = {
        "-A",
        "--after-context",
        "-B",
        "--before-context",
        "-C",
        "--context",
        "-g",
        "--glob",
        "-m",
        "--max-count",
        "-t",
        "--type",
        "-T",
        "--type-not",
        "--sort",
        "--sortr",
    }
    pattern_options = {"-e", "--regexp"}
    explicit_pattern = False
    positionals: list[str] = []
    index = 0
    after_options = False
    while index < len(arguments):
        argument = arguments[index]
        if not after_options and argument == "--":
            after_options = True
            index += 1
            continue
        if not after_options and argument in pattern_options:
            if index + 1 >= len(arguments):
                return None
            explicit_pattern = True
            index += 2
            continue
        if not after_options and any(
            argument.startswith(f"{option}=")
            for option in pattern_options
            if option.startswith("--")
        ):
            explicit_pattern = True
            index += 1
            continue
        if not after_options and argument in value_options:
            if index + 1 >= len(arguments):
                return None
            index += 2
            continue
        if not after_options and any(
            argument.startswith(f"{option}=")
            for option in value_options
            if option.startswith("--")
        ):
            index += 1
            continue
        if not after_options and argument.startswith("-"):
            index += 1
            continue
        positionals.append(argument)
        index += 1

    path_operands = positionals if explicit_pattern else positionals[1:]
    paths = {
        path
        for argument in path_operands
        if (path := markdown_token_path(argument, workdir, tree_roots))
        is not None
    }
    if not paths:
        return None
    return ReadComponent(reader="rg", node_paths=tuple(sorted(paths)))


def diagnostic_markdown_paths(
    tokens: Sequence[str],
    workdir: Path,
    tree_root: Path,
) -> set[str]:
    if not tokens:
        return set()
    executable = Path(tokens[0]).name
    if executable not in {"[", "find", "git", "ls", "test", "wc"}:
        return set()
    return {
        path
        for argument in tokens[1:]
        if (path := markdown_token_path(argument, workdir, (tree_root,)))
        is not None
    }


def safe_read_only_diagnostic(
    tokens: Sequence[str],
    workdir: Path,
    workspace: Path,
    tree_root: Path,
) -> bool:
    if not tokens:
        return False
    executable = Path(tokens[0]).name
    arguments = list(tokens[1:])
    if executable == "pwd":
        return all(argument in {"-L", "-P"} for argument in arguments) and (
            path_is_within(workdir, workspace)
            or path_is_within(workdir, tree_root)
        )
    if executable == "true":
        return not arguments
    if executable in {"test", "["}:
        return safe_test_command(
            tokens,
            workdir,
            workspace,
            tree_root,
        )
    if executable in {"echo", "printf"}:
        return safe_static_output(tokens)
    if executable == "wc":
        return safe_wc_command(
            tokens,
            workdir,
            tree_root,
            pipe_input=False,
        )
    if executable in {"first-tree", "first-tree-staging"}:
        return safe_tree_cli(tokens)
    if executable == "git":
        return safe_git_diagnostic(tokens, workdir, tree_root)
    if executable == "rg":
        if not path_is_within(workdir, tree_root) or any(
            argument in UNSAFE_RG_OPTIONS
            or any(argument.startswith(f"{option}=") for option in UNSAFE_RG_OPTIONS)
            for argument in arguments
        ):
            return False
        for argument in arguments:
            candidate = diagnostic_path(argument, workdir)
            if candidate is not None and not path_is_within(candidate, tree_root):
                return False
        return True
    if executable == "find":
        if not path_is_within(workdir, tree_root) or any(
            argument in UNSAFE_FIND_ACTIONS for argument in arguments
        ):
            return False
        for argument in arguments:
            candidate = diagnostic_path(argument, workdir)
            if candidate is not None and not path_is_within(candidate, tree_root):
                return False
        return True
    if executable == "ls":
        if not path_is_within(workdir, tree_root):
            return False
        for argument in arguments:
            if argument.startswith("-"):
                continue
            candidate = diagnostic_path(argument, workdir)
            if candidate is None or not path_is_within(candidate, tree_root):
                return False
        return True
    return False


def command_workdir(payload: Mapping[str, Any], default_workdir: Path) -> Path:
    value = parse_tool_arguments(payload).get("workdir")
    if not isinstance(value, str) or not value.strip():
        return default_workdir
    candidate = Path(value).expanduser()
    return (candidate if candidate.is_absolute() else default_workdir / candidate).resolve(
        strict=False
    )


def rejected_assessment(reason: str) -> ReadAssessment:
    status = (
        "rejected_unsafe"
        if reason.startswith("unsafe_")
        else "unresolved_opaque"
    )
    return ReadAssessment(plan=None, status=status, reason=reason)


def accepted_assessment(
    plan: ReadPlan,
    *,
    subplans: Sequence[ReadPlan] | None = None,
) -> ReadAssessment:
    return ReadAssessment(
        plan=plan,
        status=(
            "accepted_exact"
            if plan.mode == "isolated"
            else "accepted_read_only_composite"
        ),
        reason=None,
        subplans=tuple(subplans or (plan,)),
    )


def unsafe_shell_reason(tokens: Sequence[str]) -> str | None:
    if not tokens:
        return None
    executable = Path(tokens[0]).name
    arguments = list(tokens[1:])
    if executable in KNOWN_UNSAFE_PROGRAMS:
        return f"unsafe_program_{executable}"
    if executable == "sed" and any(
        argument == "-i"
        or argument.startswith("-i")
        or argument.startswith("--in-place")
        for argument in arguments
    ):
        return "unsafe_sed_in_place"
    if executable == "find" and any(
        argument in UNSAFE_FIND_ACTIONS for argument in arguments
    ):
        return "unsafe_find_action"
    if executable == "rg" and any(
        argument in UNSAFE_RG_OPTIONS
        or any(argument.startswith(f"{option}=") for option in UNSAFE_RG_OPTIONS)
        for argument in arguments
    ):
        return "unsafe_rg_option"
    if executable == "git":
        index = 2 if len(arguments) >= 2 and arguments[0] == "-C" else 0
        if git_has_unsafe_option(arguments[index + 1 :]):
            return "unsafe_git_option"
        if index < len(arguments) and arguments[index] in MUTATING_GIT_COMMANDS:
            return "unsafe_git_mutation"
    return None


def shell_command_assessment(
    tool_name: str,
    payload: Mapping[str, Any],
    tree_root: Path,
    default_workdir: Path,
    *,
    allow_diagnostic_plan: bool = False,
) -> ReadAssessment:
    node_paths = extract_node_paths(payload, (tree_root,), default_workdir)
    arguments = parse_tool_arguments(payload)
    command = arguments.get("cmd")
    if not isinstance(command, str) or not command.strip():
        return (
            rejected_assessment("unresolved_missing_literal_command")
            if node_paths or allow_diagnostic_plan
            else ReadAssessment(None, None, "not_a_tree_markdown_read")
        )
    segments, reason = shell_segments(command)
    if segments is None:
        return (
            rejected_assessment(reason or "unresolved_shell_syntax")
            if node_paths or allow_diagnostic_plan
            else ReadAssessment(None, None, "not_a_tree_markdown_read")
        )
    segments, reason = expand_static_for_loop(segments)
    if segments is None:
        return (
            rejected_assessment(reason or "unresolved_shell_loop")
            if node_paths or allow_diagnostic_plan
            else ReadAssessment(None, None, "not_a_tree_markdown_read")
        )
    segments, reason = expand_literal_if_guard(segments)
    if segments is None:
        return (
            rejected_assessment(reason or "unresolved_shell_conditional")
            if node_paths or allow_diagnostic_plan
            else ReadAssessment(None, None, "not_a_tree_markdown_read")
        )

    workdir = command_workdir(payload, default_workdir)
    current_workdir = workdir
    components: list[ReadComponent] = []
    diagnostic_paths: set[str] = set()
    diagnostic_count = 0
    auxiliary_literals: list[str] = []
    output_requires_separation = False
    deferred_unsafe_reason: str | None = None
    for shell_segment in segments:
        segment = list(shell_segment.tokens)
        if not segment:
            return rejected_assessment("unresolved_shell_syntax")
        executable = Path(segment[0]).name
        unsafe_reason = unsafe_shell_reason(segment)
        if unsafe_reason is not None:
            if node_paths or components or allow_diagnostic_plan:
                return rejected_assessment(unsafe_reason)
            deferred_unsafe_reason = unsafe_reason
            continue
        literal_non_tree_path = False
        for argument in segment[1:]:
            if not argument.startswith(("/", "./", "../")):
                continue
            candidate_path = Path(argument).expanduser()
            candidate = (
                candidate_path
                if candidate_path.is_absolute()
                else current_workdir / candidate_path
            ).resolve(strict=False)
            if not (
                argument.lower().endswith(".md")
                or candidate.exists()
            ):
                # A leading slash can be a search/sed expression. If it is not
                # a Markdown operand or an existing path, later program-specific
                # validation decides whether the shape is merely opaque.
                continue
            if not path_is_within(candidate, tree_root):
                literal_non_tree_path = True
                break
        if literal_non_tree_path:
            if node_paths or components or allow_diagnostic_plan:
                return rejected_assessment("unsafe_literal_non_tree_path")
            deferred_unsafe_reason = "unsafe_literal_non_tree_path"
            continue
        if executable in PURE_READ_COMMANDS and "-" in segment[1:]:
            if shell_segment.input_mode == "pipe" and safe_pipeline_filter(segment):
                diagnostic_count += 1
                continue
            return rejected_assessment("unresolved_stdin_tree_read")
        if executable == "cd":
            if shell_segment.input_mode == "pipe" or len(segment) != 2:
                return rejected_assessment("unresolved_shell_cd")
            candidate = Path(segment[1]).expanduser()
            current_workdir = (
                candidate if candidate.is_absolute() else current_workdir / candidate
            ).resolve(strict=False)
            if not path_is_within(current_workdir, tree_root):
                return rejected_assessment("unsafe_cross_tree_workdir")
            diagnostic_count += 1
            continue

        component = markdown_read_component(
            segment,
            current_workdir,
            (tree_root,),
        )
        if component is not None:
            if deferred_unsafe_reason is not None:
                return rejected_assessment(deferred_unsafe_reason)
            if shell_segment.output_discarded:
                diagnostic_count += 1
                diagnostic_paths.update(component.node_paths)
            else:
                components.append(component)
            continue

        if executable == "rg":
            if not safe_read_only_diagnostic(
                segment,
                current_workdir,
                default_workdir,
                tree_root,
            ):
                return rejected_assessment("unsafe_or_unresolved_rg")
            component = rg_read_component(
                segment,
                current_workdir,
                (tree_root,),
            )
            if component is not None:
                if shell_segment.output_discarded:
                    diagnostic_count += 1
                    diagnostic_paths.update(component.node_paths)
                else:
                    components.append(component)
            else:
                diagnostic_count += 1
                if not shell_segment.output_discarded:
                    output_requires_separation = True
            continue

        if shell_segment.input_mode == "pipe" and (
            safe_pipeline_filter(segment)
            or safe_wc_command(
                segment,
                current_workdir,
                tree_root,
                pipe_input=True,
            )
        ):
            diagnostic_count += 1
            diagnostic_paths.update(
                diagnostic_markdown_paths(
                    segment,
                    current_workdir,
                    tree_root,
                )
            )
            if executable == "wc" and not shell_segment.output_discarded:
                output_requires_separation = True
            continue

        if safe_read_only_diagnostic(
            segment,
            current_workdir,
            default_workdir,
            tree_root,
        ):
            diagnostic_count += 1
            diagnostic_paths.update(
                diagnostic_markdown_paths(
                    segment,
                    current_workdir,
                    tree_root,
                )
            )
            if not shell_segment.output_discarded:
                if executable in {"echo", "printf"}:
                    literal = static_output_literal(segment)
                    if literal is None:
                        return rejected_assessment("unresolved_static_output")
                    auxiliary_literals.append(literal)
                elif executable not in {"test", "[", "true"}:
                    output_requires_separation = True
            continue
        if executable in {"for", "do", "done"}:
            return rejected_assessment("unresolved_shell_loop")
        if not node_paths and not components and not allow_diagnostic_plan:
            return ReadAssessment(None, None, "not_a_tree_markdown_read")
        return rejected_assessment("unresolved_unknown_program")

    if not components:
        if deferred_unsafe_reason is not None and allow_diagnostic_plan:
            return rejected_assessment(deferred_unsafe_reason)
        if allow_diagnostic_plan and diagnostic_count > 0:
            return accepted_assessment(
                ReadPlan(
                    node_paths=(),
                    components=(),
                    command=(
                        f"{tool_name.rsplit('.', 1)[-1]} "
                        "read_only_diagnostic"
                    ),
                    mode="read_only_composite",
                    auxiliary_output_possible=True,
                    auxiliary_literals=tuple(auxiliary_literals),
                    output_requires_separation=output_requires_separation,
                )
            )
        return (
            rejected_assessment("unresolved_tree_path_without_content_reader")
            if node_paths
            else ReadAssessment(None, None, "not_a_tree_markdown_read")
        )
    recovered_paths = tuple(
        sorted({path for component in components for path in component.node_paths})
    )
    if (
        node_paths
        and set(recovered_paths) | diagnostic_paths != set(node_paths)
    ):
        return rejected_assessment("unresolved_node_path_attribution")
    mode = (
        "isolated"
        if len(segments) == 1
        and len(components) == 1
        and len(recovered_paths) == 1
        and diagnostic_count == 0
        else "read_only_composite"
    )
    descriptor = (
        f"{tool_name.rsplit('.', 1)[-1]} {mode} "
        + " ".join(recovered_paths)
    )
    return accepted_assessment(
        ReadPlan(
            node_paths=recovered_paths,
            components=tuple(components),
            command=descriptor,
            mode=mode,
            auxiliary_output_possible=diagnostic_count > 0,
            auxiliary_literals=tuple(auxiliary_literals),
            output_requires_separation=output_requires_separation,
        )
    )


def raw_orchestration_source(payload: Mapping[str, Any]) -> str | None:
    for key in ("input", "arguments"):
        value = payload.get(key)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return value
            if isinstance(parsed, str):
                return parsed
            if isinstance(parsed, Mapping):
                for field in ("code", "js", "source"):
                    candidate = parsed.get(field)
                    if isinstance(candidate, str):
                        return candidate
    return None


def matching_js_delimiter(
    source: str,
    start: int,
    opening: str,
    closing: str,
) -> tuple[str, int] | None:
    if start >= len(source) or source[start] != opening:
        return None
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(start, len(source)):
        character = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"', "`"}:
            quote = character
            continue
        if character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return source[start + 1 : index], index + 1
    return None


def parse_js_string_literal(source: str, start: int) -> tuple[str, int] | None:
    if start >= len(source) or source[start] not in {"'", '"', "`"}:
        return None
    quote = source[start]
    escaped = False
    for index in range(start + 1, len(source)):
        character = source[index]
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character != quote:
            continue
        literal = source[start : index + 1]
        if quote == "`":
            body = literal[1:-1]
            if "${" in body:
                return None
            return body, index + 1
        try:
            value = ast.literal_eval(literal)
        except (SyntaxError, ValueError):
            return None
        return (value, index + 1) if isinstance(value, str) else None
    return None


def split_js_top_level(source: str, delimiter: str) -> list[str] | None:
    parts: list[str] = []
    start = 0
    depths = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    quote: str | None = None
    escaped = False
    for index, character in enumerate(source):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"', "`"}:
            quote = character
            continue
        if character in depths:
            depths[character] += 1
            continue
        if character in closing:
            opening = closing[character]
            if depths[opening] == 0:
                return None
            depths[opening] -= 1
            continue
        if character == delimiter and all(depth == 0 for depth in depths.values()):
            parts.append(source[start:index])
            start = index + 1
    if quote is not None or any(depth != 0 for depth in depths.values()):
        return None
    parts.append(source[start:])
    return parts


def js_top_level_colon(source: str) -> int | None:
    parts = split_js_top_level(source, ":")
    if parts is None or len(parts) != 2:
        return None
    return len(parts[0])


def parse_js_object_properties(
    source: str,
) -> tuple[dict[str, str] | None, str | None]:
    entries = split_js_top_level(source, ",")
    if entries is None:
        return None, "unresolved_exec_dynamic_arguments"
    properties: dict[str, str] = {}
    for index, raw_entry in enumerate(entries):
        entry = raw_entry.strip()
        if not entry:
            if index == len(entries) - 1:
                continue
            return None, "unresolved_exec_dynamic_arguments"
        if entry.startswith("..."):
            return None, "unresolved_exec_dynamic_arguments"
        colon = js_top_level_colon(entry)
        if colon is None:
            return None, "unresolved_exec_dynamic_arguments"
        raw_key = entry[:colon].strip()
        raw_value = entry[colon + 1 :].strip()
        if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", raw_key):
            key = raw_key
        else:
            parsed_key = parse_js_string_literal(raw_key, 0)
            if parsed_key is None or parsed_key[1] != len(raw_key):
                return None, "unresolved_exec_dynamic_arguments"
            key = parsed_key[0]
        if key in properties or key in {"__proto__", "constructor", "prototype"}:
            return None, "unresolved_exec_dynamic_arguments"
        properties[key] = raw_value
    return properties, None


def exact_js_string(source: str) -> str | None:
    parsed = parse_js_string_literal(source, 0)
    if parsed is None or source[parsed[1] :].strip():
        return None
    return parsed[0]


def exact_safe_js_value(source: str) -> bool:
    value = source.strip()
    if exact_js_string(value) is not None:
        return True
    if value in {"true", "false", "null"}:
        return True
    if re.fullmatch(r"(?:0|[1-9][0-9]*)", value):
        return True
    if value.startswith("[") and value.endswith("]"):
        entries = split_js_top_level(value[1:-1], ",")
        if entries is None:
            return False
        return all(
            not entry.strip() or exact_js_string(entry.strip()) is not None
            for entry in entries
        )
    return False


def orchestration_source_skeleton(
    source: str,
) -> tuple[str | None, list[str] | None]:
    """Replace literal exec calls while retaining every surrounding JS byte."""
    call_bodies: list[str] = []
    output: list[str] = []
    cursor = 0
    pattern = re.compile(r"\btools\.exec_command\s*\(")
    while (match := pattern.search(source, cursor)) is not None:
        opening_index = match.end() - 1
        balanced = matching_js_delimiter(source, opening_index, "(", ")")
        if balanced is None:
            return None, None
        call_body, end = balanced
        output.append(source[cursor : match.start()])
        output.append("__EXEC_CALL__")
        call_bodies.append(call_body)
        cursor = end
    output.append(source[cursor:])
    if not call_bodies:
        return None, None
    return "".join(output), call_bodies


def orchestration_wrapper_shape(
    skeleton: str,
    nested_count: int,
) -> str | None:
    identifier = r"[A-Za-z_][A-Za-z0-9_]*"
    call = r"__EXEC_CALL__"

    single_forward = re.fullmatch(
        rf"\s*(?:const|let|var)\s+(?P<result>{identifier})\s*=\s*"
        rf"await\s+{call}\s*;\s*"
        rf"text\s*\(\s*(?P=result)\.output\s*\)\s*;?\s*",
        skeleton,
    )
    if single_forward is not None and nested_count == 1:
        return "sequential"

    sequential = re.fullmatch(
        rf"\s*(?P<decls>(?:(?:const|let|var)\s+{identifier}\s*=\s*"
        rf"await\s+{call}\s*;\s*)+)"
        rf"(?P<forwards>(?:text\s*\(\s*{identifier}\.output\s*\)\s*;\s*)+)",
        skeleton,
    )
    if sequential is not None:
        assignments = re.findall(
            rf"(?:const|let|var)\s+({identifier})\s*=\s*"
            rf"await\s+{call}",
            sequential.group("decls"),
        )
        forwarded = re.findall(
            rf"text\s*\(\s*({identifier})\.output\s*\)",
            sequential.group("forwards"),
        )
        if (
            len(assignments) == nested_count
            and len(set(assignments)) == len(assignments)
            and assignments == forwarded
        ):
            return "sequential"

    promise_prefix = (
        rf"\s*(?:const|let|var)\s+(?P<results>{identifier})\s*=\s*"
        rf"await\s+Promise\.all\s*\(\s*\[\s*"
        rf"(?P<calls>{call}(?:\s*,\s*{call})*\s*,?)"
        rf"\s*\]\s*\)\s*;\s*"
    )
    callback = re.fullmatch(
        promise_prefix
        + rf"(?P=results)\.(?:forEach|map)\s*\(\s*"
        rf"(?:\(\s*)?(?P<item>{identifier})(?:\s*\))?\s*=>\s*"
        rf"text\s*\(\s*(?P=item)\.output\s*\)\s*\)\s*;?\s*",
        skeleton,
    )
    if callback is not None and callback.group("calls").count(call) == nested_count:
        return "promise"

    for_of = re.fullmatch(
        promise_prefix
        + rf"for\s*\(\s*(?:const|let|var)\s+(?P<item>{identifier})\s+"
        rf"of\s+(?P=results)\s*\)\s*\{{\s*"
        rf"text\s*\(\s*(?P=item)\.output\s*\)\s*;\s*\}}\s*",
        skeleton,
    )
    if for_of is not None and for_of.group("calls").count(call) == nested_count:
        return "promise"
    return None


def orchestration_command_payloads(
    payload: Mapping[str, Any],
    default_workdir: Path,
) -> tuple[list[dict[str, Any]] | None, str | None, str | None]:
    source = raw_orchestration_source(payload)
    if source is None:
        return None, "unresolved_exec_payload", None
    skeleton, call_bodies = orchestration_source_skeleton(source)
    if skeleton is None or call_bodies is None:
        return None, "unresolved_exec_without_nested_tool", None
    shape = orchestration_wrapper_shape(skeleton, len(call_bodies))
    if shape is None:
        return None, "unresolved_exec_wrapper_shape", None

    payloads: list[dict[str, Any]] = []
    allowed_properties = {
        "cmd",
        "justification",
        "login",
        "max_output_tokens",
        "prefix_rule",
        "sandbox_permissions",
        "shell",
        "tty",
        "workdir",
        "yield_time_ms",
    }
    for call_body in call_bodies:
        object_start = call_body.find("{")
        if object_start < 0:
            return None, "unresolved_exec_dynamic_arguments", None
        object_value = matching_js_delimiter(call_body, object_start, "{", "}")
        if object_value is None:
            return None, "unresolved_exec_dynamic_arguments", None
        object_body, object_end = object_value
        if call_body[object_end:].strip().rstrip(","):
            return None, "unresolved_exec_dynamic_arguments", None
        properties, property_reason = parse_js_object_properties(object_body)
        if properties is None:
            return None, property_reason, None
        if (
            not set(properties).issubset(allowed_properties)
            or any(
                not exact_safe_js_value(value)
                for value in properties.values()
            )
        ):
            return None, "unresolved_exec_dynamic_arguments", None
        command = exact_js_string(properties.get("cmd", ""))
        if command is None:
            return None, "unresolved_exec_dynamic_command", None
        raw_workdir = properties.get("workdir")
        workdir = (
            exact_js_string(raw_workdir)
            if raw_workdir is not None
            else None
        )
        if raw_workdir is not None and workdir is None:
            return None, "unresolved_exec_dynamic_workdir", None
        payloads.append(
            {
                "arguments": {
                    "cmd": command,
                    "workdir": workdir or str(default_workdir),
                }
            }
        )
    return payloads, None, shape


def orchestration_read_assessment(
    tool_name: str,
    payload: Mapping[str, Any],
    tree_root: Path,
    default_workdir: Path,
) -> ReadAssessment:
    node_paths = extract_node_paths(payload, (tree_root,), default_workdir)
    nested_payloads, reason, wrapper_shape = orchestration_command_payloads(
        payload,
        default_workdir,
    )
    if nested_payloads is None:
        return (
            rejected_assessment(reason or "unresolved_exec_payload")
            if node_paths
            else ReadAssessment(None, None, "not_a_tree_markdown_read")
        )
    components: list[ReadComponent] = []
    recovered_paths: set[str] = set()
    nested_plans: list[ReadPlan] = []
    for nested_payload in nested_payloads:
        assessment = shell_command_assessment(
            "exec_command",
            nested_payload,
            tree_root,
            default_workdir,
            allow_diagnostic_plan=True,
        )
        if assessment.status in {"rejected_unsafe", "unresolved_opaque"}:
            return assessment
        if assessment.plan is None:
            return rejected_assessment(
                "unresolved_exec_nested_output_attribution"
            )
        nested_plans.append(assessment.plan)
        components.extend(assessment.plan.components)
        recovered_paths.update(assessment.plan.node_paths)
    if not components:
        return (
            rejected_assessment("unresolved_exec_without_content_reader")
            if node_paths
            else ReadAssessment(None, None, "not_a_tree_markdown_read")
        )
    ordered_paths = tuple(sorted(recovered_paths))
    mode = (
        "isolated"
        if len(nested_plans) == 1
        and nested_plans[0].mode == "isolated"
        and wrapper_shape == "sequential"
        else "read_only_composite"
    )
    return accepted_assessment(
        ReadPlan(
            node_paths=ordered_paths,
            components=tuple(components),
            command=f"{tool_name.rsplit('.', 1)[-1]} {mode} "
            + " ".join(ordered_paths),
            mode=mode,
            auxiliary_output_possible=any(
                plan.auxiliary_output_possible for plan in nested_plans
            ),
            auxiliary_literals=tuple(
                literal
                for plan in nested_plans
                for literal in plan.auxiliary_literals
            ),
            output_requires_separation=any(
                plan.output_requires_separation for plan in nested_plans
            ),
        ),
        subplans=nested_plans,
    )


def markdown_read_plan(
    tool_name: str,
    payload: Mapping[str, Any],
    tree_root: Path,
    default_workdir: Path,
) -> ReadAssessment:
    """Recognize isolated and provably read-only composite Markdown reads."""
    node_paths = extract_node_paths(payload, (tree_root,), default_workdir)
    if node_paths and has_literal_non_tree_markdown(payload, tree_root):
        return rejected_assessment("unsafe_literal_non_tree_path")
    if tool_name in MUTATING_TOOLS:
        return (
            rejected_assessment("unsafe_mutating_tool")
            if node_paths
            else ReadAssessment(None, None, "not_a_tree_markdown_read")
        )
    if tool_name in EXEC_ORCHESTRATION_TOOLS:
        return orchestration_read_assessment(
            tool_name,
            payload,
            tree_root,
            default_workdir,
        )
    if tool_name in DIRECT_READ_TOOLS:
        if not node_paths:
            return ReadAssessment(None, None, "not_a_tree_markdown_read")
        component = ReadComponent(
            reader=tool_name.rsplit(".", 1)[-1],
            node_paths=tuple(node_paths),
        )
        return accepted_assessment(
            ReadPlan(
                node_paths=tuple(node_paths),
                components=(component,),
                command=f"{component.reader} {' '.join(node_paths)}",
                mode="isolated" if len(node_paths) == 1 else "read_only_composite",
            )
        )
    if tool_name not in EXEC_COMMAND_TOOLS:
        return (
            rejected_assessment("unresolved_tree_read_tool")
            if node_paths
            else ReadAssessment(None, None, "not_a_tree_markdown_read")
        )
    return shell_command_assessment(
        tool_name,
        payload,
        tree_root,
        default_workdir,
    )


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


def content_output(output: str, tool_name: str) -> str:
    if tool_name in EXEC_ORCHESTRATION_TOOLS:
        return re.sub(
            r"\A\s*Script completed successfully\s*(?:\r?\n)+"
            r"Output:\s*(?:\r?\n)?",
            "",
            output,
            count=1,
            flags=re.IGNORECASE,
        )
    if tool_name in EXEC_COMMAND_TOOLS:
        return re.sub(
            r"\A\s*Process exited with code 0\s*(?:\r?\n)+",
            "",
            output,
            count=1,
            flags=re.IGNORECASE,
        )
    return output


def attributable_passage(
    output: str,
    plan: ReadPlan,
) -> tuple[str | None, str | None]:
    if plan.output_requires_separation:
        return None, "tree_read_auxiliary_output_unresolved"
    passage = output
    for literal in plan.auxiliary_literals:
        if not literal:
            continue
        if passage.count(literal) != 1:
            return None, "tree_read_static_output_attribution_unresolved"
        passage = passage.replace(literal, "", 1)
    if not passage.strip():
        return None, "tree_read_output_missing"
    return passage.strip(), None


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
    replacements: list[tuple[str, str]] = []
    for path, replacement in (
        (tree_root, "<tree-root>"),
        (workspace, "<agent-workspace>"),
    ):
        raw = path.as_posix()
        variants = {raw}
        # macOS resolves `/var` and `/tmp` through `/private`, while recorded
        # shell output can preserve either lexical form.
        if raw.startswith("/private/"):
            variants.add(raw[len("/private") :])
        replacements.extend((variant, replacement) for variant in variants)
    for raw, replacement in sorted(
        replacements,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        result = result.replace(raw, replacement)
        result = result.replace(raw.replace("/", "\\/"), replacement)
    return result


def trace_reads(
    preflight: TracePreflight,
    tree_root: Path,
    tree_id: str,
    window: Window,
    max_passage_chars: int,
) -> tuple[list[dict[str, Any]], set[str], set[str], Counter[str]]:
    """Read one trace only after its exact Chat-Agent preflight was accepted."""
    reads: list[dict[str, Any]] = []
    sessions = {preflight.trace_id}
    gaps: set[str] = set()
    attempt_counts: Counter[str] = Counter()
    expected_chat_id = preflight.audit_id.split("@", 1)[0]
    default_workdir = preflight.workspace

    calls: dict[str, dict[str, Any]] = {}
    outputs: dict[
        str,
        tuple[str, str | None, bool, tuple[str, ...]],
    ] = {}
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
                    read_plan: ReadPlan | None = None
                    assessment: ReadAssessment | None = None
                    if not is_continuation:
                        assessment = markdown_read_plan(
                            tool_name,
                            payload,
                            tree_root,
                            default_workdir,
                        )
                        if assessment.status is None:
                            continue
                        read_plan = assessment.plan
                    calls[call_id] = {
                        "timestamp": row.get("timestamp"),
                        "payload": payload,
                        "arguments": parse_tool_arguments(payload),
                        "read_plan": read_plan,
                        "assessment": assessment,
                    }
                    continue
                if payload_type in {"custom_tool_call_output", "function_call_output"}:
                    call_id = payload.get("call_id")
                    if not isinstance(call_id, str) or call_id not in calls:
                        continue
                    raw_output_value = payload.get("output")
                    raw_parts = (
                        [
                            payload_text(item)
                            for item in raw_output_value
                            if payload_text(item)
                        ]
                        if isinstance(raw_output_value, list)
                        else [payload_text(raw_output_value)]
                    )
                    output_parts: list[str] = []
                    output_truncated = False
                    for raw_part in raw_parts:
                        part, part_truncated = clipped(
                            redact_local_roots(
                                raw_part,
                                preflight.workspace,
                                tree_root,
                            ),
                            max_passage_chars,
                        )
                        output_parts.append(part)
                        output_truncated = output_truncated or part_truncated
                    output, aggregate_truncated = clipped(
                        "\n".join(output_parts),
                        max_passage_chars,
                    )
                    output_truncated = output_truncated or aggregate_truncated
                    outputs[call_id] = (
                        output,
                        row.get("timestamp"),
                        output_truncated,
                        tuple(output_parts),
                    )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        gaps.add("codex_trace_malformed_or_partially_cleaned")
        return reads, sessions, gaps, attempt_counts

    shell_sessions: dict[str, str] = {}
    cell_sessions: dict[str, str] = {}
    continuation_outputs: dict[
        str,
        list[
            tuple[
                str,
                str | None,
                str | None,
                bool,
                tuple[str, ...],
            ]
        ],
    ] = {}
    for call_id, call in calls.items():
        payload = call["payload"]
        tool_name = str(payload.get("name") or "")
        output, output_completed_at, output_truncated, output_parts = outputs.get(
            call_id,
            ("", None, False, ()),
        )
        if tool_name in EXEC_COMMAND_TOOLS:
            match = SHELL_SESSION_PATTERN.search(output)
            if match:
                shell_sessions[match.group(1)] = call_id
        elif tool_name in EXEC_ORCHESTRATION_TOOLS:
            match = CELL_SESSION_PATTERN.search(output)
            if match:
                cell_sessions[match.group(1)] = call_id
        if tool_name in SHELL_CONTINUATION_TOOLS:
            session_id = call["arguments"].get("session_id")
            original_call_id = shell_sessions.get(str(session_id))
            if original_call_id is not None:
                continuation_outputs.setdefault(original_call_id, []).append(
                    (
                        output,
                        output_completed_at,
                        call.get("timestamp"),
                        output_truncated,
                        output_parts,
                    )
                )
        elif tool_name in CELL_CONTINUATION_TOOLS:
            cell_id = call["arguments"].get("cell_id")
            original_call_id = cell_sessions.get(str(cell_id))
            if original_call_id is not None:
                continuation_outputs.setdefault(original_call_id, []).append(
                    (
                        output,
                        output_completed_at,
                        call.get("timestamp"),
                        output_truncated,
                        output_parts,
                    )
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
        assessment = call.get("assessment")
        if not isinstance(assessment, ReadAssessment) or assessment.status is None:
            continue
        attempt_counts[assessment.status] += 1
        if assessment.reason is not None:
            attempt_counts[f"reason:{assessment.reason}"] += 1
        if assessment.status in {"unresolved_opaque", "rejected_unsafe"}:
            gaps.add(assessment.reason or assessment.status)
            continue
        read_plan = call.get("read_plan")
        if not isinstance(read_plan, ReadPlan):
            continue
        (
            initial_output,
            completed_at,
            initial_truncated,
            initial_parts,
        ) = outputs.get(call_id, ("", None, False, ()))
        if (
            not isinstance(completed_at, str)
            or not in_window(completed_at, window)
        ):
            initial_output, completed_at, initial_truncated, initial_parts = (
                "",
                None,
                False,
                (),
            )
        continuations = [
            item
            for item in continuation_outputs.get(call_id, [])
            if isinstance(item[1], str)
            and in_window(item[1], window)
            and isinstance(item[2], str)
            and in_window(item[2], window)
        ]
        output = initial_output
        output_parts = list(initial_parts)
        output_was_truncated = initial_truncated
        if continuations:
            output = "\n".join([output, *(item[0] for item in continuations)])
            output_parts.extend(
                part
                for item in continuations
                for part in item[4]
            )
            completed_at = continuations[-1][1]
            output_was_truncated = output_was_truncated or any(item[3] for item in continuations)
        initial_handle = (
            SHELL_SESSION_PATTERN.search(initial_output)
            if tool_name in EXEC_COMMAND_TOOLS
            else CELL_SESSION_PATTERN.search(initial_output)
            if tool_name in EXEC_ORCHESTRATION_TOOLS
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
        content_parts = [
            cleaned
            for part in output_parts or [output]
            if (cleaned := content_output(part, tool_name)).strip()
        ]
        if not content_parts:
            gaps.add("tree_read_output_missing")
            continue
        subplans = assessment.subplans or (read_plan,)
        sliced = len(subplans) > 1 and len(content_parts) == len(subplans)
        if sliced:
            plan_outputs = list(zip(subplans, content_parts, strict=True))
        else:
            if len(subplans) > 1:
                gaps.add("tree_read_output_attribution_aggregate")
            plan_outputs = [(read_plan, "\n".join(content_parts))]
        for read_index, (current_plan, passage_source) in enumerate(plan_outputs):
            node_paths = list(current_plan.node_paths)
            passage_source, attribution_gap = attributable_passage(
                passage_source,
                current_plan,
            )
            if passage_source is None:
                gaps.add(
                    attribution_gap
                    or "tree_read_output_attribution_unresolved"
                )
                continue
            passage, passage_truncated = clipped(
                passage_source,
                max_passage_chars,
            )
            passage_truncated = passage_truncated or output_was_truncated
            if passage_truncated:
                gaps.add("tree_read_passage_truncated")
            read_id = hashlib.sha256(
                f"{preflight.trace_id}:{call_id}:{read_index}".encode()
            ).hexdigest()[:20]
            reads.append(
                {
                    "read_id": read_id,
                    "timestamp": timestamp,
                    "completed_at": completed_at,
                    "session_file": preflight.trace_id,
                    "call_id": call_id,
                    "nested_call_index": (
                        read_index if sliced else None
                    ),
                    "tool_name": tool_name,
                    "reader_agent_id": preflight.agent_id,
                    "tree_identity": tree_id,
                    "node_paths": node_paths,
                    "read_components": [
                        {
                            "reader": component.reader,
                            "node_paths": list(component.node_paths),
                        }
                        for component in current_plan.components
                    ],
                    "read_mode": current_plan.mode,
                    "output_attribution": (
                        "exact"
                        if current_plan.mode == "isolated"
                        else "aggregate"
                    ),
                    "auxiliary_output_possible": (
                        current_plan.auxiliary_output_possible
                    ),
                    "content_class_hint": content_class_hint(node_paths),
                    "command": current_plan.command,
                    "command_truncated": False,
                    "passage": passage,
                    "passage_truncated": passage_truncated,
                    "success": success,
                }
            )
    return reads, sessions, gaps, attempt_counts


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
    per_audit_attempt_counts: dict[str, Counter[str]] = {
        item: Counter() for item in chats
    }

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
        reads, sessions, gaps, attempt_counts = trace_reads(
            preflight,
            tree_root,
            current_tree_id,
            window,
            args.max_passage_chars,
        )
        per_audit_reads[preflight.audit_id].extend(reads)
        per_audit_sessions[preflight.audit_id].update(sessions)
        per_audit_gaps[preflight.audit_id].update(gaps)
        per_audit_attempt_counts[preflight.audit_id].update(attempt_counts)

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
        attempt_counts = per_audit_attempt_counts[current_audit_id]
        status_counts = {
            status: attempt_counts[status] for status in READ_ATTEMPT_STATUSES
        }
        reason_counts = {
            key.removeprefix("reason:"): count
            for key, count in sorted(attempt_counts.items())
            if key.startswith("reason:")
        }
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
                "collector_diagnostics": {
                    "in_window_tree_read_attempts": sum(status_counts.values()),
                    "attempt_status_counts": status_counts,
                    "attempt_reason_counts": reason_counts,
                },
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


def positive_int(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AuditError(f"{field} must be a positive integer.")
    return value


def load_reviewed_baseline(path: Path) -> dict[str, Any]:
    rows = list(iter_jsonl(path))
    if len(rows) != 1:
        raise AuditError("--reviewed-baseline must contain exactly one JSONL row.")
    row = rows[0]
    if row.get("schema_version") != SCHEMA_VERSION:
        raise AuditError(
            f"Reviewed baseline must use schema_version {SCHEMA_VERSION}."
        )
    if row.get("basis") != "separately_reviewed_task_cases":
        raise AuditError(
            "Reviewed baseline basis must be separately_reviewed_task_cases."
        )
    anchor = row.get("evidence_anchor")
    if not isinstance(anchor, dict):
        raise AuditError("Reviewed baseline requires evidence_anchor.")
    artifact_id = require_string(
        anchor.get("artifact_id"),
        "reviewed_baseline.evidence_anchor.artifact_id",
    )
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", artifact_id) is None:
        raise AuditError(
            "reviewed_baseline.evidence_anchor.artifact_id must be an opaque safe identifier."
        )
    artifact_sha256 = require_string(
        anchor.get("sha256"),
        "reviewed_baseline.evidence_anchor.sha256",
    ).lower()
    if re.fullmatch(r"[0-9a-f]{64}", artifact_sha256) is None:
        raise AuditError(
            "reviewed_baseline.evidence_anchor.sha256 must be 64 lowercase hex characters."
        )
    reviewed_at = isoformat(
        parse_datetime(
            require_string(row.get("reviewed_at"), "reviewed_baseline.reviewed_at"),
            field="reviewed_baseline.reviewed_at",
        )
    )
    clear_tasks = positive_int(
        row.get("clear_tasks"), field="reviewed_baseline.clear_tasks"
    )
    effect_tasks = positive_int(
        row.get("effect_tasks"), field="reviewed_baseline.effect_tasks"
    )
    independent_effects = positive_int(
        row.get("independent_effects"),
        field="reviewed_baseline.independent_effects",
    )
    if effect_tasks > clear_tasks or effect_tasks > independent_effects:
        raise AuditError(
            "Reviewed baseline effect_tasks must not exceed clear_tasks or independent_effects."
        )

    effect_counts = row.get("effect_counts")
    if not isinstance(effect_counts, dict) or set(effect_counts) != EFFECT_VALUES:
        raise AuditError(
            "Reviewed baseline effect_counts must contain exactly the four effect keys."
        )
    normalized_effect_counts: dict[str, int] = {}
    for effect in sorted(EFFECT_VALUES):
        value = effect_counts[effect]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AuditError(
                f"reviewed_baseline.effect_counts.{effect} must be a non-negative integer."
            )
        normalized_effect_counts[effect] = value
    if sum(normalized_effect_counts.values()) != independent_effects:
        raise AuditError(
            "Reviewed baseline effect_counts must conserve independent_effects."
        )

    support_counts = row.get("support_counts")
    if not isinstance(support_counts, dict) or set(support_counts) != {
        "definite",
        "limited",
    }:
        raise AuditError(
            "Reviewed baseline support_counts must contain definite and limited."
        )
    normalized_support_counts: dict[str, int] = {}
    for support in ("definite", "limited"):
        value = support_counts[support]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AuditError(
                f"reviewed_baseline.support_counts.{support} must be a non-negative integer."
            )
        normalized_support_counts[support] = value
    if sum(normalized_support_counts.values()) != independent_effects:
        raise AuditError(
            "Reviewed baseline support_counts must conserve independent_effects."
        )
    return {
        "basis": "separately_reviewed_task_cases",
        "reviewed_at": reviewed_at,
        "evidence_anchor": {
            "artifact_id": artifact_id,
            "sha256": artifact_sha256,
        },
        "clear_tasks": clear_tasks,
        "effect_tasks": effect_tasks,
        "independent_effects": independent_effects,
        "effect_counts": normalized_effect_counts,
        "support_counts": normalized_support_counts,
    }


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
    confirmed_exposure = sum(
        1 for task in clear if task["exposure"]["status"] == "confirmed"
    )
    unresolved_exposure = sum(
        1 for task in clear if task["exposure"]["status"] == "unresolved"
    )
    if not clear:
        effect_analysis_status = "not_applicable"
    elif confirmed_exposure == 0:
        effect_analysis_status = "pending"
    elif unresolved_exposure:
        effect_analysis_status = "partial"
    else:
        effect_analysis_status = "ready"
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
        if (
            consecutive_empty == 2
            and type_coverage_complete
            and effect_analysis_status == "ready"
        ):
            saturated_at = offset + 20
            break
    if effect_analysis_status == "pending":
        status = "effect_analysis_pending"
    elif effect_analysis_status == "partial":
        status = "effect_analysis_partial"
    elif len(clear) < 100:
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
        "effect_analysis_status": effect_analysis_status,
        "confirmed_exposure_tasks": confirmed_exposure,
        "unresolved_exposure_tasks": unresolved_exposure,
    }


def render_report(
    candidates: Sequence[Mapping[str, Any]],
    tasks: Sequence[Mapping[str, Any]],
    generated_at: datetime,
    reviewed_baseline: Mapping[str, Any] | None = None,
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
    attempt_status_counts = Counter(
        {
            status: sum(
                row["collector_diagnostics"]["attempt_status_counts"][status]
                for row in candidates
            )
            for status in READ_ATTEMPT_STATUSES
        }
    )
    attempt_total = sum(
        row["collector_diagnostics"]["in_window_tree_read_attempts"]
        for row in candidates
    )
    attempt_reason_counts: Counter[str] = Counter()
    for row in candidates:
        attempt_reason_counts.update(
            row["collector_diagnostics"]["attempt_reason_counts"]
        )
    if sum(attempt_status_counts.values()) != attempt_total:
        raise AuditError(
            "Collector read-attempt status counts do not conserve the in-window total."
        )
    bounded_starts = {
        row["window"]["start"]
        for row in candidates
        if isinstance(row["window"].get("start"), str)
    }
    window_start = min(bounded_starts) if bounded_starts else "unbounded"
    window_end = max(row["window"]["end"] for row in candidates)
    sampling = sampling_summary(tasks)
    effect_metrics_available = sampling["effect_analysis_status"] in {
        "partial",
        "ready",
    }

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
        table_row(["Effect Tasks", len(effect_tasks) if effect_metrics_available else "N/A"]),
        table_row(
            [
                "Independent effects",
                len(independent_effects) if effect_metrics_available else "N/A",
            ]
        ),
        "",
        "Unresolved exposure is unknown coverage, not an unused/no-value denominator. Receipt absence is also unknown.",
        "",
        (
            "Effect analysis is `pending`: no clear Task has evidence-ready exposure, "
            "so effect count, distribution, support, and saturation are N/A rather "
            "than zero."
            if sampling["effect_analysis_status"] == "pending"
            else "Observed effect counts are auditable evidence, not a global "
            "effectiveness rate. A read, selector call, or decision receipt is "
            "evidence, not causal proof by itself."
        ),
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
    if sampling["effect_analysis_status"] == "pending":
        lines.extend(
            [
                "Effect saturation: **N/A / pending** until at least one clear "
                "Task has evidence-ready exposure. Empty unresolved batches do "
                "not establish saturation.",
                "",
            ]
        )
    elif sampling["effect_analysis_status"] == "partial":
        lines.extend(
            [
                "Effect saturation: **N/A / pending** while some clear Tasks "
                "still have unresolved exposure. Observed positive effects may "
                "be reported, but empty unresolved Tasks cannot support a "
                "saturation conclusion.",
                "",
            ]
        )
    if sampling["missing_task_types"]:
        lines.extend(
            [
                "Task-type coverage still missing from the initial cohort: "
                + ", ".join(f"`{item}`" for item in sampling["missing_task_types"])
                + ".",
                "",
            ]
        )
    if (
        sampling["effect_analysis_status"] == "ready"
        and sampling["expansions"]
    ):
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

    if effect_metrics_available:
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
    else:
        lines.extend(
            [
                "## Effect Analysis",
                "",
                "Status: **N/A / pending**. The collector did not recover "
                "evidence-ready Task exposure, so this report intentionally "
                "does not render effect totals, distributions, support, "
                "representative effects, or effect saturation.",
                "",
            ]
        )

    if reviewed_baseline is not None:
        baseline_effects = reviewed_baseline["effect_counts"]
        baseline_support = reviewed_baseline["support_counts"]
        anchor = reviewed_baseline["evidence_anchor"]
        lines.extend(
            [
                "## Separately Reviewed Historical Baseline",
                "",
                "This baseline was reviewed before the current rerun and is "
                "reported separately. Current collector gaps cannot turn these "
                "positive cases into zero, and these counts are not merged into "
                "the current sample or its saturation result.",
                "",
                table_row(["Measure", "Count"]),
                table_row(["---", "---:"]),
                table_row(["Reviewed clear Tasks", reviewed_baseline["clear_tasks"]]),
                table_row(["Reviewed effect Tasks", reviewed_baseline["effect_tasks"]]),
                table_row(
                    [
                        "Reviewed independent effects",
                        reviewed_baseline["independent_effects"],
                    ]
                ),
                "",
                table_row(["Effect", "Reviewed effects"]),
                table_row(["---", "---:"]),
                *[
                    table_row([effect, baseline_effects[effect]])
                    for effect in (
                        "confirmed",
                        "constrained",
                        "redirected",
                        "conflicted",
                    )
                ],
                "",
                "Reviewed support: definite "
                f"**{baseline_support['definite']}**, limited "
                f"**{baseline_support['limited']}**.",
                "",
                f"Evidence anchor: `{anchor['artifact_id']}` / "
                f"`sha256:{anchor['sha256']}`; reviewed at "
                f"`{reviewed_baseline['reviewed_at']}`.",
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
            table_row(["In-window Tree-read attempts", attempt_total]),
            table_row(["Chat-Agent evidence rows", len(candidates)]),
            table_row(["Task judgments", len(tasks)]),
            "",
            "### Tree-read grammar conservation",
            "",
            table_row(["Attempt classification", "Count"]),
            table_row(["---", "---:"]),
            *[
                table_row([status, attempt_status_counts[status]])
                for status in READ_ATTEMPT_STATUSES
            ],
            table_row(["Total", attempt_total]),
            "",
            "The four attempt classes conserve every in-window call whose payload referenced the bound Tree. Accepted classes describe command-shape recovery; unresolved and rejected attempts remain coverage gaps and never become negative exposure.",
            "",
            "Historical collection is best-effort. Missing reads, absent receipts, and unresolved exposure do not establish that a Task did not use Context Tree.",
            "",
            "### Coverage gaps",
            "",
        ]
    )
    if attempt_reason_counts:
        lines.extend(
            [
                "### Unresolved/rejected attempt reasons",
                "",
                table_row(["Reason", "Calls"]),
                table_row(["---", "---:"]),
            ]
        )
        for reason, count in sorted(attempt_reason_counts.items()):
            lines.append(table_row([reason, count]))
        lines.append("")
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
    collector_diagnostics = value.get("collector_diagnostics")
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
    if not isinstance(collector_diagnostics, dict):
        raise AuditError(
            f"Candidate {expected_audit_id} must contain collector_diagnostics."
        )
    attempt_total = collector_diagnostics.get("in_window_tree_read_attempts")
    attempt_status_counts = collector_diagnostics.get("attempt_status_counts")
    attempt_reason_counts = collector_diagnostics.get("attempt_reason_counts")
    if (
        not isinstance(attempt_total, int)
        or attempt_total < 0
        or not isinstance(attempt_status_counts, dict)
        or set(attempt_status_counts) != set(READ_ATTEMPT_STATUSES)
        or any(
            not isinstance(attempt_status_counts[status], int)
            or attempt_status_counts[status] < 0
            for status in READ_ATTEMPT_STATUSES
        )
        or sum(attempt_status_counts.values()) != attempt_total
        or not isinstance(attempt_reason_counts, dict)
        or any(
            not isinstance(reason, str)
            or not reason
            or not isinstance(count, int)
            or count <= 0
            for reason, count in attempt_reason_counts.items()
        )
        or sum(attempt_reason_counts.values())
        != (
            attempt_status_counts["unresolved_opaque"]
            + attempt_status_counts["rejected_unsafe"]
        )
    ):
        raise AuditError(
            f"Candidate {expected_audit_id} collector diagnostics do not conserve read attempts."
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
        read_mode = read.get("read_mode")
        components = read.get("read_components")
        if read_mode is not None and read_mode not in {
            "isolated",
            "read_only_composite",
        }:
            raise AuditError(
                f"Candidate {expected_audit_id} contains an invalid read_mode."
            )
        expected_attribution = (
            "exact" if read_mode in {None, "isolated"} else "aggregate"
        )
        if read.get("output_attribution", expected_attribution) != expected_attribution:
            raise AuditError(
                f"Candidate {expected_audit_id} contains invalid output_attribution."
            )
        if not isinstance(read.get("auxiliary_output_possible", False), bool):
            raise AuditError(
                f"Candidate {expected_audit_id} contains invalid auxiliary output metadata."
            )
        nested_call_index = read.get("nested_call_index")
        if nested_call_index is not None and (
            not isinstance(nested_call_index, int)
            or nested_call_index < 0
        ):
            raise AuditError(
                f"Candidate {expected_audit_id} contains invalid nested_call_index."
            )
        if components is not None:
            if not isinstance(components, list) or not components:
                raise AuditError(
                    f"Candidate {expected_audit_id} contains invalid read_components."
                )
            component_paths: set[str] = set()
            for component in components:
                if (
                    not isinstance(component, dict)
                    or not isinstance(component.get("reader"), str)
                    or not isinstance(component.get("node_paths"), list)
                    or not component["node_paths"]
                    or any(
                        not isinstance(path, str)
                        for path in component["node_paths"]
                    )
                ):
                    raise AuditError(
                        f"Candidate {expected_audit_id} contains a malformed read component."
                    )
                component_paths.update(component["node_paths"])
            if component_paths != set(read["node_paths"]):
                raise AuditError(
                    f"Candidate {expected_audit_id} read_components do not conserve node_paths."
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
    reviewed_baseline_path = (
        artifact_path(
            artifact_root,
            args.reviewed_baseline,
            field="--reviewed-baseline",
            must_exist=True,
        )
        if args.reviewed_baseline
        else None
    )
    paths = {
        "--candidates": candidates_path,
        "--task-judgments": task_judgments_path,
        "--evidence-output": evidence_path,
        "--report-output": report_path,
    }
    if reviewed_baseline_path is not None:
        paths["--reviewed-baseline"] = reviewed_baseline_path
    require_distinct_paths(paths)
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
    reviewed_baseline = (
        load_reviewed_baseline(reviewed_baseline_path)
        if reviewed_baseline_path is not None
        else None
    )

    generated_at = parse_datetime(args.generated_at, field="--generated-at") if args.generated_at else datetime.now(timezone.utc)
    write_jsonl(evidence_path, evidence)
    write_text(
        report_path,
        f"{render_report(candidates, evidence, generated_at, reviewed_baseline)}\n",
    )


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
    report_parser.add_argument(
        "--reviewed-baseline",
        help=(
            "Optional one-row JSONL aggregate for separately reviewed historical "
            "positive Task cases; it is rendered separately from the current rerun."
        ),
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
