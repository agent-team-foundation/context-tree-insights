from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "context-tree-value-audit"
CLAUDE_SKILL_ROOT = (
    ROOT / "projections" / "claude" / "context-tree-value-audit"
)
SCRIPT = SKILL_ROOT / "scripts" / "context_tree_value_audit.py"
AGENT_ID = "55555555-5555-4555-8555-555555555555"
OTHER_AGENT_ID = "99999999-9999-4999-8999-999999999999"
CHAT_ID = "11111111-1111-4111-8111-111111111111"
SECOND_CHAT_ID = "22222222-2222-4222-8222-222222222222"
UNAUTHORIZED_CHAT_ID = "88888888-8888-4888-8888-888888888888"
MESSAGE_ID = "33333333-3333-4333-8333-333333333333"
SECOND_MESSAGE_ID = "44444444-4444-4444-8444-444444444444"
SECOND_OBJECTIVE_MESSAGE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ACCEPTANCE_MESSAGE_ID = "66666666-6666-4666-8666-666666666666"
ORG_ID = "77777777-7777-4777-8777-777777777777"
NOW = "2026-07-24T00:00:00Z"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_jsonl(path: Path, rows: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{json.dumps(row, sort_keys=True)}\n" for row in rows),
        encoding="utf-8",
    )
    path.chmod(0o600)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_cli(
    *arguments: str,
    runtime_agent_id: str | None = AGENT_ID,
    runtime_agent_slug: str | None = "fixture-agent",
    runtime_provider: str | None = "codex",
    first_tree_json: str | None = None,
    environment_overrides: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for key, value in (
        ("FIRST_TREE_AGENT_ID", runtime_agent_id),
        ("FIRST_TREE_AGENT_SLUG", runtime_agent_slug),
        ("FIRST_TREE_PROVIDER", runtime_provider),
        ("FIRST_TREE_CHAT_ID", CHAT_ID),
        ("FIRST_TREE_JSON", first_tree_json),
    ):
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    for key, value in (environment_overrides or {}).items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True,
        check=False,
        text=True,
        env=environment,
    )


def write_workspace_identity(
    workspace: Path,
    tree_root: Path,
    agent_id: str = AGENT_ID,
    display_name: str = "Fixture Agent",
) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    write_json(
        workspace / ".first-tree-workspace" / "identity.json",
        {
            "agentId": agent_id,
            "displayName": display_name,
            "type": "agent",
            "contextTreePath": str(tree_root),
        },
    )


def context_block(chat_id: str) -> str:
    return (
        '<first-tree-current-chat-context format="json">\n'
        f'{{"chatId":"{chat_id}"}}\n'
        "</first-tree-current-chat-context>"
    )


def session_meta(workspace: Path) -> dict[str, Any]:
    return {
        "timestamp": "2026-07-22T10:00:00Z",
        "type": "session_meta",
        "payload": {
            "cwd": str(workspace),
            "originator": "first-tree",
            "model_provider": "openai",
            "source": "vscode",
        },
    }


def context_row(chat_id: str) -> dict[str, Any]:
    return {
        "timestamp": "2026-07-22T10:01:00Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": context_block(chat_id)}],
        },
    }


def context_mirror_row(chat_id: str) -> dict[str, Any]:
    return {
        "timestamp": "2026-07-22T10:01:00.001Z",
        "type": "event_msg",
        "payload": {
            "type": "user_message",
            "message": context_block(chat_id),
            "images": [],
            "local_images": [],
            "text_elements": [],
        },
    }


class RepositoryContractTests(unittest.TestCase):
    def test_skill_is_an_explicit_only_umbrella(self) -> None:
        self.assertFalse((ROOT / "skills" / "context-tree-insights").exists())
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        openai = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        reference = (SKILL_ROOT / "references" / "evidence-schema.md").read_text(
            encoding="utf-8"
        )
        task_reference = (
            SKILL_ROOT / "references" / "task-analysis-schema.md"
        ).read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        version = (SKILL_ROOT / "VERSION").read_text(encoding="utf-8").strip()

        self.assertIn("name: context-tree-value-audit", skill)
        self.assertIn("$context-tree-value-audit", skill)
        self.assertIn("manual and read-only", skill)
        self.assertIn("Do not trigger from an ordinary task", skill)
        self.assertIn("all authorized Chats are not an eligible", skill)
        self.assertIn("accepted_read_only_composite", skill)
        self.assertIn("There is no\nminimum Task quota", skill)
        claude_skill = (CLAUDE_SKILL_ROOT / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("disable-model-invocation: true", claude_skill)
        self.assertNotIn("disable-model-invocation", skill)
        self.assertIn("allow_implicit_invocation: false", openai)
        self.assertIn("explicit_agent", reference)
        self.assertIn("explicit_chat", reference)
        self.assertIn("Task, Read, and Effect Schema", task_reference)
        self.assertIn('"schema_version": 4', task_reference)
        self.assertIn('"status": "observed"', task_reference)
        self.assertIn('"effects": []', task_reference)
        self.assertIn("no more direct user instruction", task_reference)
        self.assertIn("in_window_tree_read_attempts", reference)
        self.assertIn("unresolved_opaque", reference)
        self.assertIn("explicit_agent", skill)
        self.assertNotIn("original_judgment", task_reference)
        self.assertNotIn("sampling_order", task_reference)
        self.assertIn("sampled evidence report", skill)
        self.assertEqual("0.5.0", version)
        self.assertIn(".skill-quarantine/", readme)
        self.assertIn("diff -qr", readme)
        self.assertIn("rollback", readme)
        self.assertNotIn(
            "/Users/", "\n".join((skill, openai, reference, task_reference))
        )

    def test_private_schema_v4_artifacts_are_ignored_and_rejected(self) -> None:
        private_names = {
            "task-source.jsonl",
            "task-inventory-draft.jsonl",
            "task-inventory.jsonl",
            "read-attributions.jsonl",
            "effect-judgments.jsonl",
        }
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        validator = (ROOT / "scripts" / "validate_skill.py").read_text(
            encoding="utf-8"
        )
        for name in private_names:
            self.assertIn(f"/{name}", gitignore)
            self.assertIn(f'"{name}"', validator)

    def test_install_layout_supports_codex_and_claude_upgrade_and_rollback(
        self,
    ) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            'projections/claude/context-tree-value-audit',
            readme,
        )
        self.assertIn(
            '../../.agents/skills/context-tree-insights',
            readme,
        )
        with tempfile.TemporaryDirectory(prefix="context-tree-value-audit-install-") as raw:
            root = Path(raw)

            fresh = root / "fresh"
            fresh_agents = fresh / ".agents" / "skills"
            fresh_claude = fresh / ".claude" / "skills"
            fresh_agents.mkdir(parents=True)
            fresh_claude.mkdir(parents=True)
            fresh_payload = fresh_agents / "context-tree-value-audit"
            fresh_projection = fresh_claude / "context-tree-value-audit"
            shutil.copytree(SKILL_ROOT, fresh_payload)
            shutil.copytree(CLAUDE_SKILL_ROOT, fresh_projection)
            self.assertTrue((fresh_payload / "SKILL.md").is_file())
            self.assertTrue((fresh_projection / "SKILL.md").is_file())
            self.assertEqual(
                (fresh_payload / "SKILL.md").resolve(),
                (
                    fresh_projection
                    / "../../../.agents/skills/context-tree-value-audit/SKILL.md"
                ).resolve(),
            )

            upgrade = root / "upgrade"
            upgrade_agents = upgrade / ".agents" / "skills"
            upgrade_claude = upgrade / ".claude" / "skills"
            quarantine = upgrade / ".skill-quarantine"
            upgrade_agents.mkdir(parents=True)
            upgrade_claude.mkdir(parents=True)
            quarantine.mkdir(parents=True)
            old_payload = upgrade_agents / "context-tree-insights"
            old_payload.mkdir()
            (old_payload / "SKILL.md").write_text(
                "---\nname: context-tree-insights\n---\n",
                encoding="utf-8",
            )
            old_link = upgrade_claude / "context-tree-insights"
            old_link.symlink_to("../../.agents/skills/context-tree-insights")
            retired_payload = quarantine / "context-tree-insights"
            retired_link = quarantine / "context-tree-insights.claude-link"
            old_link.rename(retired_link)
            old_payload.rename(retired_payload)
            new_payload = upgrade_agents / "context-tree-value-audit"
            new_projection = upgrade_claude / "context-tree-value-audit"
            shutil.copytree(SKILL_ROOT, new_payload)
            shutil.copytree(CLAUDE_SKILL_ROOT, new_projection)

            self.assertFalse(old_payload.exists())
            self.assertFalse(old_link.exists())
            self.assertTrue((new_payload / "SKILL.md").is_file())
            self.assertTrue((new_projection / "SKILL.md").is_file())
            self.assertEqual(
                (new_payload / "SKILL.md").resolve(),
                (
                    new_projection
                    / "../../../.agents/skills/context-tree-value-audit/SKILL.md"
                ).resolve(),
            )

            new_projection.rename(
                quarantine / "context-tree-value-audit.failed-claude"
            )
            new_payload.rename(quarantine / "context-tree-value-audit.failed")
            retired_payload.rename(old_payload)
            retired_link.rename(old_link)
            self.assertFalse(new_payload.exists())
            self.assertFalse(new_projection.exists())
            self.assertTrue((old_payload / "SKILL.md").is_file())
            self.assertTrue((old_link / "SKILL.md").is_file())


class DeterministicPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="context-tree-value-audit-")
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.artifacts = self.workspace / "artifacts"
        self.artifacts.mkdir(parents=True)
        self.tree_root = self.root / "tree"
        self.tree_file = self.tree_root / "system" / "architecture.md"
        self.tree_file.parent.mkdir(parents=True)
        self.tree_file.write_text(
            "# Architecture\n\n## Decision\n\nChat history is the authoritative state.\n",
            encoding="utf-8",
        )
        self.second_tree_file = self.tree_root / "team-practice" / "dogfooding.md"
        self.second_tree_file.parent.mkdir(parents=True)
        self.second_tree_file.write_text(
            "# Dogfooding\n\n## Decision\n\nUse First Tree in daily work.\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "init", "-b", "main", str(self.tree_root)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(self.tree_root), "config", "user.email", "tests@example.com"],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(self.tree_root), "config", "user.name", "Tests"],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(self.tree_root), "add", "."],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(self.tree_root), "commit", "-m", "seed"],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.tree_root),
                "remote",
                "add",
                "origin",
                "https://github.com/acme/tree.git",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.tree_commit = subprocess.run(
            ["git", "-C", str(self.tree_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            [
                "git",
                "-C",
                str(self.tree_root),
                "update-ref",
                "refs/remotes/origin/main",
                self.tree_commit,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.tree_root),
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/main",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        write_workspace_identity(self.workspace, self.tree_root)
        self.trace_root = self.root / "sessions"
        self.trace_root.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_fake_first_tree(
        self,
        message_metadata: dict[str, Any] | None = None,
        chat_last_message_at: Any = "2026-07-22T10:05:00Z",
        resolved_agent_id: str = AGENT_ID,
        resolved_agent_name: str = "fixture-agent",
    ) -> tuple[Path, Path]:
        binary = self.root / "fake-first-tree"
        log = self.root / "first-tree-commands.log"
        source = f"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
with Path({str(log)!r}).open("a", encoding="utf-8") as handle:
    handle.write(" ".join(args) + "\\n")

if "agent" in args and "list" in args and "--remote" in args:
    print("  NAME           TYPE    RUNTIME  ORG                                   CLIENT")
    print("  fixture-human  human   codex    {ORG_ID}  —")
    print(
        "  {resolved_agent_name}  agent   codex    {ORG_ID}  fixture-client"
    )
    raise SystemExit(0)
if "agent" in args and "list" in args:
    if os.environ.get("FIRST_TREE_JSON") == "1":
        raise SystemExit(0)
    print(
        "  {resolved_agent_name} runtime: codex uuid: {resolved_agent_id}",
        file=sys.stderr,
    )
    raise SystemExit(0)
if "agent" in args:
    print(json.dumps({{"ok": False, "error": "unexpected agent command"}}))
    raise SystemExit(9)
if "chat" in args and "list" in args:
    data = {{
        "items": [{{
            "id": {CHAT_ID!r},
            "topic": "Fixture Chat",
            "organizationId": {ORG_ID!r},
            "lastMessageAt": {chat_last_message_at!r}
        }}],
        "nextCursor": None
    }}
elif "chat" in args and "history" in args:
    data = {{
        "items": [{{
            "id": {MESSAGE_ID!r},
        "createdAt": "2026-07-22T10:05:00Z",
        "senderId": {AGENT_ID!r},
        "content": "The Context Tree constraint keeps one authoritative state source.",
        "metadata": {message_metadata!r}
        }}],
        "nextCursor": None
    }}
else:
    print(json.dumps({{"ok": False, "error": "unexpected command"}}))
    raise SystemExit(8)
print(json.dumps({{"ok": True, "data": data}}))
"""
        binary.write_text(source, encoding="utf-8")
        binary.chmod(0o755)
        return binary, log

    def export_scope(
        self,
        scope: dict[str, Any],
        output_name: str = "chats.jsonl",
        message_metadata: dict[str, Any] | None = None,
        *,
        days: int | None = 7,
        runtime_agent_id: str | None = AGENT_ID,
        runtime_agent_slug: str | None = "fixture-agent",
        resolved_agent_id: str = AGENT_ID,
        first_tree_json: str | None = None,
        chat_last_message_at: Any = "2026-07-22T10:05:00Z",
    ) -> subprocess.CompletedProcess[str]:
        scope_path = self.artifacts / "scope.json"
        output_path = self.artifacts / output_name
        write_json(scope_path, scope)
        binary, _ = self.make_fake_first_tree(
            message_metadata,
            chat_last_message_at,
            resolved_agent_id,
            runtime_agent_slug
            if isinstance(runtime_agent_slug, str)
            else "fixture-agent",
        )
        arguments = [
            "export-chats",
            "--artifact-root",
            str(self.artifacts),
            "--scope",
            str(scope_path),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--first-tree-bin",
            str(binary),
            "--now",
            NOW,
            "--output",
            str(output_path),
        ]
        if days is not None:
            arguments.extend(["--days", str(days)])
        return run_cli(
            *arguments,
            runtime_agent_id=runtime_agent_id,
            runtime_agent_slug=runtime_agent_slug,
            first_tree_json=first_tree_json,
        )

    def export_scope_with_runtime(
        self,
        scope: dict[str, Any],
        *,
        runtime_agent_id: str | None = AGENT_ID,
        runtime_agent_slug: str | None = "fixture-agent",
        resolved_agent_id: str = AGENT_ID,
        first_tree_json: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self.export_scope(
            scope,
            "runtime-identity.jsonl",
            runtime_agent_id=runtime_agent_id,
            runtime_agent_slug=runtime_agent_slug,
            resolved_agent_id=resolved_agent_id,
            first_tree_json=first_tree_json,
        )

    def test_scope_is_single_agent_and_uses_one_explicit_mode(self) -> None:
        mixed = {
            "schema_version": 1,
            "agents": [
                {
                    "name": "fixture-agent",
                    "agent_id": AGENT_ID,
                    "authorization": "explicit_agent",
                }
            ],
            "chats": [
                {
                    "chat_id": CHAT_ID,
                    "agent": "fixture-agent",
                    "agent_id": AGENT_ID,
                    "authorization": "explicit_chat",
                }
            ],
        }
        result = self.export_scope(mixed)
        self.assertEqual(2, result.returncode)
        self.assertIn("exactly one mode", result.stderr)

        multiple_agents = {
            "schema_version": 1,
            "agents": [],
            "chats": [
                {
                    "chat_id": CHAT_ID,
                    "agent": "fixture-agent",
                    "agent_id": AGENT_ID,
                    "authorization": "explicit_chat",
                },
                {
                    "chat_id": UNAUTHORIZED_CHAT_ID,
                    "agent": "other-agent",
                    "agent_id": OTHER_AGENT_ID,
                    "authorization": "explicit_chat",
                },
            ],
        }
        result = self.export_scope(multiple_agents)
        self.assertEqual(2, result.returncode)
        self.assertIn("one exact Agent", result.stderr)

    def test_exact_chat_export_only_uses_local_agent_list_for_identity(self) -> None:
        scope = {
            "schema_version": 1,
            "agents": [],
            "chats": [
                {
                    "chat_id": CHAT_ID,
                    "agent": "fixture-agent",
                    "agent_id": AGENT_ID,
                    "authorization": "explicit_chat",
                }
            ],
        }
        result = self.export_scope(scope)
        self.assertEqual(0, result.returncode, result.stderr)
        rows = read_jsonl(self.artifacts / "chats.jsonl")
        self.assertEqual(1, len(rows))
        self.assertEqual("explicit_chat", rows[0]["authorization"])
        self.assertEqual(CHAT_ID, rows[0]["chat_id"])

        commands = (self.root / "first-tree-commands.log").read_text(encoding="utf-8")
        self.assertIn("agent list", commands)
        self.assertIn(f"chat history {CHAT_ID}", commands)
        self.assertNotIn("chat list", commands)
        self.assertEqual(0o700, stat.S_IMODE(self.artifacts.stat().st_mode))
        self.assertEqual(
            0o600,
            stat.S_IMODE((self.artifacts / "chats.jsonl").stat().st_mode),
        )

    def test_explicit_agent_export_uses_the_simple_explicit_scope(self) -> None:
        scope = {
            "schema_version": 1,
            "agents": [
                {
                    "name": "fixture-agent",
                    "agent_id": AGENT_ID,
                    "authorization": "explicit_agent",
                }
            ],
            "chats": [],
        }
        result = self.export_scope(scope)
        self.assertEqual(0, result.returncode, result.stderr)
        rows = read_jsonl(self.artifacts / "chats.jsonl")
        self.assertEqual("explicit_agent", rows[0]["authorization"])
        self.assertNotIn("authorization_context", rows[0])
        commands = (self.root / "first-tree-commands.log").read_text(encoding="utf-8")
        self.assertIn("agent list", commands)
        self.assertIn("chat list", commands)
        self.assertIn("--agent=fixture-agent", commands)
        self.assertNotIn("Fixture Agent", commands)

    def test_scope_rejects_extra_authorization_context(self) -> None:
        scope = {
            "schema_version": 1,
            "agents": [
                {
                    "name": "fixture-agent",
                    "agent_id": AGENT_ID,
                    "authorization": "explicit_agent",
                }
            ],
            "chats": [],
            "authorization_context": {
                "chat_id": CHAT_ID,
            },
        }
        rejected = self.export_scope(scope)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("complete authorization model", rejected.stderr)

    def test_runtime_slug_and_uuid_bind_the_cli_selector(self) -> None:
        scope = {
            "schema_version": 1,
            "agents": [
                {
                    "name": "fixture-agent",
                    "agent_id": AGENT_ID,
                    "authorization": "explicit_agent",
                }
            ],
            "chats": [],
        }

        missing_slug = self.export_scope_with_runtime(
            scope,
            runtime_agent_slug=None,
        )
        self.assertEqual(2, missing_slug.returncode)
        self.assertIn("FIRST_TREE_AGENT_SLUG", missing_slug.stderr)

        inherited_json_mode = self.export_scope_with_runtime(
            scope,
            first_tree_json="1",
        )
        self.assertEqual(
            0,
            inherited_json_mode.returncode,
            inherited_json_mode.stderr,
        )

        for valid_slug in (
            "fixture_agent",
            "fixture-agent-",
            "fixture-agent_",
            "-fixture-agent",
            "_fixture-agent",
            "-",
            "_",
            "--json",
            "--help",
            "a" * 64,
            "a" * 100,
        ):
            accepted = self.export_scope_with_runtime(
                {
                    **scope,
                    "agents": [{**scope["agents"][0], "name": valid_slug}],
                },
                runtime_agent_slug=valid_slug,
            )
            self.assertEqual(0, accepted.returncode, accepted.stderr)

        commands = (self.root / "first-tree-commands.log").read_text(encoding="utf-8")
        self.assertIn("--agent=--json", commands)
        self.assertIn("--agent=--help", commands)
        self.assertNotIn("--agent --json", commands)
        self.assertNotIn("--agent --help", commands)

        for invalid_slug_value in (
            "Fixture Agent",
            "fixture.agent",
            "a" * 101,
        ):
            invalid_slug = self.export_scope_with_runtime(
                scope,
                runtime_agent_slug=invalid_slug_value,
            )
            self.assertEqual(2, invalid_slug.returncode)
            self.assertIn("lowercase CLI selector", invalid_slug.stderr)

        wrong_uuid = self.export_scope_with_runtime(
            scope,
            runtime_agent_id=OTHER_AGENT_ID,
        )
        self.assertEqual(2, wrong_uuid.returncode)
        self.assertIn("does not match", wrong_uuid.stderr)

        mismatched_selector = self.export_scope_with_runtime(
            scope,
            resolved_agent_id=OTHER_AGENT_ID,
        )
        self.assertEqual(2, mismatched_selector.returncode)
        self.assertIn("does not resolve", mismatched_selector.stderr)

        display_name_scope = json.loads(json.dumps(scope))
        display_name_scope["agents"][0]["name"] = "Fixture Agent"
        wrong_name = self.export_scope_with_runtime(display_name_scope)
        self.assertEqual(2, wrong_name.returncode)
        self.assertIn("identity must match", wrong_name.stderr)

    def test_chat_continuing_after_window_end_is_still_exported(self) -> None:
        scope = {
            "schema_version": 1,
            "agents": [
                {
                    "name": "fixture-agent",
                    "agent_id": AGENT_ID,
                    "authorization": "explicit_agent",
                }
            ],
            "chats": [],
        }
        result = self.export_scope(
            scope,
            "continued-chat.jsonl",
            chat_last_message_at="2026-07-25T10:05:00Z",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        rows = read_jsonl(self.artifacts / "continued-chat.jsonl")
        self.assertEqual([CHAT_ID], [row["chat_id"] for row in rows])
        commands = (self.root / "first-tree-commands.log").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"chat history {CHAT_ID}", commands)

        for malformed_summary in ({"unexpected": "object"}, 42):
            malformed = self.export_scope(
                scope,
                "continued-chat.jsonl",
                chat_last_message_at=malformed_summary,
            )
            self.assertEqual(0, malformed.returncode, malformed.stderr)
            rows = read_jsonl(self.artifacts / "continued-chat.jsonl")
            self.assertEqual([CHAT_ID], [row["chat_id"] for row in rows])

    def test_receipt_projection_is_minimal_and_absence_stays_unknown(self) -> None:
        scope = {
            "schema_version": 1,
            "agents": [],
            "chats": [
                {
                    "chat_id": CHAT_ID,
                    "agent": "fixture-agent",
                    "agent_id": AGENT_ID,
                    "authorization": "explicit_chat",
                }
            ],
        }
        valid_receipt = {
            "contextDecision": {
                "version": 1,
                "effect": "constrained",
                "summary": "  Kept one state source.  ",
                "ignored": "do not persist",
                "evidence": [
                    {
                        "repoUrl": "https://github.com/example/tree",
                        "commit": "a" * 40,
                        "nodePath": "system/architecture.md",
                        "heading": "Decision",
                        "ignored": "do not persist",
                    }
                ],
            },
            "other": "private metadata",
        }
        valid = self.export_scope(
            scope,
            "valid-receipt.jsonl",
            valid_receipt,
        )
        self.assertEqual(0, valid.returncode, valid.stderr)
        row = read_jsonl(self.artifacts / "valid-receipt.jsonl")[0]
        receipt = row["messages"][0]["decision_receipt"]
        self.assertEqual(
            {"version", "effect", "summary", "evidence"},
            set(receipt),
        )
        self.assertEqual(
            {"repoUrl", "commit", "nodePath", "heading"},
            set(receipt["evidence"][0]),
        )
        self.assertNotIn("context_decision_invalid", row["coverage_gaps"])
        receipt_chat = json.loads(json.dumps(row))
        receipt_chat["messages"][0]["content"] = "Kept one source."
        write_jsonl(self.artifacts / "chats.jsonl", [receipt_chat])
        receipt_only = self.collect("receipt-only-candidates.jsonl")
        self.assertEqual(0, receipt_only.returncode, receipt_only.stderr)
        receipt_candidate = read_jsonl(
            self.artifacts / "receipt-only-candidates.jsonl"
        )[0]
        self.assertEqual("candidate", receipt_candidate["candidate_status"])
        self.assertEqual(
            [MESSAGE_ID],
            [
                message["message_id"]
                for message in receipt_candidate["visible_choice_candidates"]
            ],
        )

        malformed = self.export_scope(
            scope,
            "malformed-receipt.jsonl",
            {"contextDecision": {"version": 1, "effect": ["not", "valid"]}},
        )
        self.assertEqual(0, malformed.returncode, malformed.stderr)
        malformed_row = read_jsonl(self.artifacts / "malformed-receipt.jsonl")[0]
        self.assertNotIn("decision_receipt", malformed_row["messages"][0])
        self.assertIn(
            "context_decision_invalid", malformed_row["coverage_gaps"]
        )

        for output_name, rejected_url in (
            (
                "credential-receipt.jsonl",
                "https://secret-token@example.com/org/tree.git",
            ),
            ("local-receipt.jsonl", "/private/context-tree"),
            ("non-repository-receipt.jsonl", "not-a-repository"),
            ("short-loopback-receipt.jsonl", "https://127.1/org/tree"),
            (
                "integer-loopback-receipt.jsonl",
                "https://2130706433/org/tree",
            ),
            ("unspecified-ipv4-receipt.jsonl", "https://0.0.0.0/org/tree"),
            ("unspecified-ipv6-receipt.jsonl", "https://[::]/org/tree"),
            (
                "mapped-loopback-receipt.jsonl",
                "https://[::ffff:127.0.0.1]/org/tree",
            ),
            (
                "hex-integer-loopback-receipt.jsonl",
                "https://0x7f000001/org/tree",
            ),
            (
                "hex-scp-loopback-receipt.jsonl",
                "git@0x7f000001:org/tree",
            ),
            (
                "hex-components-loopback-receipt.jsonl",
                "https://0x7f.0x0.0x0.0x1/org/tree",
            ),
            (
                "encoded-loopback-receipt.jsonl",
                "https://127%2e0%2e0%2e1/org/tree",
            ),
        ):
            unsafe_receipt = json.loads(json.dumps(valid_receipt))
            unsafe_receipt["contextDecision"]["evidence"][0][
                "repoUrl"
            ] = rejected_url
            unsafe = self.export_scope(
                scope,
                output_name,
                unsafe_receipt,
            )
            self.assertEqual(0, unsafe.returncode, unsafe.stderr)
            unsafe_text = (self.artifacts / output_name).read_text(
                encoding="utf-8"
            )
            self.assertNotIn(rejected_url, unsafe_text)
            unsafe_row = read_jsonl(self.artifacts / output_name)[0]
            self.assertNotIn("decision_receipt", unsafe_row["messages"][0])
            self.assertIn(
                "context_decision_invalid", unsafe_row["coverage_gaps"]
            )

        absent = self.export_scope(scope, "absent-receipt.jsonl", None)
        self.assertEqual(0, absent.returncode, absent.stderr)
        absent_row = read_jsonl(self.artifacts / "absent-receipt.jsonl")[0]
        self.assertNotIn("decision_receipt", absent_row["messages"][0])
        self.assertNotIn("context_decision_invalid", absent_row["coverage_gaps"])

        unbounded = self.export_scope(
            scope,
            "unbounded-window.jsonl",
            None,
            days=None,
        )
        self.assertEqual(0, unbounded.returncode, unbounded.stderr)
        self.assertIsNone(
            read_jsonl(self.artifacts / "unbounded-window.jsonl")[0]["window"]["start"]
        )

    def write_chat_export(self) -> Path:
        path = self.artifacts / "chats.jsonl"
        write_jsonl(
            path,
            [
                {
                    "schema_version": 1,
                    "audit_id": f"{CHAT_ID}@{AGENT_ID}",
                    "chat_id": CHAT_ID,
                    "title": "Choose one state source",
                    "authorization": "explicit_chat",
                    "source_agent": "fixture-agent",
                    "source_agent_id": AGENT_ID,
                    "messages": [
                        {
                            "message_id": ACCEPTANCE_MESSAGE_ID,
                            "created_at": "2026-07-22T10:01:00Z",
                            "sender_id": AGENT_ID,
                            "content": (
                                "I will choose the authoritative state source "
                                "and document the decision."
                            ),
                        },
                        {
                            "message_id": MESSAGE_ID,
                            "created_at": "2026-07-22T10:05:00Z",
                            "sender_id": AGENT_ID,
                            "content": (
                                "The Context Tree requires one authoritative state "
                                "source, so I will not add a second table."
                            ),
                            "decision_receipt": {
                                "version": 1,
                                "effect": "constrained",
                                "summary": "Kept one authoritative state source.",
                                "evidence": [
                                    {
                                        "repoUrl": "https://github.com/acme/tree",
                                        "commit": self.tree_commit,
                                        "nodePath": "system/architecture.md",
                                        "heading": "Decision",
                                    }
                                ],
                            },
                        }
                    ],
                    "coverage_gaps": [],
                }
            ],
        )
        return path

    def write_trace_fixtures(self) -> None:
        write_jsonl(
            self.trace_root / "authorized.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                {
                    "timestamp": "2026-07-22T10:02:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "call-authorized-read",
                        "arguments": json.dumps(
                            {
                                "cmd": f"cat {self.tree_file}",
                                "workdir": str(self.workspace),
                            }
                        ),
                    },
                },
                {
                    "timestamp": "2026-07-22T10:02:01Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-authorized-read",
                        "output": (
                            "Process exited with code 0\n"
                            "# Architecture\n\n## Decision\n\n"
                            "Chat history is the authoritative state."
                        ),
                    },
                },
            ],
        )

        unauthorized = self.trace_root / "unauthorized.jsonl"
        write_jsonl(
            unauthorized,
            [session_meta(self.workspace), context_row(UNAUTHORIZED_CHAT_ID)],
        )
        with unauthorized.open("a", encoding="utf-8") as handle:
            handle.write("not-json private-unauthorized-sentinel\n")

        write_jsonl(
            self.trace_root / "compound.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                {
                    "timestamp": "2026-07-22T10:03:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "call-compound-read",
                        "arguments": json.dumps(
                            {
                                "cmd": f"cat {self.tree_file} && printf mixed-output-sentinel",
                                "workdir": str(self.workspace),
                            }
                        ),
                    },
                },
                {
                    "timestamp": "2026-07-22T10:03:01Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-compound-read",
                        "output": (
                            "Process exited with code 0\n"
                            "Chat history is authoritative.\n"
                            "mixed-output-sentinel"
                        ),
                    },
                },
            ],
        )

        write_jsonl(
            self.trace_root / "read-only-composite.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                {
                    "timestamp": "2026-07-22T10:03:10Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "call-read-only-composite",
                        "arguments": json.dumps(
                            {
                                "cmd": (
                                    f"cd {self.tree_root} && "
                                    "test -f system/architecture.md && "
                                    "printf '%s\\n' tree-node-content && "
                                    "sed -n '1,80p' system/architecture.md && "
                                    "sed -n '1,80p' team-practice/dogfooding.md"
                                ),
                                "workdir": str(self.workspace),
                            }
                        ),
                    },
                },
                {
                    "timestamp": "2026-07-22T10:03:11Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-read-only-composite",
                        "output": (
                            "Process exited with code 0\n"
                            "tree-node-content\n"
                            "# Architecture\n\n## Decision\n\n"
                            "Chat history is the authoritative state.\n"
                            "# Dogfooding\n\n## Decision\n\n"
                            "Use First Tree in daily work."
                        ),
                    },
                },
            ],
        )

        orchestration_source = (
            "var nested = await tools.exec_command({"
            f"cmd: `sed -n '1,80p' {self.tree_file}; "
            f"sed -n '1,80p' {self.second_tree_file}`, "
            f'workdir: "{self.workspace}", '
            "yield_time_ms: 10000, max_output_tokens: 1000});\n"
            "text(nested.output);"
        )
        write_jsonl(
            self.trace_root / "exec-orchestration.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                {
                    "timestamp": "2026-07-22T10:03:20Z",
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call",
                        "name": "exec",
                        "call_id": "call-exec-orchestration",
                        "input": orchestration_source,
                    },
                },
                {
                    "timestamp": "2026-07-22T10:03:21Z",
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call_output",
                        "call_id": "call-exec-orchestration",
                        "output": [
                            {
                                "type": "input_text",
                                "text": "Script completed successfully\nOutput:\n",
                            },
                            {
                                "type": "input_text",
                                "text": (
                                    "# Architecture\n\n## Decision\n\n"
                                    "Chat history is the authoritative state.\n"
                                    "# Dogfooding\n\n## Decision\n\n"
                                    "Use First Tree in daily work."
                                ),
                            },
                        ],
                    },
                },
            ],
        )

        other_tree = self.root / "other-tree"
        other_file = other_tree / "system" / "architecture.md"
        other_file.parent.mkdir(parents=True)
        other_file.write_text("outside-bound-tree-sentinel", encoding="utf-8")
        write_jsonl(
            self.trace_root / "other-tree.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                {
                    "timestamp": "2026-07-22T10:04:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "call-other-tree-read",
                        "arguments": json.dumps(
                            {
                                "cmd": f"cat {other_file}",
                                "workdir": str(self.workspace),
                            }
                        ),
                    },
                },
                {
                    "timestamp": "2026-07-22T10:04:01Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-other-tree-read",
                        "output": "Process exited with code 0\noutside-bound-tree-sentinel",
                    },
                },
            ],
        )

    def collect(self, output_name: str) -> subprocess.CompletedProcess[str]:
        return run_cli(
            "collect",
            "--artifact-root",
            str(self.artifacts),
            "--chats",
            str(self.artifacts / "chats.jsonl"),
            "--trace-root",
            str(self.trace_root),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--tree-root",
            str(self.tree_root),
            "--days",
            "7",
            "--now",
            NOW,
            "--output",
            str(self.artifacts / output_name),
        )

    def collect_for_provider(
        self,
        provider: str,
        trace_root: Path,
        output_name: str,
    ) -> subprocess.CompletedProcess[str]:
        return run_cli(
            "collect",
            "--artifact-root",
            str(self.artifacts),
            "--chats",
            str(self.artifacts / "chats.jsonl"),
            "--trace-root",
            str(trace_root),
            "--runtime-provider",
            provider,
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--tree-root",
            str(self.tree_root),
            "--days",
            "7",
            "--now",
            NOW,
            "--output",
            str(self.artifacts / output_name),
            runtime_provider=provider,
        )

    def task_judgment(
        self,
        candidate: dict[str, Any],
        *,
        task_id: str = "task-1",
        message_id: str = MESSAGE_ID,
        objective_message_id: str | None = None,
        read_status: str = "observed",
        read_ids: list[str] | None = None,
        effect: dict[str, Any] | None | object = ...,
    ) -> dict[str, Any]:
        selected_reads = (
            read_ids
            if read_ids is not None
            else [candidate["reads"][0]["read_id"]]
            if candidate["reads"]
            else []
        )
        if effect is ...:
            effect = (
                {
                    "type": "constrained",
                    "read_ids": selected_reads,
                    "choice_message_ids": [message_id],
                    "outcome_anchor": message_id,
                    "summary": "The Tree constraint prevented a second state table.",
                }
                if selected_reads and read_status == "observed"
                else None
            )
        visible_message_ids = {
            message["message_id"]
            for message in candidate.get("visible_messages", [])
            if isinstance(message, dict)
            and isinstance(message.get("message_id"), str)
        }
        objective_anchor_id = (
            objective_message_id
            or (
                ACCEPTANCE_MESSAGE_ID
                if ACCEPTANCE_MESSAGE_ID in visible_message_ids
                and message_id != ACCEPTANCE_MESSAGE_ID
                else message_id
            )
        )
        source_message_ids = list(
            dict.fromkeys([objective_anchor_id, message_id])
        )
        message_times = {
            message["message_id"]: message["created_at"]
            for message in candidate.get("visible_messages", [])
            if isinstance(message, dict)
            and isinstance(message.get("message_id"), str)
            and isinstance(message.get("created_at"), str)
        }
        return {
            "schema_version": 4,
            "task_id": task_id,
            "status": "clear",
            "objective": "Choose one state source",
            "object_scope": "state persistence",
            "outcome": "Kept the existing authoritative state source.",
            "started_at": message_times.get(
                objective_anchor_id, "2026-07-22T10:01:00Z"
            ),
            "ended_at": message_times.get(
                message_id, "2026-07-22T10:05:00Z"
            ),
            "source_fragments": [
                {
                    "audit_id": candidate["audit_id"],
                    "message_ids": source_message_ids,
                }
            ],
            "episode": {
                "ownership": {
                    "kind": "accepted",
                    "anchor_message_ids": [objective_anchor_id],
                    "reason": "The audited Agent visibly accepted the objective.",
                },
                "objective_anchor_message_ids": [objective_anchor_id],
                "outcome_anchor_message_ids": [message_id],
                "continuation_message_ids": [],
                "primary_deliverable": "A decision selecting one state source.",
                "boundary_reason": (
                    "One accepted objective produced one terminal decision."
                ),
            },
            "read": {
                "status": read_status,
                "read_ids": selected_reads,
                "reason": (
                    "Historical trace coverage cannot confirm a read."
                    if read_status == "unresolved"
                    else None
                ),
            },
            "effect": effect,
            "effect_reason": (
                "No later choice reasonably shows Tree influence."
                if effect is None
                else None
            ),
        }

    def report(
        self,
        tasks: list[dict[str, Any]],
        *,
        candidates_name: str = "candidates.jsonl",
        evidence_name: str = "evidence.jsonl",
        report_name: str = "REPORT.md",
        reviewed_baseline_name: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        candidates_path = self.artifacts / candidates_name
        task_source_path = self.artifacts / "task-source.jsonl"
        task_source_result = run_cli(
            "task-source",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--candidates",
            str(candidates_path),
            "--output",
            str(task_source_path),
        )
        if task_source_result.returncode != 0:
            return task_source_result

        inventory_rows: list[dict[str, Any]] = []
        read_rows: list[dict[str, Any]] = []
        effect_rows: list[dict[str, Any]] = []
        for task in tasks:
            inventory = json.loads(json.dumps(task))
            read = inventory.pop("read", None)
            effect = inventory.pop("effect", None)
            effects = inventory.pop("effects", None)
            effect_reason = inventory.pop("effect_reason", None)
            episode = inventory.pop("episode", None)
            if isinstance(episode, dict):
                inventory["objective_source_message_ids"] = episode.get(
                    "objective_anchor_message_ids"
                )
                inventory["outcome_source_message_ids"] = episode.get(
                    "outcome_anchor_message_ids"
                )
                inventory["primary_deliverable"] = episode.get(
                    "primary_deliverable"
                )
            inventory_rows.append(inventory)

            if inventory.get("status") != "clear":
                continue
            task_id = inventory.get("task_id")
            if isinstance(read, dict):
                read_rows.append(
                    {
                        "schema_version": 4,
                        "task_id": task_id,
                        "status": read.get("status"),
                        "read_ids": read.get("read_ids"),
                        "reason": read.get("reason"),
                    }
                )
            selected_effects = (
                effects
                if effects is not None
                else [effect]
                if isinstance(effect, dict)
                else []
            )
            projected_effects = []
            for selected_effect in selected_effects:
                projected = dict(selected_effect)
                if "outcome_anchor" in projected:
                    projected["outcome_message_id"] = projected.pop(
                        "outcome_anchor"
                    )
                projected_effects.append(projected)
            effect_rows.append(
                {
                    "schema_version": 4,
                    "task_id": task_id,
                    "effects": projected_effects,
                    "effect_reason": effect_reason,
                }
            )

        inventory_draft_path = self.artifacts / "task-inventory-draft.jsonl"
        inventory_path = self.artifacts / "task-inventory.jsonl"
        write_jsonl(inventory_draft_path, inventory_rows)
        freeze_result = run_cli(
            "freeze-tasks",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--task-source",
            str(task_source_path),
            "--task-inventory-draft",
            str(inventory_draft_path),
            "--task-inventory-output",
            str(inventory_path),
        )
        if freeze_result.returncode != 0:
            return freeze_result
        frozen_rows = read_jsonl(inventory_path)
        inventory_sha256 = frozen_rows[0]["inventory_sha256"]
        for row in [*read_rows, *effect_rows]:
            row["inventory_sha256"] = inventory_sha256
        read_path = self.artifacts / "read-attributions.jsonl"
        effect_path = self.artifacts / "effect-judgments.jsonl"
        write_jsonl(read_path, read_rows)
        write_jsonl(effect_path, effect_rows)
        arguments = [
            "report",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--candidates",
            str(candidates_path),
            "--task-inventory",
            str(inventory_path),
            "--read-attributions",
            str(read_path),
            "--effect-judgments",
            str(effect_path),
            "--evidence-output",
            str(self.artifacts / evidence_name),
            "--report-output",
            str(self.artifacts / report_name),
            "--generated-at",
            NOW,
        ]
        if reviewed_baseline_name is not None:
            arguments.extend(
                [
                    "--reviewed-baseline",
                    str(self.artifacts / reviewed_baseline_name),
                ]
            )
        return run_cli(*arguments)

    def test_collect_prefilters_trace_and_recovers_read_only_composites(self) -> None:
        self.write_chat_export()
        self.write_trace_fixtures()

        first = self.collect("candidates-one.jsonl")
        second = self.collect("candidates-two.jsonl")
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual(
            (self.artifacts / "candidates-one.jsonl").read_bytes(),
            (self.artifacts / "candidates-two.jsonl").read_bytes(),
        )

        rows = read_jsonl(self.artifacts / "candidates-one.jsonl")
        self.assertEqual(1, len(rows))
        candidate = rows[0]
        self.assertEqual("candidate", candidate["candidate_status"])
        self.assertTrue(candidate["tree_identity"].startswith("tree-"))
        self.assertEqual(4, len(candidate["reads"]))
        isolated_read, compound_read, composite_read, orchestration_read = candidate[
            "reads"
        ]
        self.assertEqual(["system/architecture.md"], isolated_read["node_paths"])
        self.assertEqual("isolated", isolated_read["read_mode"])
        self.assertEqual(candidate["tree_identity"], isolated_read["tree_identity"])
        self.assertEqual(
            "default_branch_match",
            isolated_read["tree_source"]["status"],
        )
        self.assertIn("authoritative state", isolated_read["passage"])
        self.assertEqual(
            [
                "system/architecture.md",
                "team-practice/dogfooding.md",
            ],
            composite_read["node_paths"],
        )
        self.assertEqual("read_only_composite", composite_read["read_mode"])
        self.assertEqual(
            [
                {
                    "reader": "sed",
                    "node_paths": ["system/architecture.md"],
                },
                {
                    "reader": "sed",
                    "node_paths": ["team-practice/dogfooding.md"],
                },
            ],
            composite_read["read_components"],
        )
        self.assertIn("authoritative state", composite_read["passage"])
        self.assertIn("daily work", composite_read["passage"])
        self.assertEqual("read_only_composite", compound_read["read_mode"])
        self.assertEqual("read_only_composite", orchestration_read["read_mode"])
        self.assertEqual("exec", orchestration_read["tool_name"])
        self.assertEqual(
            {
                "accepted_exact": 1,
                "accepted_read_only_composite": 3,
                "unresolved_opaque": 0,
                "rejected_unsafe": 0,
            },
            candidate["collector_diagnostics"]["attempt_status_counts"],
        )
        self.assertEqual(
            4,
            candidate["collector_diagnostics"]["in_window_tree_read_attempts"],
        )
        self.assertTrue(all(item.startswith("trace-") for item in candidate["mapped_trace_files"]))
        self.assertEqual([], candidate["coverage_gaps"])
        self.assertEqual([MESSAGE_ID], [
            message["message_id"] for message in candidate["visible_choice_candidates"]
        ])

        serialized = json.dumps(candidate, sort_keys=True)
        self.assertNotIn("private-unauthorized-sentinel", serialized)
        self.assertNotIn("mixed-output-sentinel", serialized)
        self.assertNotIn("tree-node-content", serialized)
        self.assertNotIn("outside-bound-tree-sentinel", serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertEqual(
            0o600,
            stat.S_IMODE((self.artifacts / "candidates-one.jsonl").stat().st_mode),
        )

    def test_codex_missing_and_duplicate_results_stay_unresolved(self) -> None:
        self.write_chat_export()
        command = {
            "type": "function_call",
            "name": "exec_command",
            "arguments": json.dumps(
                {
                    "cmd": f"cat {self.tree_file}",
                    "workdir": str(self.workspace),
                }
            ),
        }
        output = (
            "Process exited with code 0\n"
            + self.tree_file.read_text(encoding="utf-8")
        )
        write_jsonl(
            self.trace_root / "missing-result.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                {
                    "timestamp": "2026-07-22T10:02:00Z",
                    "type": "response_item",
                    "payload": {
                        **command,
                        "call_id": "call-missing-result",
                    },
                },
            ],
        )
        write_jsonl(
            self.trace_root / "duplicate-call.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                *[
                    {
                        "timestamp": f"2026-07-22T10:03:0{index}Z",
                        "type": "response_item",
                        "payload": {
                            **command,
                            "call_id": "call-duplicate",
                        },
                    }
                    for index in (0, 1)
                ],
                {
                    "timestamp": "2026-07-22T10:03:02Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-duplicate",
                        "output": output,
                    },
                },
            ],
        )
        write_jsonl(
            self.trace_root / "duplicate-result.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                {
                    "timestamp": "2026-07-22T10:04:00Z",
                    "type": "response_item",
                    "payload": {
                        **command,
                        "call_id": "call-duplicate-result",
                    },
                },
                *[
                    {
                        "timestamp": f"2026-07-22T10:04:0{index}Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": "call-duplicate-result",
                            "output": output,
                        },
                    }
                    for index in (1, 2)
                ],
            ],
        )

        result = self.collect("codex-pairing-candidates.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "codex-pairing-candidates.jsonl"
        )[0]
        self.assertEqual([], candidate["reads"])
        self.assertEqual(
            {
                "accepted_exact": 0,
                "accepted_read_only_composite": 0,
                "unresolved_opaque": 4,
                "rejected_unsafe": 0,
            },
            candidate["collector_diagnostics"]["attempt_status_counts"],
        )
        self.assertEqual(
            {
                "codex_duplicate_call_id": 2,
                "codex_duplicate_tool_result": 1,
                "tree_read_output_missing": 1,
            },
            candidate["collector_diagnostics"]["attempt_reason_counts"],
        )

    def test_codex_explicit_direct_read_error_stays_unresolved(self) -> None:
        self.write_chat_export()
        write_jsonl(
            self.trace_root / "direct-read-error.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                {
                    "timestamp": "2026-07-22T10:02:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "read_file",
                        "call_id": "call-direct-read-error",
                        "arguments": json.dumps(
                            {"path": str(self.tree_file)}
                        ),
                    },
                },
                {
                    "timestamp": "2026-07-22T10:02:01Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-direct-read-error",
                        "output": "Error: permission denied",
                    },
                },
                {
                    "timestamp": "2026-07-22T10:02:02Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "read_file",
                        "call_id": "call-direct-read-json-error",
                        "arguments": json.dumps(
                            {"path": str(self.tree_file)}
                        ),
                    },
                },
                {
                    "timestamp": "2026-07-22T10:02:03Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-direct-read-json-error",
                        "output": json.dumps(
                            {"error": "permission denied"}
                        ),
                    },
                },
            ],
        )

        result = self.collect("direct-read-error-candidates.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "direct-read-error-candidates.jsonl"
        )[0]
        self.assertEqual([], candidate["reads"])
        self.assertEqual(
            {
                "accepted_exact": 0,
                "accepted_read_only_composite": 0,
                "unresolved_opaque": 2,
                "rejected_unsafe": 0,
            },
            candidate["collector_diagnostics"]["attempt_status_counts"],
        )
        self.assertEqual(
            {"tree_read_command_failed": 2},
            candidate["collector_diagnostics"]["attempt_reason_counts"],
        )

    def test_codex_read_call_id_shared_with_non_read_call_is_unresolved(
        self,
    ) -> None:
        self.write_chat_export()
        write_jsonl(
            self.trace_root / "ambiguous-call-id.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                {
                    "timestamp": "2026-07-22T10:02:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "read_file",
                        "call_id": "call-shared-with-non-read",
                        "arguments": json.dumps(
                            {"path": str(self.tree_file)}
                        ),
                    },
                },
                {
                    "timestamp": "2026-07-22T10:02:01Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "web_search",
                        "call_id": "call-shared-with-non-read",
                        "arguments": json.dumps({"query": "unrelated"}),
                    },
                },
                {
                    "timestamp": "2026-07-22T10:02:02Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-shared-with-non-read",
                        "output": self.tree_file.read_text(encoding="utf-8"),
                    },
                },
            ],
        )

        result = self.collect("ambiguous-call-id-candidates.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "ambiguous-call-id-candidates.jsonl"
        )[0]
        self.assertEqual([], candidate["reads"])
        self.assertEqual(
            {
                "accepted_exact": 0,
                "accepted_read_only_composite": 0,
                "unresolved_opaque": 1,
                "rejected_unsafe": 0,
            },
            candidate["collector_diagnostics"]["attempt_status_counts"],
        )
        self.assertEqual(
            {"codex_duplicate_call_id": 1},
            candidate["collector_diagnostics"]["attempt_reason_counts"],
        )

    def test_collects_claude_code_native_tool_results(self) -> None:
        self.write_chat_export()
        claude_config_root = self.root / "claude-config"
        trace_root = claude_config_root / "projects"
        write_jsonl(
            trace_root / "project" / "session.jsonl",
            [
                {
                    "type": "user",
                    "sessionId": "claude-session",
                    "cwd": str(self.workspace),
                    "timestamp": "2026-07-22T10:01:00Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": context_block(CHAT_ID)}],
                    },
                },
                {
                    "type": "assistant",
                    "sessionId": "claude-session",
                    "cwd": str(self.workspace),
                    "timestamp": "2026-07-22T10:02:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "claude-read",
                                "name": "Read",
                                "input": {"file_path": str(self.tree_file)},
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "sessionId": "claude-session",
                    "cwd": str(self.workspace),
                    "timestamp": "2026-07-22T10:02:01Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "claude-read",
                                "content": self.tree_file.read_text(encoding="utf-8"),
                            }
                        ],
                    },
                },
            ],
        )
        write_jsonl(
            trace_root / "unrelated" / "session.jsonl",
            [
                {
                    "type": "user",
                    "sessionId": "unrelated-session",
                    "cwd": str(self.root / "another-workspace"),
                    "timestamp": "2026-07-22T10:01:00Z",
                    "message": {"role": "user", "content": "unrelated"},
                }
            ],
        )

        result = self.collect_for_provider(
            "claude-code",
            trace_root,
            "claude-candidates.jsonl",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(self.artifacts / "claude-candidates.jsonl")[0]
        self.assertEqual("claude-code", candidate["runtime_provider"])
        self.assertEqual(1, len(candidate["reads"]))
        self.assertEqual(
            "claude-code",
            candidate["reads"][0]["runtime_provider"],
        )
        self.assertEqual(
            1,
            candidate["collector_diagnostics"]["attempt_status_counts"][
                "accepted_exact"
            ],
        )
        self.assertNotIn(
            "claude_trace_preflight_malformed_or_unmapped",
            candidate["coverage_gaps"],
        )
        tui_result = self.collect_for_provider(
            "claude-code-tui",
            trace_root,
            "claude-tui-candidates.jsonl",
        )
        self.assertEqual(0, tui_result.returncode, tui_result.stderr)
        self.assertEqual(
            "claude-code",
            read_jsonl(self.artifacts / "claude-tui-candidates.jsonl")[0][
                "runtime_provider"
            ],
        )
        default_root_result = run_cli(
            "collect",
            "--artifact-root",
            str(self.artifacts),
            "--chats",
            str(self.artifacts / "chats.jsonl"),
            "--runtime-provider",
            "claude-code",
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--tree-root",
            str(self.tree_root),
            "--days",
            "7",
            "--now",
            NOW,
            "--output",
            str(self.artifacts / "claude-custom-root-candidates.jsonl"),
            runtime_provider="claude-code",
            environment_overrides={
                "CLAUDE_CONFIG_DIR": str(claude_config_root),
            },
        )
        self.assertEqual(0, default_root_result.returncode, default_root_result.stderr)
        self.assertEqual(
            1,
            len(
                read_jsonl(
                    self.artifacts / "claude-custom-root-candidates.jsonl"
                )[0]["reads"]
            ),
        )

    def test_claude_failed_result_is_not_counted_as_accepted(self) -> None:
        self.write_chat_export()
        trace_root = self.root / "claude-failed"
        write_jsonl(
            trace_root / "project" / "session.jsonl",
            [
                {
                    "type": "user",
                    "sessionId": "claude-failed-session",
                    "cwd": str(self.workspace),
                    "timestamp": "2026-07-22T10:01:00Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": context_block(CHAT_ID)}],
                    },
                },
                {
                    "type": "assistant",
                    "sessionId": "claude-failed-session",
                    "cwd": str(self.workspace),
                    "timestamp": "2026-07-22T10:02:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "claude-failed-read",
                                "name": "Read",
                                "input": {"file_path": str(self.tree_file)},
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "sessionId": "claude-failed-session",
                    "cwd": str(self.workspace),
                    "timestamp": "2026-07-22T10:02:01Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "claude-failed-read",
                                "is_error": True,
                                "content": "read failed",
                            }
                        ],
                    },
                },
            ],
        )
        result = self.collect_for_provider(
            "claude-code",
            trace_root,
            "claude-failed-candidates.jsonl",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "claude-failed-candidates.jsonl"
        )[0]
        self.assertEqual([], candidate["reads"])
        self.assertEqual(
            0,
            candidate["collector_diagnostics"]["attempt_status_counts"][
                "accepted_exact"
            ],
        )
        self.assertEqual(
            1,
            candidate["collector_diagnostics"]["attempt_status_counts"][
                "unresolved_opaque"
            ],
        )
        self.assertEqual(
            {"tree_read_command_failed": 1},
            candidate["collector_diagnostics"]["attempt_reason_counts"],
        )

    def test_claude_tool_result_context_echo_is_not_identity(self) -> None:
        self.write_chat_export()
        trace_root = self.root / "claude-echo"
        write_jsonl(
            trace_root / "project" / "session.jsonl",
            [
                {
                    "type": "user",
                    "sessionId": "claude-echo-session",
                    "cwd": str(self.workspace),
                    "timestamp": "2026-07-22T10:01:00Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "echo",
                                "content": context_block(CHAT_ID),
                            }
                        ],
                    },
                }
            ],
        )

        result = self.collect_for_provider(
            "claude-code",
            trace_root,
            "claude-echo-candidates.jsonl",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "claude-echo-candidates.jsonl"
        )[0]
        self.assertEqual([], candidate["reads"])
        self.assertIn(
            "claude_trace_preflight_malformed_or_unmapped",
            candidate["coverage_gaps"],
        )

    def test_claude_ignores_native_non_message_metadata_rows(self) -> None:
        self.write_chat_export()
        trace_root = self.root / "claude-native-metadata"
        session_id = "claude-native-metadata-session"
        metadata_rows = [
            {
                "type": row_type,
                "sessionId": session_id,
                "timestamp": f"2026-07-22T10:01:0{index}Z",
            }
            for index, row_type in enumerate(
                ("queue-operation", "last-prompt", "mode"),
                start=1,
            )
        ]
        write_jsonl(
            trace_root / "project" / "session.jsonl",
            [
                {
                    "type": "user",
                    "sessionId": session_id,
                    "cwd": str(self.workspace),
                    "timestamp": "2026-07-22T10:01:00Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": context_block(CHAT_ID)}],
                    },
                },
                *metadata_rows,
                {
                    "type": "assistant",
                    "sessionId": session_id,
                    "cwd": str(self.workspace),
                    "timestamp": "2026-07-22T10:02:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "claude-metadata-read",
                                "name": "Read",
                                "input": {"file_path": str(self.tree_file)},
                            }
                        ],
                    },
                },
                {
                    "type": "last-prompt",
                    "sessionId": session_id,
                    "timestamp": "2026-07-22T10:02:00.500Z",
                },
                {
                    "type": "user",
                    "sessionId": session_id,
                    "cwd": str(self.workspace),
                    "timestamp": "2026-07-22T10:02:01Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "claude-metadata-read",
                                "content": self.tree_file.read_text(encoding="utf-8"),
                            }
                        ],
                    },
                },
            ],
        )

        result = self.collect_for_provider(
            "claude-code",
            trace_root,
            "claude-native-metadata-candidates.jsonl",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "claude-native-metadata-candidates.jsonl"
        )[0]
        self.assertEqual(1, len(candidate["reads"]))
        self.assertNotIn(
            "claude_trace_workspace_changed",
            candidate["coverage_gaps"],
        )

    def test_claude_compact_and_meta_context_echoes_are_not_identity(self) -> None:
        self.write_chat_export()
        for marker in ("isCompactSummary", "isMeta"):
            with self.subTest(marker=marker, position="only"):
                trace_root = self.root / f"claude-{marker}-only"
                write_jsonl(
                    trace_root / "project" / "session.jsonl",
                    [
                        {
                            "type": "user",
                            marker: True,
                            "sessionId": "claude-synthetic-session",
                            "cwd": str(self.workspace),
                            "timestamp": "2026-07-22T10:01:00Z",
                            "message": {
                                "role": "user",
                                "content": [{"type": "text", "text": context_block(CHAT_ID)}],
                            },
                        }
                    ],
                )
                result = self.collect_for_provider(
                    "claude-code",
                    trace_root,
                    f"claude-{marker}-only-candidates.jsonl",
                )
                self.assertEqual(0, result.returncode, result.stderr)
                candidate = read_jsonl(
                    self.artifacts / f"claude-{marker}-only-candidates.jsonl"
                )[0]
                self.assertEqual([], candidate["reads"])
                self.assertIn(
                    "no_mapped_claude_code_evidence",
                    candidate["coverage_gaps"],
                )

            with self.subTest(marker=marker, position="after-preflight"):
                trace_root = self.root / f"claude-{marker}-late"
                session_id = "claude-late-session"
                canonical = {
                    "type": "user",
                    "sessionId": session_id,
                    "cwd": str(self.workspace),
                    "timestamp": "2026-07-22T10:01:00Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": context_block(CHAT_ID)}],
                    },
                }
                filler = [
                    {
                        "type": "assistant",
                        "sessionId": session_id,
                        "cwd": str(self.workspace),
                        "timestamp": "2026-07-22T10:01:01Z",
                        "message": {"role": "assistant", "content": []},
                    }
                    for _ in range(511)
                ]
                synthetic = {
                    "type": "user",
                    marker: True,
                    "sessionId": session_id,
                    "timestamp": "2026-07-22T10:01:02Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": context_block(SECOND_CHAT_ID)}],
                    },
                }
                call = {
                    "type": "assistant",
                    "sessionId": session_id,
                    "cwd": str(self.workspace),
                    "timestamp": "2026-07-22T10:02:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": f"claude-{marker}-read",
                                "name": "Read",
                                "input": {"file_path": str(self.tree_file)},
                            }
                        ],
                    },
                }
                tool_result = {
                    "type": "user",
                    "sessionId": session_id,
                    "cwd": str(self.workspace),
                    "timestamp": "2026-07-22T10:02:01Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": f"claude-{marker}-read",
                                "content": self.tree_file.read_text(encoding="utf-8"),
                            }
                        ],
                    },
                }
                write_jsonl(
                    trace_root / "project" / "session.jsonl",
                    [canonical, *filler, synthetic, call, tool_result],
                )
                result = self.collect_for_provider(
                    "claude-code",
                    trace_root,
                    f"claude-{marker}-late-candidates.jsonl",
                )
                self.assertEqual(0, result.returncode, result.stderr)
                candidate = read_jsonl(
                    self.artifacts / f"claude-{marker}-late-candidates.jsonl"
                )[0]
                self.assertEqual(1, len(candidate["reads"]))
                self.assertNotIn(
                    "claude_trace_chat_boundary_changed",
                    candidate["coverage_gaps"],
                )

    def test_claude_full_scan_rejects_post_preflight_session_and_chat_drift(
        self,
    ) -> None:
        self.write_chat_export()
        initial = {
            "type": "user",
            "sessionId": "claude-session-a",
            "cwd": str(self.workspace),
            "timestamp": "2026-07-22T10:01:00Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": context_block(CHAT_ID)}],
            },
        }
        filler = [
            {
                "type": "assistant",
                "sessionId": "claude-session-a",
                "cwd": str(self.workspace),
                "timestamp": "2026-07-22T10:01:01Z",
                "message": {"role": "assistant", "content": []},
            }
            for _ in range(511)
        ]
        cases = {
            "session": {
                "type": "assistant",
                "sessionId": "claude-session-b",
                "cwd": str(self.workspace),
                "timestamp": "2026-07-22T10:02:00Z",
                "message": {"role": "assistant", "content": []},
            },
            "chat": {
                "type": "user",
                "sessionId": "claude-session-a",
                "cwd": str(self.workspace),
                "timestamp": "2026-07-22T10:02:00Z",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": context_block(SECOND_CHAT_ID),
                        }
                    ],
                },
            },
        }
        expected = {
            "session": "claude_trace_session_changed",
            "chat": "claude_trace_chat_boundary_changed",
        }
        for name, drift in cases.items():
            with self.subTest(name=name):
                trace_root = self.root / f"claude-{name}-drift"
                write_jsonl(
                    trace_root / "project" / "session.jsonl",
                    [initial, *filler, drift],
                )
                result = self.collect_for_provider(
                    "claude-code",
                    trace_root,
                    f"claude-{name}-drift-candidates.jsonl",
                )
                self.assertEqual(0, result.returncode, result.stderr)
                candidate = read_jsonl(
                    self.artifacts / f"claude-{name}-drift-candidates.jsonl"
                )[0]
                self.assertEqual([], candidate["reads"])
                self.assertIn(expected[name], candidate["coverage_gaps"])

    def test_runtimes_without_complete_native_evidence_stay_pending(self) -> None:
        self.write_chat_export()
        for provider in ("cursor", "kimi-code"):
            with self.subTest(provider=provider):
                result = self.collect_for_provider(
                    provider,
                    self.trace_root,
                    f"{provider}-unsupported-candidates.jsonl",
                )
                self.assertEqual(0, result.returncode, result.stderr)
                candidate = read_jsonl(
                    self.artifacts / f"{provider}-unsupported-candidates.jsonl"
                )[0]
                self.assertEqual([], candidate["reads"])
                self.assertIn(
                    f"{provider.replace('-', '_')}_historical_evidence_not_supported",
                    candidate["coverage_gaps"],
                )

    def test_claude_pairing_fail_closes_duplicate_calls(self) -> None:
        self.write_chat_export()
        claude_root = self.root / "claude-duplicate"
        claude_rows = [
            {
                "type": "user",
                "sessionId": "claude-duplicate-session",
                "cwd": str(self.workspace),
                "timestamp": "2026-07-22T10:01:00Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": context_block(CHAT_ID)}],
                },
            },
            *[
                {
                    "type": "assistant",
                    "sessionId": "claude-duplicate-session",
                    "cwd": str(self.workspace),
                    "timestamp": f"2026-07-22T10:02:0{index}Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "duplicate-read",
                                "name": "Read",
                                "input": {"file_path": str(self.tree_file)},
                            }
                        ],
                    },
                }
                for index in (0, 1)
            ],
            {
                "type": "user",
                "sessionId": "claude-duplicate-session",
                "cwd": str(self.workspace),
                "timestamp": "2026-07-22T10:02:02Z",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "duplicate-read",
                            "content": self.tree_file.read_text(encoding="utf-8"),
                        }
                    ],
                },
            },
        ]
        write_jsonl(claude_root / "project" / "session.jsonl", claude_rows)
        claude_result = self.collect_for_provider(
            "claude-code",
            claude_root,
            "claude-duplicate-candidates.jsonl",
        )
        self.assertEqual(0, claude_result.returncode, claude_result.stderr)
        claude_candidate = read_jsonl(
            self.artifacts / "claude-duplicate-candidates.jsonl"
        )[0]
        self.assertEqual([], claude_candidate["reads"])
        self.assertIn(
            "claude_tool_call_duplicate",
            claude_candidate["coverage_gaps"],
        )
        self.assertEqual(
            {
                "accepted_exact": 0,
                "accepted_read_only_composite": 0,
                "unresolved_opaque": 2,
                "rejected_unsafe": 0,
            },
            claude_candidate["collector_diagnostics"]["attempt_status_counts"],
        )
        self.assertEqual(
            {"unresolved_claude_tool_call_duplicate": 2},
            claude_candidate["collector_diagnostics"]["attempt_reason_counts"],
        )
        self.assertEqual(
            2,
            claude_candidate["collector_diagnostics"][
                "in_window_tree_read_attempts"
            ],
        )

    def test_claude_unpaired_tree_calls_stay_in_attempt_denominator(self) -> None:
        self.write_chat_export()
        claude_root = self.root / "claude-unpaired"
        context = {
            "type": "user",
            "sessionId": "claude-unpaired-session",
            "cwd": str(self.workspace),
            "timestamp": "2026-07-22T10:01:00Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": context_block(CHAT_ID)}],
            },
        }
        missing_call = {
            "type": "assistant",
            "sessionId": "claude-unpaired-session",
            "cwd": str(self.workspace),
            "timestamp": "2026-07-22T10:02:00Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "missing-result",
                        "name": "Read",
                        "input": {"file_path": str(self.tree_file)},
                    }
                ],
            },
        }
        write_jsonl(
            claude_root / "missing" / "session.jsonl",
            [context, missing_call],
        )

        duplicate_call = json.loads(json.dumps(missing_call))
        duplicate_call["message"]["content"][0]["id"] = "duplicate-result"
        duplicate_result = {
            "type": "user",
            "sessionId": "claude-unpaired-session",
            "cwd": str(self.workspace),
            "timestamp": "2026-07-22T10:02:01Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "duplicate-result",
                        "content": self.tree_file.read_text(encoding="utf-8"),
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "duplicate-result",
                        "content": self.tree_file.read_text(encoding="utf-8"),
                    },
                ],
            },
        }
        write_jsonl(
            claude_root / "duplicate" / "session.jsonl",
            [context, duplicate_call, duplicate_result],
        )

        result = self.collect_for_provider(
            "claude-code",
            claude_root,
            "claude-unpaired-candidates.jsonl",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "claude-unpaired-candidates.jsonl"
        )[0]
        self.assertEqual([], candidate["reads"])
        self.assertEqual(
            {
                "accepted_exact": 0,
                "accepted_read_only_composite": 0,
                "unresolved_opaque": 2,
                "rejected_unsafe": 0,
            },
            candidate["collector_diagnostics"]["attempt_status_counts"],
        )
        self.assertEqual(
            {
                "unresolved_claude_tool_result_duplicate": 1,
                "unresolved_claude_tool_result_missing": 1,
            },
            candidate["collector_diagnostics"]["attempt_reason_counts"],
        )
        self.assertEqual(
            2,
            candidate["collector_diagnostics"]["in_window_tree_read_attempts"],
        )
        self.assertIn("claude_tool_result_duplicate", candidate["coverage_gaps"])
        self.assertIn("claude_tool_result_missing", candidate["coverage_gaps"])

    def test_claude_pairing_respects_the_acquisition_window(self) -> None:
        self.write_chat_export()
        claude_root = self.root / "claude-window"

        def context(timestamp: str, session_id: str) -> dict[str, Any]:
            return {
                "type": "user",
                "sessionId": session_id,
                "cwd": str(self.workspace),
                "timestamp": timestamp,
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": context_block(CHAT_ID)}],
                },
            }

        def call(timestamp: str, session_id: str, call_id: str) -> dict[str, Any]:
            return {
                "type": "assistant",
                "sessionId": session_id,
                "cwd": str(self.workspace),
                "timestamp": timestamp,
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": call_id,
                            "name": "Read",
                            "input": {"file_path": str(self.tree_file)},
                        }
                    ],
                },
            }

        def result(timestamp: str, session_id: str, call_id: str) -> dict[str, Any]:
            return {
                "type": "user",
                "sessionId": session_id,
                "cwd": str(self.workspace),
                "timestamp": timestamp,
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": call_id,
                            "content": self.tree_file.read_text(encoding="utf-8"),
                        }
                    ],
                },
            }

        write_jsonl(
            claude_root / "cross-end" / "session.jsonl",
            [
                context("2026-07-23T23:58:00Z", "cross-end-session"),
                call(
                    "2026-07-23T23:59:00Z",
                    "cross-end-session",
                    "cross-end-read",
                ),
                result(
                    "2026-07-24T00:01:00Z",
                    "cross-end-session",
                    "cross-end-read",
                ),
            ],
        )
        write_jsonl(
            claude_root / "old-missing" / "session.jsonl",
            [
                context("2026-07-16T10:00:00Z", "old-missing-session"),
                call(
                    "2026-07-16T10:01:00Z",
                    "old-missing-session",
                    "old-missing-read",
                ),
            ],
        )
        old_duplicate_result = result(
            "2026-07-16T10:02:00Z",
            "old-duplicate-session",
            "old-duplicate-read",
        )
        write_jsonl(
            claude_root / "old-duplicate" / "session.jsonl",
            [
                context("2026-07-16T10:00:00Z", "old-duplicate-session"),
                call(
                    "2026-07-16T10:01:00Z",
                    "old-duplicate-session",
                    "old-duplicate-read",
                ),
                old_duplicate_result,
                json.loads(json.dumps(old_duplicate_result)),
            ],
        )

        collect_result = self.collect_for_provider(
            "claude-code",
            claude_root,
            "claude-window-candidates.jsonl",
        )
        self.assertEqual(0, collect_result.returncode, collect_result.stderr)
        candidate = read_jsonl(
            self.artifacts / "claude-window-candidates.jsonl"
        )[0]
        self.assertEqual([], candidate["reads"])
        self.assertEqual(
            {
                "accepted_exact": 0,
                "accepted_read_only_composite": 0,
                "unresolved_opaque": 1,
                "rejected_unsafe": 0,
            },
            candidate["collector_diagnostics"]["attempt_status_counts"],
        )
        self.assertEqual(
            {"unresolved_claude_code_tool_result_outside_window": 1},
            candidate["collector_diagnostics"]["attempt_reason_counts"],
        )
        self.assertEqual(
            1,
            candidate["collector_diagnostics"]["in_window_tree_read_attempts"],
        )
        self.assertIn(
            "claude_code_tool_result_outside_window",
            candidate["coverage_gaps"],
        )
        self.assertNotIn(
            "claude_tool_result_missing",
            candidate["coverage_gaps"],
        )
        self.assertNotIn(
            "claude_tool_result_duplicate",
            candidate["coverage_gaps"],
        )

    def test_provider_mismatch_fails_before_trace_collection(self) -> None:
        self.write_chat_export()
        result = run_cli(
            "collect",
            "--artifact-root",
            str(self.artifacts),
            "--chats",
            str(self.artifacts / "chats.jsonl"),
            "--trace-root",
            str(self.trace_root),
            "--runtime-provider",
            "claude-code",
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--tree-root",
            str(self.tree_root),
            "--output",
            str(self.artifacts / "mismatch.jsonl"),
            runtime_provider="cursor",
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("must match FIRST_TREE_PROVIDER", result.stderr)

    def test_missing_runtime_provider_fails_before_trace_collection(self) -> None:
        self.write_chat_export()
        result = run_cli(
            "collect",
            "--artifact-root",
            str(self.artifacts),
            "--chats",
            str(self.artifacts / "chats.jsonl"),
            "--trace-root",
            str(self.trace_root),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--tree-root",
            str(self.tree_root),
            "--output",
            str(self.artifacts / "missing-provider.jsonl"),
            runtime_provider=None,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("FIRST_TREE_PROVIDER is required", result.stderr)

    def test_preflight_accepts_same_id_mirror_and_ignores_noncanonical_echoes(
        self,
    ) -> None:
        self.write_chat_export()
        write_jsonl(
            self.trace_root / "production-envelope.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                context_mirror_row(CHAT_ID),
                {
                    "timestamp": "2026-07-22T10:01:01Z",
                    "type": "compacted",
                    "payload": {
                        "message": context_block(UNAUTHORIZED_CHAT_ID),
                        "replacement_history": [],
                    },
                },
                {
                    "timestamp": "2026-07-22T10:01:02Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-echo-only",
                        "output": context_block(UNAUTHORIZED_CHAT_ID),
                    },
                },
                {
                    "timestamp": "2026-07-22T10:02:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "call-production-read",
                        "arguments": json.dumps(
                            {
                                "cmd": f"cat {self.tree_file}",
                                "workdir": str(self.workspace),
                            }
                        ),
                    },
                },
                {
                    "timestamp": "2026-07-22T10:02:01Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-production-read",
                        "output": (
                            "Process exited with code 0\n"
                            "# Architecture\n\n## Decision\n\n"
                            "Chat history is the authoritative state."
                        ),
                    },
                },
            ],
        )

        result = self.collect("production-envelope-candidates.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "production-envelope-candidates.jsonl"
        )[0]
        self.assertEqual(1, len(candidate["mapped_trace_files"]))
        self.assertEqual(1, len(candidate["reads"]))
        self.assertNotIn(
            "codex_trace_preflight_malformed_or_ambiguous",
            candidate["coverage_gaps"],
        )

    def test_exec_command_continuations_complete_one_read_attempt(self) -> None:
        self.write_chat_export()
        write_jsonl(
            self.trace_root / "continued-read.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                {
                    "timestamp": "2026-07-22T10:02:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "call-started-read",
                        "arguments": json.dumps(
                            {
                                "cmd": f"cat {self.tree_file}",
                                "workdir": str(self.workspace),
                            }
                        ),
                    },
                },
                {
                    "timestamp": "2026-07-22T10:02:01Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-started-read",
                        "output": "Script running with session ID 731",
                    },
                },
                {
                    "timestamp": "2026-07-22T10:02:02Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "write_stdin",
                        "call_id": "call-continued-read",
                        "arguments": json.dumps(
                            {"session_id": 731, "chars": ""}
                        ),
                    },
                },
                {
                    "timestamp": "2026-07-22T10:02:03Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-continued-read",
                        "output": (
                            "Process exited with code 0\n"
                            "# Architecture\n\n## Decision\n\n"
                            "Chat history is the authoritative state."
                        ),
                    },
                },
            ],
        )

        result = self.collect("continued-candidate.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(self.artifacts / "continued-candidate.jsonl")[0]
        self.assertEqual(1, len(candidate["reads"]))
        self.assertIn("authoritative state", candidate["reads"][0]["passage"])
        self.assertNotIn("tree_read_output_pending", candidate["coverage_gaps"])
        self.assertEqual(
            1,
            candidate["collector_diagnostics"]["attempt_status_counts"][
                "accepted_exact"
            ],
        )

    def test_duplicate_continuation_output_keeps_parent_unresolved(self) -> None:
        self.write_chat_export()
        terminal_output = (
            "Process exited with code 0\n"
            "# Architecture\n\n## Decision\n\n"
            "Chat history is the authoritative state."
        )
        write_jsonl(
            self.trace_root / "duplicate-continuation.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                {
                    "timestamp": "2026-07-22T10:02:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "call-duplicate-continuation-parent",
                        "arguments": json.dumps(
                            {
                                "cmd": f"cat {self.tree_file}",
                                "workdir": str(self.workspace),
                            }
                        ),
                    },
                },
                {
                    "timestamp": "2026-07-22T10:02:01Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-duplicate-continuation-parent",
                        "output": "Script running with session ID 733",
                    },
                },
                {
                    "timestamp": "2026-07-22T10:02:02Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "write_stdin",
                        "call_id": "call-duplicate-continuation",
                        "arguments": json.dumps(
                            {"session_id": 733, "chars": ""}
                        ),
                    },
                },
                *[
                    {
                        "timestamp": f"2026-07-22T10:02:0{index}Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": "call-duplicate-continuation",
                            "output": terminal_output,
                        },
                    }
                    for index in (3, 4)
                ],
            ],
        )

        result = self.collect("duplicate-continuation-candidate.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "duplicate-continuation-candidate.jsonl"
        )[0]
        self.assertEqual([], candidate["reads"])
        self.assertEqual(
            {"tree_read_continuation_output_duplicate": 1},
            candidate["collector_diagnostics"]["attempt_reason_counts"],
        )

    def test_continuation_after_acquisition_end_stays_pending(self) -> None:
        self.write_chat_export()
        write_jsonl(
            self.trace_root / "late-continuation.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                {
                    "timestamp": "2026-07-23T23:59:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "call-late-start",
                        "arguments": json.dumps(
                            {
                                "cmd": f"cat {self.tree_file}",
                                "workdir": str(self.workspace),
                            }
                        ),
                    },
                },
                {
                    "timestamp": "2026-07-23T23:59:01Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-late-start",
                        "output": "Script running with session ID 732",
                    },
                },
                {
                    "timestamp": "2026-07-24T00:01:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "write_stdin",
                        "call_id": "call-late-finish",
                        "arguments": json.dumps(
                            {"session_id": 732, "chars": ""}
                        ),
                    },
                },
                {
                    "timestamp": "2026-07-24T00:01:01Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-late-finish",
                        "output": (
                            "Process exited with code 0\n"
                            "# Architecture\n\nlate-private-passage"
                        ),
                    },
                },
            ],
        )

        result = self.collect("late-continuation-candidate.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "late-continuation-candidate.jsonl"
        )[0]
        self.assertEqual([], candidate["reads"])
        self.assertIn(
            "tree_read_continuation_incomplete_or_out_of_order",
            candidate["coverage_gaps"],
        )
        self.assertNotIn("late-private-passage", json.dumps(candidate))

    def test_exec_orchestration_classifies_exact_and_promise_all(self) -> None:
        self.write_chat_export()
        exact_source = (
            "const result = await tools.exec_command({"
            f"cmd: `cat {self.tree_file}`, workdir: `{self.workspace}`"
            "});\ntext(result.output);"
        )
        promise_source = (
            "const results = await Promise.all(["
            "tools.exec_command({"
            f"cmd: `cat {self.tree_file}`, workdir: `{self.workspace}`"
            "}),"
            "tools.exec_command({"
            f"cmd: `cat {self.second_tree_file}`, workdir: `{self.workspace}`"
            "})]);\nresults.forEach((result) => text(result.output));"
        )
        loop_source = (
            "const result = await tools.exec_command({"
            "cmd: `for node in "
            f"{self.tree_file} {self.second_tree_file}; "
            "do sed -n '1,80p' \"$node\"; done`, "
            f"workdir: `{self.workspace}`"
            "});\ntext(result.output);"
        )
        null_sink_source = (
            "const result = await tools.exec_command({"
            f"cmd: `test -f {self.tree_file} >/dev/null 2>&1 && "
            f"sed -n '1,80p' {self.tree_file}`, "
            f"workdir: `{self.workspace}`"
            "});\ntext(result.output);"
        )
        diagnostic_source = (
            "const results = await Promise.all(["
            "tools.exec_command({"
            f"cmd: `pwd`, workdir: `{self.workspace}`"
            "}),"
            "tools.exec_command({"
            f"cmd: `cat {self.tree_file}`, workdir: `{self.workspace}`"
            "})]);\nresults.forEach((result) => text(result.output));"
        )
        for filename, call_id, timestamp, source, output in (
            (
                "exec-exact.jsonl",
                "call-exec-exact",
                "2026-07-22T10:02:00Z",
                exact_source,
                "# Architecture\n\nChat history is authoritative.",
            ),
            (
                "exec-promise.jsonl",
                "call-exec-promise",
                "2026-07-22T10:03:00Z",
                promise_source,
                [
                    "# Architecture\n\nChat history is authoritative.\n"
                    ,
                    "# Dogfooding\n\nUse First Tree daily.",
                ],
            ),
            (
                "exec-loop.jsonl",
                "call-exec-loop",
                "2026-07-22T10:04:00Z",
                loop_source,
                (
                    "# Architecture\n\nChat history is authoritative.\n"
                    "# Dogfooding\n\nUse First Tree daily."
                ),
            ),
            (
                "exec-null-sink.jsonl",
                "call-exec-null-sink",
                "2026-07-22T10:05:00Z",
                null_sink_source,
                "# Architecture\n\nChat history is authoritative.",
            ),
            (
                "exec-diagnostic.jsonl",
                "call-exec-diagnostic",
                "2026-07-22T10:06:00Z",
                diagnostic_source,
                [
                    str(self.workspace),
                    "# Architecture\n\nChat history is authoritative.",
                ],
            ),
        ):
            write_jsonl(
                self.trace_root / filename,
                [
                    session_meta(self.workspace),
                    context_row(CHAT_ID),
                    {
                        "timestamp": timestamp,
                        "type": "response_item",
                        "payload": {
                            "type": "custom_tool_call",
                            "name": "functions.exec",
                            "call_id": call_id,
                            "input": source,
                        },
                    },
                    {
                        "timestamp": timestamp,
                        "type": "response_item",
                        "payload": {
                            "type": "custom_tool_call_output",
                            "call_id": call_id,
                            "output": [
                                {
                                    "type": "input_text",
                                    "text": (
                                        "Script completed successfully\nOutput:\n"
                                    ),
                                },
                                *[
                                    {"type": "input_text", "text": item}
                                    for item in (
                                        output
                                        if isinstance(output, list)
                                        else [output]
                                    )
                                ],
                            ],
                        },
                    },
                ],
            )

        result = self.collect("exec-orchestration-candidate.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "exec-orchestration-candidate.jsonl"
        )[0]
        self.assertEqual(5, len(candidate["reads"]))
        self.assertEqual(
            [
                "isolated",
                "isolated",
                "isolated",
                "read_only_composite",
                "read_only_composite",
            ],
            [read["read_mode"] for read in candidate["reads"]],
        )
        self.assertEqual(
            ["exact", "exact", "exact", "aggregate", "aggregate"],
            [read["output_attribution"] for read in candidate["reads"]],
        )
        self.assertNotIn(
            "Script completed successfully",
            "\n".join(read["passage"] for read in candidate["reads"]),
        )
        self.assertEqual(
            {
                "accepted_exact": 1,
                "accepted_read_only_composite": 3,
                "unresolved_opaque": 1,
                "rejected_unsafe": 0,
            },
            candidate["collector_diagnostics"]["attempt_status_counts"],
        )
        self.assertIn(
            "tree_read_auxiliary_output_unresolved",
            candidate["coverage_gaps"],
        )

    def test_literal_if_guards_preserve_reads_and_fail_closed(self) -> None:
        self.write_chat_export()
        commands = {
            "test-guard": (
                f"if test -f {self.tree_file}; then "
                f"sed -n '1,80p' {self.tree_file}; fi"
            ),
            "bracket-guard": (
                f"if [ -r {self.second_tree_file} ]; then "
                f"cat {self.second_tree_file}; fi"
            ),
            "read-sequence": (
                f"cat {self.tree_file} && "
                f"if [ -r {self.second_tree_file} ]; then "
                f"sed -n '1,80p' {self.second_tree_file}; fi && "
                f"cat {self.tree_file}"
            ),
            "mixed-diagnostic": (
                "pwd && "
                f"cat {self.tree_file} && "
                f"if [ -r {self.second_tree_file} ]; then "
                f"cat {self.second_tree_file}; fi"
            ),
            "else-branch": (
                f"if test -f {self.tree_file}; then "
                f"cat {self.tree_file}; else cat {self.second_tree_file}; fi"
            ),
            "dynamic-guard": (
                f'if test -f "$NODE"; then cat {self.tree_file}; fi'
            ),
            "mutating-body": (
                f"if test -f {self.tree_file}; then "
                f"git -C {self.tree_root} pull; cat {self.tree_file}; fi"
            ),
        }
        for index, (label, command) in enumerate(commands.items(), start=1):
            call_id = f"call-if-{label}"
            write_jsonl(
                self.trace_root / f"if-{label}.jsonl",
                [
                    session_meta(self.workspace),
                    context_row(CHAT_ID),
                    {
                        "timestamp": f"2026-07-22T12:0{index}:00Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "call_id": call_id,
                            "arguments": json.dumps(
                                {
                                    "cmd": command,
                                    "workdir": str(self.workspace),
                                }
                            ),
                        },
                    },
                    {
                        "timestamp": f"2026-07-22T12:0{index}:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": f"literal-if-output-{label}",
                        },
                    },
                ],
            )

        result = self.collect("literal-if-candidate.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "literal-if-candidate.jsonl"
        )[0]
        self.assertEqual(3, len(candidate["reads"]))
        self.assertEqual(
            {
                "accepted_exact": 0,
                "accepted_read_only_composite": 3,
                "unresolved_opaque": 3,
                "rejected_unsafe": 1,
            },
            candidate["collector_diagnostics"]["attempt_status_counts"],
        )
        self.assertEqual(
            {
                "unresolved_shell_conditional": 1,
                "unresolved_unknown_program": 1,
                "unsafe_git_mutation": 1,
                "tree_read_auxiliary_output_unresolved": 1,
            },
            candidate["collector_diagnostics"]["attempt_reason_counts"],
        )
        self.assertIn(
            "tree_read_auxiliary_output_unresolved",
            candidate["coverage_gaps"],
        )

    def test_semicolonless_forwarding_rechecks_inner_literals(
        self,
    ) -> None:
        self.write_chat_export()
        sources = {
            "literal-first": (
                "const result = await tools.exec_command({"
                f"cmd: `cat {self.tree_file}`, "
                f"workdir: `{self.workspace}`"
                "});\n"
                "text(result.output)"
            ),
            "literal-second": (
                "const result = await tools.exec_command({"
                f"cmd: `cat {self.second_tree_file}`, "
                f"workdir: `{self.workspace}`"
                "});\n"
                "text(result.output)"
            ),
            "dynamic-command": (
                "const result = await tools.exec_command({"
                f"cmd: prefix + `cat {self.tree_file}`, "
                f"workdir: `{self.workspace}`"
                "});\n"
                "text(result.output)"
            ),
            "dynamic-workdir": (
                "const result = await tools.exec_command({"
                f"cmd: `cat {self.tree_file}`, workdir: selectedWorkdir"
                "});\n"
                "text(result.output)"
            ),
            "dynamic-options": (
                "const result = await tools.exec_command({"
                f"cmd: `cat {self.tree_file}`, "
                f"workdir: `{self.workspace}`, yield_time_ms: selectedYield"
                "});\n"
                "text(result.output)"
            ),
        }
        for index, (label, source) in enumerate(sources.items(), start=1):
            call_id = f"call-semicolonless-{label}"
            write_jsonl(
                self.trace_root / f"semicolonless-{label}.jsonl",
                [
                    session_meta(self.workspace),
                    context_row(CHAT_ID),
                    {
                        "timestamp": f"2026-07-22T13:0{index}:00Z",
                        "type": "response_item",
                        "payload": {
                            "type": "custom_tool_call",
                            "name": "functions.exec",
                            "call_id": call_id,
                            "input": source,
                        },
                    },
                    {
                        "timestamp": f"2026-07-22T13:0{index}:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "custom_tool_call_output",
                            "call_id": call_id,
                            "output": [
                                {
                                    "type": "input_text",
                                    "text": f"semicolonless-output-{label}",
                                }
                            ],
                        },
                    },
                ],
            )

        result = self.collect("semicolonless-candidate.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "semicolonless-candidate.jsonl"
        )[0]
        self.assertEqual(2, len(candidate["reads"]))
        self.assertEqual(
            {
                "accepted_exact": 2,
                "accepted_read_only_composite": 0,
                "unresolved_opaque": 3,
                "rejected_unsafe": 0,
            },
            candidate["collector_diagnostics"]["attempt_status_counts"],
        )
        self.assertEqual(
            {
                "unresolved_exec_dynamic_arguments": 3,
            },
            candidate["collector_diagnostics"]["attempt_reason_counts"],
        )

    def test_exec_orchestration_fail_closes_dynamic_and_unsafe_shapes(self) -> None:
        self.write_chat_export()
        shapes = (
            (
                "dynamic",
                (
                    f"const target = `{self.tree_file}`;\n"
                    "const result = await tools.exec_command({"
                    "cmd: `sed -n '1,80p' ${target}`});\n"
                    "text(result.output);"
                ),
            ),
            (
                "unknown-program",
                (
                    "const result = await tools.exec_command({"
                    f"cmd: `awk '{{print}}' {self.tree_file}`"
                    "});\ntext(result.output);"
                ),
            ),
            (
                "file-redirection",
                (
                    "const result = await tools.exec_command({"
                    f"cmd: `cat {self.tree_file} > captured.txt`, "
                    f"workdir: `{self.workspace}`"
                    "});\ntext(result.output);"
                ),
            ),
            (
                "git-pull",
                (
                    "const result = await tools.exec_command({"
                    f"cmd: `git -C {self.tree_root} pull && "
                    f"cat {self.tree_file}`"
                    "});\ntext(result.output);"
                ),
            ),
            (
                "outside-tree",
                (
                    "const result = await tools.exec_command({"
                    f"cmd: `cat {self.tree_file} /private/outside/example.md`"
                    "});\ntext(result.output);"
                ),
            ),
        )
        for index, (label, source) in enumerate(shapes, start=1):
            call_id = f"call-{label}"
            write_jsonl(
                self.trace_root / f"{label}.jsonl",
                [
                    session_meta(self.workspace),
                    context_row(CHAT_ID),
                    {
                        "timestamp": f"2026-07-22T10:0{index}:00Z",
                        "type": "response_item",
                        "payload": {
                            "type": "custom_tool_call",
                            "name": "exec",
                            "call_id": call_id,
                            "input": source,
                        },
                    },
                    {
                        "timestamp": f"2026-07-22T10:0{index}:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "custom_tool_call_output",
                            "call_id": call_id,
                            "output": f"unsafe-private-{label}",
                        },
                    },
                ],
            )

        result = self.collect("exec-fail-closed.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(self.artifacts / "exec-fail-closed.jsonl")[0]
        self.assertEqual([], candidate["reads"])
        self.assertEqual(
            {
                "accepted_exact": 0,
                "accepted_read_only_composite": 0,
                "unresolved_opaque": 2,
                "rejected_unsafe": 3,
            },
            candidate["collector_diagnostics"]["attempt_status_counts"],
        )
        self.assertEqual(
            {
                "unresolved_exec_wrapper_shape": 1,
                "unresolved_unknown_program": 1,
                "unsafe_shell_redirection": 1,
                "unsafe_git_mutation": 1,
                "unsafe_literal_non_tree_path": 1,
            },
            candidate["collector_diagnostics"]["attempt_reason_counts"],
        )
        self.assertNotIn("unsafe-private-", json.dumps(candidate, sort_keys=True))

    def test_exec_orchestration_rejects_wrapper_side_effects_and_reordering(
        self,
    ) -> None:
        self.write_chat_export()
        call = (
            "tools.exec_command({"
            f"cmd: `cat {self.tree_file}`, workdir: `{self.workspace}`"
            "})"
        )
        second_call = (
            "tools.exec_command({"
            f"cmd: `cat {self.second_tree_file}`, workdir: `{self.workspace}`"
            "})"
        )
        sources = {
            "mutated-output": (
                f"let result = await {call}; "
                'result.output = "forged"; text(result.output);'
            ),
            "aliased-text": (
                f"const emit = text; const result = await {call}; "
                'emit("forged"); text(result.output);'
            ),
            "promise-side-effect": (
                "const results = await Promise.all(["
                f"{call}, {second_call}"
                "]); results.forEach((result) => {"
                'result.output = "forged"; text(result.output); });'
            ),
            "reversed-forwarding": (
                f"const first = await {call}; "
                f"const second = await {second_call}; "
                "text(second.output); text(first.output);"
            ),
            "dead-branch": (
                f"const result = await {call}; "
                'if (false) { text("forged"); } text(result.output);'
            ),
            "property-expression": (
                "const result = await tools.exec_command({"
                f"cmd: `cat {self.tree_file}`, "
                'max_output_tokens: text("forged")'
                "}); text(result.output);"
            ),
            "duplicate-command": (
                "const result = await tools.exec_command({"
                f"cmd: `cat {self.tree_file}`, "
                f"cmd: `cat {self.second_tree_file}`"
                "}); text(result.output);"
            ),
            "unknown-nested-command": (
                "const results = await Promise.all(["
                'tools.exec_command({cmd: "date"}), '
                f"{call}"
                "]); results.forEach((result) => text(result.output));"
            ),
            "unsafe-nested-command": (
                "const results = await Promise.all(["
                'tools.exec_command({cmd: "curl https://example.invalid"}), '
                f"{call}"
                "]); results.forEach((result) => text(result.output));"
            ),
        }
        for index, (label, source) in enumerate(sources.items(), start=1):
            call_id = f"call-wrapper-{label}"
            write_jsonl(
                self.trace_root / f"wrapper-{label}.jsonl",
                [
                    session_meta(self.workspace),
                    context_row(CHAT_ID),
                    {
                        "timestamp": f"2026-07-22T11:0{index}:00Z",
                        "type": "response_item",
                        "payload": {
                            "type": "custom_tool_call",
                            "name": "functions.exec",
                            "call_id": call_id,
                            "input": source,
                        },
                    },
                    {
                        "timestamp": f"2026-07-22T11:0{index}:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "custom_tool_call_output",
                            "call_id": call_id,
                            "output": f"forged-wrapper-output-{label}",
                        },
                    },
                ],
            )

        result = self.collect("exec-wrapper-adversarial.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "exec-wrapper-adversarial.jsonl"
        )[0]
        self.assertEqual([], candidate["reads"])
        self.assertEqual(
            {
                "accepted_exact": 0,
                "accepted_read_only_composite": 0,
                "unresolved_opaque": 8,
                "rejected_unsafe": 1,
            },
            candidate["collector_diagnostics"]["attempt_status_counts"],
        )
        self.assertNotIn(
            "forged-wrapper-output",
            json.dumps(candidate, sort_keys=True),
        )

    def test_git_rg_and_stderr_shapes_fail_closed(self) -> None:
        self.write_chat_export()
        root_node = self.tree_root / "NODE.md"
        root_node.write_text("# Root\n", encoding="utf-8")
        outside = self.root / "outside-secret.txt"
        outside.write_text("outside", encoding="utf-8")
        shapes = (
            (
                "git-output",
                (
                    f"git -C {self.tree_root} diff "
                    "--output=captured.diff && "
                    f"cat {self.tree_file}"
                ),
                "unsafe",
            ),
            (
                "git-no-index",
                (
                    f"cd {self.tree_root} && "
                    f"git diff --no-index NODE.md {outside} && "
                    f"cat {self.tree_file}"
                ),
                "unsafe",
            ),
            (
                "git-implicit-diff-helper",
                (
                    f"git -C {self.tree_root} diff && "
                    f"cat {self.tree_file}"
                ),
                "unsafe",
            ),
            (
                "git-implicit-log-helper",
                (
                    f"git -C {self.tree_root} log -1 -p && "
                    f"cat {self.tree_file}"
                ),
                "unsafe",
            ),
            (
                "git-implicit-show-helper",
                (
                    f"git -C {self.tree_root} show HEAD && "
                    f"cat {self.tree_file}"
                ),
                "unsafe",
            ),
            (
                "git-implicit-status-hook",
                (
                    f"git -C {self.tree_root} status && "
                    f"cat {self.tree_file}"
                ),
                "unsafe",
            ),
            (
                "git-global-exec-path",
                (
                    f"git --exec-path=/tmp diff && "
                    f"cat {self.tree_file}"
                ),
                "unsafe",
            ),
            (
                "git-inline-config",
                (
                    "git -c diff.external=/tmp/helper diff && "
                    f"cat {self.tree_file}"
                ),
                "unsafe",
            ),
            (
                "git-index-revision",
                (
                    f"git -C {self.tree_root} rev-parse --verify :tracked && "
                    f"cat {self.tree_file}"
                ),
                "unsafe",
            ),
            (
                "git-external-repository-path",
                (
                    f"git -C {self.tree_root} rev-parse "
                    "--resolve-git-dir ~/.git && "
                    f"cat {self.tree_file}"
                ),
                "unsafe",
            ),
            (
                "rg-pattern-only",
                (
                    f"cd {self.tree_root} && "
                    f"rg --no-config --no-ignore {self.tree_file}"
                ),
                "opaque",
            ),
            (
                "rg-file-read",
                (
                    f"cd {self.tree_root} && "
                    "rg --no-config --no-ignore "
                    "Decision system/architecture.md"
                ),
                "read",
            ),
            (
                "git-remote",
                (
                    f"git -C {self.tree_root} remote get-url origin && "
                    f"cat {self.tree_file}"
                ),
                "unsafe",
            ),
            (
                "stderr-null",
                f"sed -n '1,80p' {self.tree_file} 2>/dev/null",
                "read",
            ),
        )
        for index, (label, command, expected) in enumerate(shapes, start=1):
            call_id = f"call-{label}"
            output = (
                "# Architecture\n\n## Decision\n\n"
                "Chat history is the authoritative state."
                if expected == "read"
                else "diagnostic-or-private-output"
            )
            write_jsonl(
                self.trace_root / f"{label}.jsonl",
                [
                    session_meta(self.workspace),
                    context_row(CHAT_ID),
                    {
                        "timestamp": f"2026-07-22T11:{10 + index:02d}:00Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "call_id": call_id,
                            "arguments": json.dumps(
                                {
                                    "cmd": command,
                                    "workdir": str(self.workspace),
                                }
                            ),
                        },
                    },
                    {
                        "timestamp": f"2026-07-22T11:{10 + index:02d}:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": f"Process exited with code 0\n{output}",
                        },
                    },
                ],
            )

        result = self.collect("git-rg-stderr.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(self.artifacts / "git-rg-stderr.jsonl")[0]
        self.assertEqual(2, len(candidate["reads"]))
        self.assertEqual(
            {
                "accepted_exact": 1,
                "accepted_read_only_composite": 1,
                "unresolved_opaque": 1,
                "rejected_unsafe": 11,
            },
            candidate["collector_diagnostics"]["attempt_status_counts"],
        )
        self.assertEqual(
            {
                "unsafe_git_configured_helper": 4,
                "unsafe_git_option": 4,
                "unsafe_git_unbound_configuration": 3,
                "unresolved_tree_path_without_content_reader": 1,
            },
            candidate["collector_diagnostics"]["attempt_reason_counts"],
        )
        self.assertNotIn(
            "tree_read_auxiliary_output_unresolved",
            candidate["coverage_gaps"],
        )
        self.assertNotIn(
            "diagnostic-or-private-output",
            json.dumps(candidate, sort_keys=True),
        )

    def test_tree_cli_and_rg_options_use_closed_read_only_grammars(self) -> None:
        self.write_chat_export()
        outside_ignore = self.root / "outside.ignore"
        outside_ignore.write_text("private pattern", encoding="utf-8")
        shapes = {
            "tree-selector": (
                f"cd {self.tree_root} && "
                "first-tree-staging tree tree -P '*.md' -L 2 --no-pull && "
                f"cat {self.tree_file}"
            ),
            "tree-default-refresh": (
                f"cd {self.tree_root} && "
                "first-tree-staging tree tree -P '*.md' -L 2 && "
                f"cat {self.tree_file}"
            ),
            "tree-help": (
                "first-tree-staging tree tree --help && "
                f"cat {self.tree_file}"
            ),
            "tree-mutating-namespace": (
                f"cd {self.tree_root} && "
                "first-tree-staging chat send tree tree && "
                f"cat {self.tree_file}"
            ),
            "tree-path-qualified": (
                f"/tmp/first-tree-staging tree tree && cat {self.tree_file}"
            ),
            "rg-file-equals": (
                f"cd {self.tree_root} && "
                f"rg --file=/etc/passwd Decision {self.tree_file}"
            ),
            "rg-ignore-file": (
                f"cd {self.tree_root} && "
                f"rg --ignore-file {outside_ignore} "
                f"Decision {self.tree_file}"
            ),
            "rg-unknown-option": (
                f"cd {self.tree_root} && "
                f"rg --mystery Decision {self.tree_file}"
            ),
            "rg-stdin": (
                f"cd {self.tree_root} && "
                f"rg -- Decision - && cat {self.tree_file}"
            ),
            "rg-absolute-executable": (
                f"/tmp/rg Decision {self.tree_file}"
            ),
            "rg-relative-executable": (
                f"./rg Decision {self.tree_file}"
            ),
            "bat-bare": (
                f"bat {self.tree_file}"
            ),
            "bat-forced-paging": (
                f"bat --paging=always {self.tree_file}"
            ),
            "bat-closed-looking": (
                f"bat --no-config --paging=never {self.tree_file}"
            ),
            "find-bare": (
                f"find {self.tree_root} -type f && cat {self.tree_file}"
            ),
            "find-file-valued": (
                f"find -files0-from=/etc/passwd && cat {self.tree_file}"
            ),
            "ls-bare": (
                f"ls {self.tree_root} && cat {self.tree_file}"
            ),
            "ls-recursive-dereference": (
                f"ls -RL {self.tree_root} && cat {self.tree_file}"
            ),
            "head-open-pipeline-option": (
                f"cat {self.tree_file} | head --help"
            ),
            "tail-open-pipeline-option": (
                f"cat {self.tree_file} | tail --follow=name"
            ),
            "nl-open-pipeline-option": (
                f"cat {self.tree_file} | nl --help"
            ),
            "rg-implicit-config": (
                f"cd {self.tree_root} && "
                f"rg Decision {self.tree_file}"
            ),
            "rg-implicit-ignore": (
                f"cd {self.tree_root} && "
                f"rg --no-config Decision {self.tree_file}"
            ),
            "cat-path-qualified": (
                f"/usr/bin/cat {self.tree_file}"
            ),
            "rg-closed-options": (
                f"cd {self.tree_root} && "
                "rg --no-config --no-ignore -n -g '*.md' "
                f"Decision {self.tree_file}"
            ),
        }
        for index, (label, command) in enumerate(shapes.items(), start=1):
            call_id = f"call-closed-grammar-{label}"
            write_jsonl(
                self.trace_root / f"closed-grammar-{label}.jsonl",
                [
                    session_meta(self.workspace),
                    context_row(CHAT_ID),
                    {
                        "timestamp": f"2026-07-22T14:{index:02d}:00Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "call_id": call_id,
                            "arguments": json.dumps(
                                {
                                    "cmd": command,
                                    "workdir": str(self.workspace),
                                }
                            ),
                        },
                    },
                    {
                        "timestamp": f"2026-07-22T14:{index:02d}:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": (
                                "Process exited with code 0\n"
                                "# Architecture\n\n## Decision\n\n"
                                f"closed-grammar-output-{label}"
                            ),
                        },
                    },
                ],
            )

        result = self.collect("closed-command-grammars.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "closed-command-grammars.jsonl"
        )[0]
        self.assertEqual(1, len(candidate["reads"]))
        self.assertEqual(
            {
                "accepted_exact": 0,
                "accepted_read_only_composite": 1,
                "unresolved_opaque": 5,
                "rejected_unsafe": 19,
            },
            candidate["collector_diagnostics"]["attempt_status_counts"],
        )
        self.assertEqual(
            {
                "unsafe_first_tree_command": 2,
                "unsafe_or_unresolved_rg": 4,
                "unsafe_path_qualified_program": 4,
                "unsafe_find_unbound_grammar": 2,
                "unsafe_ls_unbound_grammar": 2,
                "unsafe_program_bat": 3,
                "unsafe_rg_option": 2,
                "unresolved_unknown_program": 3,
                "tree_read_auxiliary_output_unresolved": 2,
            },
            candidate["collector_diagnostics"]["attempt_reason_counts"],
        )
        self.assertEqual(
            25,
            candidate["collector_diagnostics"]["in_window_tree_read_attempts"],
        )
        serialized = json.dumps(candidate, sort_keys=True)
        for label in (
            "tree-mutating-namespace",
            "tree-default-refresh",
            "rg-file-equals",
            "rg-ignore-file",
            "rg-unknown-option",
            "rg-stdin",
            "rg-implicit-config",
            "rg-implicit-ignore",
            "rg-absolute-executable",
            "rg-relative-executable",
            "bat-bare",
            "bat-forced-paging",
            "bat-closed-looking",
            "find-bare",
            "find-file-valued",
            "ls-bare",
            "ls-recursive-dereference",
            "head-open-pipeline-option",
            "tail-open-pipeline-option",
            "nl-open-pipeline-option",
            "cat-path-qualified",
            "tree-path-qualified",
        ):
            self.assertNotIn(f"closed-grammar-output-{label}", serialized)

    def test_preflight_rejects_conflicting_mirror_and_mirror_only_trace(
        self,
    ) -> None:
        self.write_chat_export()
        write_jsonl(
            self.trace_root / "conflicting-mirror.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                context_mirror_row(UNAUTHORIZED_CHAT_ID),
                {
                    "timestamp": "2026-07-22T10:02:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-conflicting-mirror",
                        "output": "conflicting-mirror-private-sentinel",
                    },
                },
            ],
        )
        write_jsonl(
            self.trace_root / "mirror-only.jsonl",
            [
                session_meta(self.workspace),
                context_mirror_row(CHAT_ID),
                {
                    "timestamp": "2026-07-22T10:02:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-mirror-only",
                        "output": "mirror-only-private-sentinel",
                    },
                },
            ],
        )

        result = self.collect("rejected-envelope-candidates.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "rejected-envelope-candidates.jsonl"
        )[0]
        self.assertEqual([], candidate["mapped_trace_files"])
        self.assertEqual([], candidate["reads"])
        self.assertIn(
            "codex_trace_preflight_malformed_or_ambiguous",
            candidate["coverage_gaps"],
        )
        self.assertIn("codex_trace_preflight_unmapped", candidate["coverage_gaps"])
        serialized = json.dumps(candidate, sort_keys=True)
        self.assertNotIn("conflicting-mirror-private-sentinel", serialized)
        self.assertNotIn("mirror-only-private-sentinel", serialized)

    def test_preflight_rejects_two_canonical_chat_ids(self) -> None:
        self.write_chat_export()
        write_jsonl(
            self.trace_root / "canonical-chat-drift.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                context_mirror_row(CHAT_ID),
                context_row(SECOND_CHAT_ID),
                context_mirror_row(SECOND_CHAT_ID),
            ],
        )

        result = self.collect("canonical-chat-drift-candidates.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(
            self.artifacts / "canonical-chat-drift-candidates.jsonl"
        )[0]
        self.assertEqual([], candidate["mapped_trace_files"])
        self.assertIn(
            "codex_trace_preflight_ambiguous_chat",
            candidate["coverage_gaps"],
        )

    def test_report_is_task_first_deterministic_and_rejects_invalid_effects(self) -> None:
        self.write_chat_export()
        self.write_trace_fixtures()
        collected = self.collect("candidates.jsonl")
        self.assertEqual(0, collected.returncode, collected.stderr)
        candidate = read_jsonl(self.artifacts / "candidates.jsonl")[0]
        task = self.task_judgment(candidate)

        first = self.report(
            [task],
            evidence_name="minimal-evidence-one.jsonl",
            report_name="minimal-REPORT-one.md",
        )
        second = self.report(
            [task],
            evidence_name="minimal-evidence-two.jsonl",
            report_name="minimal-REPORT-two.md",
        )
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual(
            (self.artifacts / "minimal-evidence-one.jsonl").read_bytes(),
            (self.artifacts / "minimal-evidence-two.jsonl").read_bytes(),
        )
        self.assertEqual(
            (self.artifacts / "minimal-REPORT-one.md").read_bytes(),
            (self.artifacts / "minimal-REPORT-two.md").read_bytes(),
        )
        markdown = (self.artifacts / "minimal-REPORT-one.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("| Clear Tasks | 1 |", markdown)
        self.assertIn("| Read observed Tasks | 1 |", markdown)
        self.assertIn("| Effect Tasks | 1 |", markdown)
        self.assertIn("| Observed Read without Effect | 0 |", markdown)
        self.assertIn("| constrained | 1 |", markdown)
        self.assertIn("There is no minimum Task quota", markdown)
        self.assertIn("Tree-read grammar conservation", markdown)
        evidence = read_jsonl(self.artifacts / "minimal-evidence-one.jsonl")
        self.assertEqual("constrained", evidence[0]["effects"][0]["type"])
        self.assertIn("effect_id", evidence[0]["effects"][0])
        self.assertNotIn("derived_support", evidence[0]["effects"][0])

        invalid = json.loads(json.dumps(task))
        invalid["effect"]["type"] = "informed"
        invalid_result = self.report(
            [invalid],
            evidence_name="minimal-invalid-evidence.jsonl",
            report_name="minimal-invalid-REPORT.md",
        )
        self.assertEqual(2, invalid_result.returncode)
        self.assertIn(".type must be one of", invalid_result.stderr)

        missing_anchor = json.loads(json.dumps(task))
        missing_anchor["effect"].pop("outcome_anchor")
        missing_anchor_result = self.report(
            [missing_anchor],
            evidence_name="minimal-missing-anchor-evidence.jsonl",
            report_name="minimal-missing-anchor-REPORT.md",
        )
        self.assertEqual(2, missing_anchor_result.returncode)
        self.assertIn("outcome_message_id", missing_anchor_result.stderr)

    def test_report_survives_tree_advance_and_rejects_v02_confidence_fields(
        self,
    ) -> None:
        self.write_chat_export()
        self.write_trace_fixtures()
        collected = self.collect("candidates.jsonl")
        self.assertEqual(0, collected.returncode, collected.stderr)
        candidate = read_jsonl(self.artifacts / "candidates.jsonl")[0]
        task = self.task_judgment(candidate)

        self.tree_file.write_text(
            "# Architecture\n\n## Decision\n\nChat history remains authoritative.\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "-C", str(self.tree_root), "add", "."],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(self.tree_root), "commit", "-m", "advance"],
            check=True,
            capture_output=True,
            text=True,
        )
        advanced_commit = subprocess.run(
            ["git", "-C", str(self.tree_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            [
                "git",
                "-C",
                str(self.tree_root),
                "update-ref",
                "refs/remotes/origin/main",
                advanced_commit,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        accepted = self.report(
            [task],
            evidence_name="source-neutral-evidence.jsonl",
            report_name="source-neutral-REPORT.md",
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)

        for field, value in (
            ("original_judgment", "probable"),
            ("rubric", {"real_read": True}),
            ("support", "limited"),
        ):
            legacy = json.loads(json.dumps(task))
            legacy["effect"][field] = value
            result = self.report(
                [legacy],
                evidence_name=f"legacy-{field}-evidence.jsonl",
                report_name=f"legacy-{field}-REPORT.md",
            )
            self.assertEqual(2, result.returncode)
            self.assertIn("superseded model", result.stderr)

    def test_report_supports_multiple_effects_and_enforces_inventory_digest(
        self,
    ) -> None:
        self.write_chat_export()
        self.write_trace_fixtures()
        collected = self.collect("candidates.jsonl")
        self.assertEqual(0, collected.returncode, collected.stderr)
        candidate = read_jsonl(self.artifacts / "candidates.jsonl")[0]
        second_choice_id = "second-effect-choice"
        second_choice = {
            "message_id": second_choice_id,
            "created_at": "2026-07-22T10:04:00Z",
            "sender_id": AGENT_ID,
            "sender_kind": "agent",
            "content": "I will retain the current source and document its boundary.",
        }
        candidate["visible_messages"].append(second_choice)
        candidate["visible_choice_candidates"].append(
            {
                field: second_choice[field]
                for field in ("message_id", "created_at", "sender_id", "content")
            }
        )
        candidate["chat"]["message_count"] += 1
        write_jsonl(self.artifacts / "candidates.jsonl", [candidate])

        task = self.task_judgment(candidate)
        task["source_fragments"][0]["message_ids"].insert(-1, second_choice_id)
        read_id = candidate["reads"][0]["read_id"]
        task["effects"] = [
            {
                "type": "confirmed",
                "read_ids": [read_id],
                "choice_message_ids": [second_choice_id],
                "outcome_message_id": MESSAGE_ID,
                "summary": "The Tree removed uncertainty about retaining the source.",
            },
            {
                "type": "constrained",
                "read_ids": [read_id],
                "choice_message_ids": [MESSAGE_ID],
                "outcome_message_id": MESSAGE_ID,
                "summary": "The Tree ruled out creating a second state table.",
            },
        ]
        task.pop("effect")
        task["effect_reason"] = None
        accepted = self.report(
            [task],
            evidence_name="multi-effect-evidence.jsonl",
            report_name="multi-effect-REPORT.md",
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        evidence = read_jsonl(self.artifacts / "multi-effect-evidence.jsonl")
        self.assertEqual(2, len(evidence[0]["effects"]))
        self.assertEqual(
            2, len({effect["effect_id"] for effect in evidence[0]["effects"]})
        )
        report = (self.artifacts / "multi-effect-REPORT.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("| Effect Tasks | 1 |", report)
        self.assertIn("| Effects | 2 |", report)
        self.assertIn("| confirmed | 1 |", report)
        self.assertIn("| constrained | 1 |", report)
        valid_read_rows = read_jsonl(
            self.artifacts / "read-attributions.jsonl"
        )
        valid_effect_rows = read_jsonl(
            self.artifacts / "effect-judgments.jsonl"
        )

        same_time_candidate = json.loads(json.dumps(candidate))
        same_time_candidate["reads"][0]["completed_at"] = second_choice[
            "created_at"
        ]
        write_jsonl(
            self.artifacts / "same-time-candidates.jsonl",
            [same_time_candidate],
        )
        same_time_result = run_cli(
            "report",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--candidates",
            str(self.artifacts / "same-time-candidates.jsonl"),
            "--task-inventory",
            str(self.artifacts / "task-inventory.jsonl"),
            "--read-attributions",
            str(self.artifacts / "read-attributions.jsonl"),
            "--effect-judgments",
            str(self.artifacts / "effect-judgments.jsonl"),
            "--evidence-output",
            str(self.artifacts / "same-time-evidence.jsonl"),
            "--report-output",
            str(self.artifacts / "same-time-REPORT.md"),
            "--generated-at",
            NOW,
        )
        self.assertEqual(2, same_time_result.returncode)
        self.assertIn(
            "complete before its earliest choice",
            same_time_result.stderr,
        )

        reversed_read_candidate = json.loads(json.dumps(candidate))
        reversed_read_candidate["reads"][0]["timestamp"] = (
            "2026-07-22T10:03:00Z"
        )
        reversed_read_candidate["reads"][0]["completed_at"] = (
            "2026-07-22T10:02:00Z"
        )
        write_jsonl(
            self.artifacts / "reversed-read-candidates.jsonl",
            [reversed_read_candidate],
        )
        reversed_read_result = run_cli(
            "report",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--candidates",
            str(self.artifacts / "reversed-read-candidates.jsonl"),
            "--task-inventory",
            str(self.artifacts / "task-inventory.jsonl"),
            "--read-attributions",
            str(self.artifacts / "read-attributions.jsonl"),
            "--effect-judgments",
            str(self.artifacts / "effect-judgments.jsonl"),
            "--evidence-output",
            str(self.artifacts / "reversed-read-evidence.jsonl"),
            "--report-output",
            str(self.artifacts / "reversed-read-REPORT.md"),
            "--generated-at",
            NOW,
        )
        self.assertEqual(2, reversed_read_result.returncode)
        self.assertIn(
            "must complete after it starts",
            reversed_read_result.stderr,
        )

        zero_duration_read_candidate = json.loads(json.dumps(candidate))
        zero_duration_read_candidate["reads"][0]["completed_at"] = (
            zero_duration_read_candidate["reads"][0]["timestamp"]
        )
        write_jsonl(
            self.artifacts / "zero-duration-read-candidates.jsonl",
            [zero_duration_read_candidate],
        )
        zero_duration_read_result = run_cli(
            "report",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--candidates",
            str(self.artifacts / "zero-duration-read-candidates.jsonl"),
            "--task-inventory",
            str(self.artifacts / "task-inventory.jsonl"),
            "--read-attributions",
            str(self.artifacts / "read-attributions.jsonl"),
            "--effect-judgments",
            str(self.artifacts / "effect-judgments.jsonl"),
            "--evidence-output",
            str(self.artifacts / "zero-duration-read-evidence.jsonl"),
            "--report-output",
            str(self.artifacts / "zero-duration-read-REPORT.md"),
            "--generated-at",
            NOW,
        )
        self.assertEqual(2, zero_duration_read_result.returncode)
        self.assertIn(
            "must complete after it starts",
            zero_duration_read_result.stderr,
        )

        frozen_rows = read_jsonl(self.artifacts / "task-inventory.jsonl")
        tampered_rows = json.loads(json.dumps(frozen_rows))
        tampered_rows[0]["objective"] = "A changed objective after freeze"
        write_jsonl(self.artifacts / "task-inventory.jsonl", tampered_rows)
        tampered_result = run_cli(
            "report",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--candidates",
            str(self.artifacts / "candidates.jsonl"),
            "--task-inventory",
            str(self.artifacts / "task-inventory.jsonl"),
            "--read-attributions",
            str(self.artifacts / "read-attributions.jsonl"),
            "--effect-judgments",
            str(self.artifacts / "effect-judgments.jsonl"),
            "--evidence-output",
            str(self.artifacts / "tampered-evidence.jsonl"),
            "--report-output",
            str(self.artifacts / "tampered-REPORT.md"),
            "--generated-at",
            NOW,
        )
        self.assertEqual(2, tampered_result.returncode)
        self.assertIn("digest does not match", tampered_result.stderr)
        write_jsonl(self.artifacts / "task-inventory.jsonl", frozen_rows)

        leaked_draft = json.loads(json.dumps(frozen_rows))
        for row in leaked_draft:
            row.pop("inventory_sha256")
        leaked_draft[0]["read"] = {
            "status": "observed",
            "read_ids": [read_id],
        }
        write_jsonl(
            self.artifacts / "leaked-task-inventory-draft.jsonl",
            leaked_draft,
        )
        leaked_result = run_cli(
            "freeze-tasks",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--task-source",
            str(self.artifacts / "task-source.jsonl"),
            "--task-inventory-draft",
            str(self.artifacts / "leaked-task-inventory-draft.jsonl"),
            "--task-inventory-output",
            str(self.artifacts / "leaked-task-inventory.jsonl"),
        )
        self.assertEqual(2, leaked_result.returncode)
        self.assertIn("pure Task inventory", leaked_result.stderr)

        unknown_draft = json.loads(json.dumps(leaked_draft))
        unknown_draft[0].pop("read")
        unknown_draft[0]["tree_passage"] = "derived content"
        write_jsonl(
            self.artifacts / "unknown-task-inventory-draft.jsonl",
            unknown_draft,
        )
        unknown_task_result = run_cli(
            "freeze-tasks",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--task-source",
            str(self.artifacts / "task-source.jsonl"),
            "--task-inventory-draft",
            str(self.artifacts / "unknown-task-inventory-draft.jsonl"),
            "--task-inventory-output",
            str(self.artifacts / "unknown-task-inventory.jsonl"),
        )
        self.assertEqual(2, unknown_task_result.returncode)
        self.assertIn("unsupported field", unknown_task_result.stderr)

        duplicate_choice = json.loads(json.dumps(task))
        duplicate_choice["effects"][1]["choice_message_ids"] = [
            second_choice_id
        ]
        rejected = self.report(
            [duplicate_choice],
            evidence_name="duplicate-effect-evidence.jsonl",
            report_name="duplicate-effect-REPORT.md",
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("reused across independent Effects", rejected.stderr)
        write_jsonl(
            self.artifacts / "read-attributions.jsonl",
            valid_read_rows,
        )
        write_jsonl(
            self.artifacts / "effect-judgments.jsonl",
            valid_effect_rows,
        )

        read_rows = json.loads(json.dumps(valid_read_rows))
        read_rows[0]["inventory_sha256"] = "0" * 64
        write_jsonl(self.artifacts / "read-attributions.jsonl", read_rows)
        digest_rejected = run_cli(
            "report",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--candidates",
            str(self.artifacts / "candidates.jsonl"),
            "--task-inventory",
            str(self.artifacts / "task-inventory.jsonl"),
            "--read-attributions",
            str(self.artifacts / "read-attributions.jsonl"),
            "--effect-judgments",
            str(self.artifacts / "effect-judgments.jsonl"),
            "--evidence-output",
            str(self.artifacts / "digest-evidence.jsonl"),
            "--report-output",
            str(self.artifacts / "digest-REPORT.md"),
            "--generated-at",
            NOW,
        )
        self.assertEqual(2, digest_rejected.returncode)
        self.assertIn("frozen Task inventory", digest_rejected.stderr)
        write_jsonl(
            self.artifacts / "read-attributions.jsonl",
            valid_read_rows,
        )

        effect_rows = json.loads(json.dumps(valid_effect_rows))
        effect_rows[0]["inventory_sha256"] = "0" * 64
        write_jsonl(self.artifacts / "effect-judgments.jsonl", effect_rows)
        effect_digest_rejected = run_cli(
            "report",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--candidates",
            str(self.artifacts / "candidates.jsonl"),
            "--task-inventory",
            str(self.artifacts / "task-inventory.jsonl"),
            "--read-attributions",
            str(self.artifacts / "read-attributions.jsonl"),
            "--effect-judgments",
            str(self.artifacts / "effect-judgments.jsonl"),
            "--evidence-output",
            str(self.artifacts / "effect-digest-evidence.jsonl"),
            "--report-output",
            str(self.artifacts / "effect-digest-REPORT.md"),
            "--generated-at",
            NOW,
        )
        self.assertEqual(2, effect_digest_rejected.returncode)
        self.assertIn(
            "frozen Task inventory",
            effect_digest_rejected.stderr,
        )
        write_jsonl(
            self.artifacts / "effect-judgments.jsonl",
            valid_effect_rows,
        )

        unknown_read_rows = json.loads(json.dumps(valid_read_rows))
        unknown_read_rows[0]["tree_passage"] = "derived content"
        write_jsonl(
            self.artifacts / "read-attributions.jsonl",
            unknown_read_rows,
        )
        unknown_read_result = run_cli(
            "report",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--candidates",
            str(self.artifacts / "candidates.jsonl"),
            "--task-inventory",
            str(self.artifacts / "task-inventory.jsonl"),
            "--read-attributions",
            str(self.artifacts / "read-attributions.jsonl"),
            "--effect-judgments",
            str(self.artifacts / "effect-judgments.jsonl"),
            "--evidence-output",
            str(self.artifacts / "unknown-read-evidence.jsonl"),
            "--report-output",
            str(self.artifacts / "unknown-read-REPORT.md"),
            "--generated-at",
            NOW,
        )
        self.assertEqual(2, unknown_read_result.returncode)
        self.assertIn("unsupported field", unknown_read_result.stderr)
        write_jsonl(
            self.artifacts / "read-attributions.jsonl",
            valid_read_rows,
        )

        unknown_effect_rows = json.loads(json.dumps(valid_effect_rows))
        unknown_effect_rows[0]["effect_claim"] = "derived content"
        write_jsonl(
            self.artifacts / "effect-judgments.jsonl",
            unknown_effect_rows,
        )
        unknown_effect_result = run_cli(
            "report",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--candidates",
            str(self.artifacts / "candidates.jsonl"),
            "--task-inventory",
            str(self.artifacts / "task-inventory.jsonl"),
            "--read-attributions",
            str(self.artifacts / "read-attributions.jsonl"),
            "--effect-judgments",
            str(self.artifacts / "effect-judgments.jsonl"),
            "--evidence-output",
            str(self.artifacts / "unknown-effect-evidence.jsonl"),
            "--report-output",
            str(self.artifacts / "unknown-effect-REPORT.md"),
            "--generated-at",
            NOW,
        )
        self.assertEqual(2, unknown_effect_result.returncode)
        self.assertIn("unsupported field", unknown_effect_result.stderr)

    def test_report_handles_excluded_task(
        self,
    ) -> None:
        self.write_chat_export()
        self.write_trace_fixtures()
        collected = self.collect("candidates.jsonl")
        self.assertEqual(0, collected.returncode, collected.stderr)
        candidate = read_jsonl(self.artifacts / "candidates.jsonl")[0]
        excluded = {
            "schema_version": 4,
            "task_id": "excluded-1",
            "status": "excluded",
            "objective": None,
            "object_scope": "unknown",
            "outcome": None,
            "started_at": "2026-07-22T10:00:00Z",
            "ended_at": "2026-07-22T10:06:00Z",
            "source_fragments": [
                {
                    "audit_id": candidate["audit_id"],
                    "message_ids": [MESSAGE_ID],
                }
            ],
            "exclusion_kind": "missing_objective",
            "exclusion_reason": "No clear objective and outcome boundary.",
        }
        result = self.report(
            [excluded],
            evidence_name="minimal-outside-evidence.jsonl",
            report_name="minimal-outside-REPORT.md",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        report = (self.artifacts / "minimal-outside-REPORT.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("| Excluded Tasks | 1 |", report)
        self.assertIn("## Excluded Tasks", report)
        self.assertIn("No clear objective and outcome boundary.", report)
        self.assertIn("## Frozen Task Inventory", report)
        self.assertIn("Inventory digest:", report)
        self.assertIn(
            "digest still binds the excluded-candidate inventory",
            report,
        )

        for legacy_field, legacy_value in (
            ("task_type", "solution_design"),
            ("sampling_order", 1),
            ("saturation_signals", []),
        ):
            legacy = json.loads(json.dumps(excluded))
            legacy[legacy_field] = legacy_value
            rejected = self.report(
                [legacy],
                evidence_name=f"excluded-legacy-{legacy_field}-evidence.jsonl",
                report_name=f"excluded-legacy-{legacy_field}-REPORT.md",
            )
            self.assertEqual(2, rejected.returncode)
            self.assertIn("pure Task inventory", rejected.stderr)

    def test_one_chat_splits_into_two_tasks_and_duplicate_read_is_rejected(
        self,
    ) -> None:
        self.write_chat_export()
        self.write_trace_fixtures()
        collected = self.collect("candidates.jsonl")
        self.assertEqual(0, collected.returncode, collected.stderr)
        candidate = read_jsonl(self.artifacts / "candidates.jsonl")[0]
        candidate["visible_messages"].extend(
            [
                {
                    "message_id": SECOND_OBJECTIVE_MESSAGE_ID,
                    "created_at": "2026-07-22T10:05:10Z",
                    "sender_id": AGENT_ID,
                    "sender_kind": None,
                    "content": "I will explain a separate result.",
                },
                {
                    "message_id": SECOND_MESSAGE_ID,
                    "created_at": "2026-07-22T10:05:30Z",
                    "sender_id": AGENT_ID,
                    "sender_kind": None,
                    "content": "A separate task completed.",
                },
            ]
        )
        candidate["chat"]["message_count"] += 2
        write_jsonl(self.artifacts / "candidates.jsonl", [candidate])

        first_task = self.task_judgment(candidate)
        second_task = self.task_judgment(
            candidate,
            task_id="task-2",
            message_id=SECOND_MESSAGE_ID,
            objective_message_id=SECOND_OBJECTIVE_MESSAGE_ID,
            read_status="unresolved",
            read_ids=[],
            effect=None,
        )
        second_task["objective"] = "Explain a separate result"
        second_task["object_scope"] = "independent outcome"
        second_task["outcome"] = "Delivered the separate explanation."

        split = self.report(
            [first_task, second_task],
            evidence_name="minimal-split-evidence.jsonl",
            report_name="minimal-split-REPORT.md",
        )
        self.assertEqual(0, split.returncode, split.stderr)
        report = (self.artifacts / "minimal-split-REPORT.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("| Clear Tasks | 2 |", report)
        self.assertIn("| Read unresolved Tasks | 1 |", report)
        self.assertIn("| Observed Read without Effect | 0 |", report)

        unresolved_with_read = json.loads(json.dumps(second_task))
        unresolved_with_read["read"]["read_ids"] = [
            candidate["reads"][0]["read_id"]
        ]
        unresolved_result = self.report(
            [unresolved_with_read],
            evidence_name="minimal-unresolved-read-evidence.jsonl",
            report_name="minimal-unresolved-read-REPORT.md",
        )
        self.assertEqual(2, unresolved_result.returncode)
        self.assertIn("must not contain read_ids", unresolved_result.stderr)

        duplicate = self.task_judgment(
            candidate,
            task_id="task-2",
            message_id=SECOND_MESSAGE_ID,
            objective_message_id=SECOND_OBJECTIVE_MESSAGE_ID,
            read_ids=[candidate["reads"][0]["read_id"]],
            effect=None,
        )
        duplicate_result = self.report(
            [first_task, duplicate],
            evidence_name="minimal-duplicate-evidence.jsonl",
            report_name="minimal-duplicate-REPORT.md",
        )
        self.assertEqual(2, duplicate_result.returncode)
        self.assertIn("outside the Task window", duplicate_result.stderr)

    def test_task_inventory_sources_and_weak_fragments_are_enforced(
        self,
    ) -> None:
        self.write_chat_export()
        self.write_trace_fixtures()
        collected = self.collect("candidates.jsonl")
        self.assertEqual(0, collected.returncode, collected.stderr)
        candidate = read_jsonl(self.artifacts / "candidates.jsonl")[0]
        assignment_id = "assignment-message"
        continuation_id = "continuation-message"
        candidate["visible_messages"].extend(
            [
                {
                    "message_id": assignment_id,
                    "created_at": "2026-07-22T10:00:00Z",
                    "sender_id": OTHER_AGENT_ID,
                    "sender_kind": "human",
                    "content": (
                        "Choose the authoritative state source and deliver the "
                        "decision."
                    ),
                },
                {
                    "message_id": continuation_id,
                    "created_at": "2026-07-22T10:04:00Z",
                    "sender_id": OTHER_AGENT_ID,
                    "sender_kind": "human",
                    "content": "Please continue.",
                },
            ]
        )
        candidate["chat"]["message_count"] += 2
        write_jsonl(self.artifacts / "candidates.jsonl", [candidate])

        valid = self.task_judgment(candidate)
        valid["started_at"] = "2026-07-22T10:00:00Z"
        valid["source_fragments"][0]["message_ids"] = [
            assignment_id,
            ACCEPTANCE_MESSAGE_ID,
            continuation_id,
            MESSAGE_ID,
        ]
        valid["episode"]["objective_anchor_message_ids"] = [assignment_id]
        valid["episode"]["outcome_anchor_message_ids"] = [MESSAGE_ID]
        accepted = self.report(
            [valid],
            evidence_name="inventory-valid-evidence.jsonl",
            report_name="inventory-valid-REPORT.md",
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        report = (self.artifacts / "inventory-valid-REPORT.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("## Frozen Task Inventory", report)
        self.assertIn("Objective sources", report)
        self.assertIn("Primary deliverable", report)
        task_source = (
            self.artifacts / "task-source.jsonl"
        ).read_text(encoding="utf-8")
        self.assertNotIn("decision_receipt", task_source)
        self.assertNotIn('"reads"', task_source)

        weak_variants = (
            "please continue",
            "请继续",
            "修一下吧",
            "status please",
            "please continue fixing it",
            "please fix it",
            "continue the work",
            "proceed",
            "go ahead",
            "keep going",
            "carry on",
            "fix that",
            "继续修一下",
            "修这个",
            "“please continue”",
            "请继续（谢谢）",
            "@agent-one @agent-two，请继续",
        )
        for index, source_content in enumerate(weak_variants):
            weak_candidate = json.loads(json.dumps(candidate))
            next(
                message
                for message in weak_candidate["visible_messages"]
                if message["message_id"] == assignment_id
            )["content"] = source_content
            write_jsonl(self.artifacts / "candidates.jsonl", [weak_candidate])
            result = self.report(
                [valid],
                evidence_name=f"inventory-weak-{index}-evidence.jsonl",
                report_name=f"inventory-weak-{index}-REPORT.md",
            )
            self.assertEqual(2, result.returncode)
            self.assertIn("concrete objective-source", result.stderr)

        concrete_variants = (
            "Please continue the state-source design and deliver the decision.",
            "Proceed with the schema-v4 validator and deliver the PR.",
            "请继续完成状态源方案并交付独立决定",
            "@agent-one，请继续完成状态源方案并交付独立决定",
        )
        for index, source_content in enumerate(concrete_variants):
            concrete_candidate = json.loads(json.dumps(candidate))
            next(
                message
                for message in concrete_candidate["visible_messages"]
                if message["message_id"] == assignment_id
            )["content"] = source_content
            write_jsonl(
                self.artifacts / "candidates.jsonl",
                [concrete_candidate],
            )
            result = self.report(
                [valid],
                evidence_name=f"inventory-concrete-{index}-evidence.jsonl",
                report_name=f"inventory-concrete-{index}-REPORT.md",
            )
            self.assertEqual(0, result.returncode, result.stderr)

        write_jsonl(self.artifacts / "candidates.jsonl", [candidate])
        weak_objective = json.loads(json.dumps(valid))
        weak_objective["objective"] = "修一下吧"
        weak_result = self.report(
            [weak_objective],
            evidence_name="inventory-weak-objective-evidence.jsonl",
            report_name="inventory-weak-objective-REPORT.md",
        )
        self.assertEqual(2, weak_result.returncode)
        self.assertIn("only a continuation", weak_result.stderr)

        human_outcome_id = "human-outcome-message"
        mixed_outcome_candidate = json.loads(json.dumps(candidate))
        mixed_outcome_candidate["visible_messages"].append(
            {
                "message_id": human_outcome_id,
                "created_at": "2026-07-22T10:05:30Z",
                "sender_id": OTHER_AGENT_ID,
                "sender_kind": "human",
                "content": "Thanks, this delivery is complete.",
            }
        )
        mixed_outcome_candidate["chat"]["message_count"] += 1
        write_jsonl(
            self.artifacts / "candidates.jsonl",
            [mixed_outcome_candidate],
        )
        mixed_outcome = json.loads(json.dumps(valid))
        mixed_outcome["ended_at"] = "2026-07-22T10:05:30Z"
        mixed_outcome["source_fragments"][0]["message_ids"].append(
            human_outcome_id
        )
        mixed_outcome["episode"]["outcome_anchor_message_ids"] = [
            human_outcome_id
        ]
        mixed_result = self.report(
            [mixed_outcome],
            evidence_name="inventory-human-outcome-evidence.jsonl",
            report_name="inventory-human-outcome-REPORT.md",
        )
        self.assertEqual(2, mixed_result.returncode)
        self.assertIn("every outcome source", mixed_result.stderr)

        missing_sources = json.loads(json.dumps(valid))
        missing_sources.pop("episode")
        missing_result = self.report(
            [missing_sources],
            evidence_name="inventory-missing-sources-evidence.jsonl",
            report_name="inventory-missing-sources-REPORT.md",
        )
        self.assertEqual(2, missing_result.returncode)
        self.assertIn("objective_source_message_ids", missing_result.stderr)

        schema_v3 = json.loads(json.dumps(valid))
        schema_v3["schema_version"] = 3
        schema_result = self.report(
            [schema_v3],
            evidence_name="inventory-schema-v3-evidence.jsonl",
            report_name="inventory-schema-v3-REPORT.md",
        )
        self.assertEqual(2, schema_result.returncode)
        self.assertIn("schema_version 4", schema_result.stderr)

        collapsed = self.task_judgment(
            candidate,
            message_id=ACCEPTANCE_MESSAGE_ID,
            objective_message_id=ACCEPTANCE_MESSAGE_ID,
            read_status="unresolved",
            read_ids=[],
            effect=None,
        )
        collapsed_result = self.report(
            [collapsed],
            evidence_name="inventory-collapsed-evidence.jsonl",
            report_name="inventory-collapsed-REPORT.md",
        )
        self.assertEqual(2, collapsed_result.returncode)
        self.assertIn("must be separate", collapsed_result.stderr)

        early_outcome_id = "early-outcome-message"
        early_candidate = json.loads(json.dumps(candidate))
        early_candidate["visible_messages"].append(
            {
                "message_id": early_outcome_id,
                "created_at": "2026-07-22T10:01:30Z",
                "sender_id": AGENT_ID,
                "sender_kind": "agent",
                "content": "An early intermediate state was recorded.",
            }
        )
        early_candidate["chat"]["message_count"] += 1
        write_jsonl(self.artifacts / "candidates.jsonl", [early_candidate])
        early_effect = json.loads(json.dumps(valid))
        early_effect["source_fragments"][0]["message_ids"].insert(
            -1, early_outcome_id
        )
        early_effect["effect"]["outcome_anchor"] = early_outcome_id
        early_result = self.report(
            [early_effect],
            evidence_name="effect-early-outcome-evidence.jsonl",
            report_name="effect-early-outcome-REPORT.md",
        )
        self.assertEqual(2, early_result.returncode)
        self.assertIn("outcome precedes", early_result.stderr)

    def test_task_source_ignores_malformed_derived_evidence(self) -> None:
        self.write_chat_export()
        self.write_trace_fixtures()
        collected = self.collect("candidates.jsonl")
        self.assertEqual(0, collected.returncode, collected.stderr)
        candidate = read_jsonl(self.artifacts / "candidates.jsonl")[0]

        baseline_result = run_cli(
            "task-source",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--candidates",
            str(self.artifacts / "candidates.jsonl"),
            "--output",
            str(self.artifacts / "task-source-baseline.jsonl"),
        )
        self.assertEqual(0, baseline_result.returncode, baseline_result.stderr)
        baseline = (
            self.artifacts / "task-source-baseline.jsonl"
        ).read_bytes()
        inventory = self.task_judgment(candidate)

        candidate["collector_diagnostics"] = "malformed"
        candidate["tree_source_snapshot"] = {"status": "future-invalid"}
        candidate["reads"] = [{"malformed": True}]
        candidate["visible_choice_candidates"] = [{"malformed": True}]
        candidate["visible_tree_mentions"] = "malformed"
        candidate["visible_messages"][0]["decision_receipt"] = {
            "future": "invalid"
        }
        write_jsonl(
            self.artifacts / "derived-damage-candidates.jsonl",
            [candidate],
        )
        damaged_result = run_cli(
            "task-source",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--candidates",
            str(self.artifacts / "derived-damage-candidates.jsonl"),
            "--output",
            str(self.artifacts / "task-source-derived-damage.jsonl"),
        )
        self.assertEqual(0, damaged_result.returncode, damaged_result.stderr)
        self.assertEqual(
            baseline,
            (self.artifacts / "task-source-derived-damage.jsonl").read_bytes(),
        )

        task_source = read_jsonl(
            self.artifacts / "task-source-derived-damage.jsonl"
        )
        task_source[0]["reads"] = []
        write_jsonl(
            self.artifacts / "task-source-with-derived-field.jsonl",
            task_source,
        )
        inventory.pop("read")
        inventory.pop("effect")
        inventory.pop("effect_reason")
        episode = inventory.pop("episode")
        inventory["objective_source_message_ids"] = episode[
            "objective_anchor_message_ids"
        ]
        inventory["outcome_source_message_ids"] = episode[
            "outcome_anchor_message_ids"
        ]
        inventory["primary_deliverable"] = episode["primary_deliverable"]
        write_jsonl(
            self.artifacts / "stage-one-inventory-draft.jsonl",
            [inventory],
        )
        rejected = run_cli(
            "freeze-tasks",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--task-source",
            str(self.artifacts / "task-source-with-derived-field.jsonl"),
            "--task-inventory-draft",
            str(self.artifacts / "stage-one-inventory-draft.jsonl"),
            "--task-inventory-output",
            str(self.artifacts / "stage-one-inventory.jsonl"),
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("unsupported field", rejected.stderr)

    def test_cross_chat_task_requires_explicit_linkage(self) -> None:
        self.write_chat_export()
        self.write_trace_fixtures()
        collected = self.collect("candidates.jsonl")
        self.assertEqual(0, collected.returncode, collected.stderr)
        first = read_jsonl(self.artifacts / "candidates.jsonl")[0]
        second = json.loads(json.dumps(first))
        second["audit_id"] = f"{SECOND_CHAT_ID}@{AGENT_ID}"
        second["chat"]["chat_id"] = SECOND_CHAT_ID
        second["chat"]["title"] = "Follow-up Chat"
        second["mapped_trace_files"] = []
        second["reads"] = []
        second["visible_messages"] = [
            {
                "message_id": SECOND_MESSAGE_ID,
                "created_at": "2026-07-22T10:05:30Z",
                "sender_id": AGENT_ID,
                "sender_kind": None,
                "content": "Follow-up delivery for the same objective.",
            }
        ]
        second["visible_choice_candidates"] = []
        second["visible_tree_mentions"] = []
        second["chat"]["message_count"] = 1
        write_jsonl(self.artifacts / "candidates.jsonl", [first, second])

        task = self.task_judgment(first)
        task["source_fragments"].append(
            {
                "audit_id": second["audit_id"],
                "message_ids": [SECOND_MESSAGE_ID],
            }
        )
        task["episode"]["outcome_anchor_message_ids"].append(
            SECOND_MESSAGE_ID
        )
        task["ended_at"] = "2026-07-22T10:05:30Z"
        no_linkage = self.report(
            [task],
            evidence_name="no-linkage-evidence.jsonl",
            report_name="no-linkage-REPORT.md",
        )
        self.assertEqual(2, no_linkage.returncode)
        self.assertIn("requires one explicit shared linkage", no_linkage.stderr)

        linkage = {
            "kind": "same_objective_delivery",
            "key": "deliver-one-state-source",
        }
        for fragment in task["source_fragments"]:
            fragment["linkage"] = linkage
        linked = self.report(
            [task],
            evidence_name="linked-evidence.jsonl",
            report_name="linked-REPORT.md",
        )
        self.assertEqual(0, linked.returncode, linked.stderr)

    def test_every_available_task_reports_without_a_sampling_gate(self) -> None:
        self.write_chat_export()
        self.write_trace_fixtures()
        collected = self.collect("candidates.jsonl")
        self.assertEqual(0, collected.returncode, collected.stderr)
        candidate = read_jsonl(self.artifacts / "candidates.jsonl")[0]
        candidate["candidate_status"] = "outside_candidate_set"
        candidate["mapped_trace_files"] = []
        candidate["reads"] = []
        candidate["visible_choice_candidates"] = []
        candidate["visible_tree_mentions"] = []
        candidate["visible_messages"] = [
            message
            for index in range(1, 45)
            for message in (
                {
                    "message_id": f"sample-objective-{index:03d}",
                    "created_at": "2026-07-22T10:04:00Z",
                    "sender_id": AGENT_ID,
                    "sender_kind": None,
                    "content": f"I will complete sample task {index}.",
                },
                {
                    "message_id": f"sample-message-{index:03d}",
                    "created_at": "2026-07-22T10:05:00Z",
                    "sender_id": AGENT_ID,
                    "sender_kind": None,
                    "content": f"Sample task {index} completed.",
                },
            )
        ]
        candidate["chat"]["message_count"] = 88
        write_jsonl(self.artifacts / "candidates.jsonl", [candidate])
        tasks = [
            self.task_judgment(
                candidate,
                task_id=f"sample-task-{index:03d}",
                message_id=f"sample-message-{index:03d}",
                objective_message_id=f"sample-objective-{index:03d}",
                read_status="unresolved",
                read_ids=[],
                effect=None,
            )
            for index in range(1, 45)
        ]

        for count in (1, 16, 44):
            result = self.report(
                tasks[:count],
                evidence_name=f"sample-{count}-evidence.jsonl",
                report_name=f"sample-{count}-REPORT.md",
            )
            self.assertEqual(0, result.returncode, result.stderr)
            report = (self.artifacts / f"sample-{count}-REPORT.md").read_text(
                encoding="utf-8"
            )
            self.assertIn(f"| Clear Tasks | {count} |", report)
            self.assertIn(f"| Read unresolved Tasks | {count} |", report)
            self.assertIn("| Observed Read without Effect | 0 |", report)
            self.assertIn("There is no minimum Task quota", report)
            self.assertNotIn("Effect saturation", report)
            self.assertNotIn("Status: `saturated`", report)
            self.assertNotIn("task type", report.lower())

        write_jsonl(
            self.artifacts / "reviewed-baseline.jsonl",
            [
                {
                    "schema_version": 4,
                    "basis": "separately_reviewed_task_cases",
                    "reviewed_at": "2026-07-22T12:00:00Z",
                    "evidence_anchor": {
                        "artifact_id": "reviewed-task-cases-v2",
                        "sha256": "a" * 64,
                    },
                    "clear_tasks": 44,
                    "effect_tasks": 16,
                    "effects": 16,
                    "effect_counts": {
                        "confirmed": 2,
                        "constrained": 8,
                        "redirected": 5,
                        "conflicted": 1,
                    },
                }
            ],
        )
        baseline = self.report(
            tasks[:16],
            evidence_name="minimal-baseline-evidence.jsonl",
            report_name="minimal-baseline-REPORT.md",
            reviewed_baseline_name="reviewed-baseline.jsonl",
        )
        self.assertEqual(0, baseline.returncode, baseline.stderr)
        baseline_report = (
            self.artifacts / "minimal-baseline-REPORT.md"
        ).read_text(encoding="utf-8")
        self.assertIn("## Separately Reviewed Historical Baseline", baseline_report)
        self.assertIn("| Reviewed effect Tasks | 16 |", baseline_report)
        self.assertNotIn("Derived support", baseline_report)
        self.assertNotIn("support_counts", baseline_report)

        write_jsonl(
            self.artifacts / "zero-effect-baseline.jsonl",
            [
                {
                    "schema_version": 4,
                    "basis": "separately_reviewed_task_cases",
                    "reviewed_at": "2026-07-22T12:00:00Z",
                    "evidence_anchor": {
                        "artifact_id": "reviewed-zero-effect-cases",
                        "sha256": "b" * 64,
                    },
                    "clear_tasks": 5,
                    "effect_tasks": 0,
                    "effects": 0,
                    "effect_counts": {
                        "confirmed": 0,
                        "constrained": 0,
                        "redirected": 0,
                        "conflicted": 0,
                    },
                }
            ],
        )
        zero_baseline = self.report(
            tasks[:1],
            evidence_name="zero-baseline-evidence.jsonl",
            report_name="zero-baseline-REPORT.md",
            reviewed_baseline_name="zero-effect-baseline.jsonl",
        )
        self.assertEqual(0, zero_baseline.returncode, zero_baseline.stderr)
        zero_report = (
            self.artifacts / "zero-baseline-REPORT.md"
        ).read_text(encoding="utf-8")
        self.assertIn("| Reviewed effect Tasks | 0 |", zero_report)
        self.assertIn("| Reviewed Effects | 0 |", zero_report)

        for legacy_field, legacy_value in (
            ("task_type", "solution_design"),
            ("sampling_order", 1),
            ("saturation_signals", []),
        ):
            legacy = json.loads(json.dumps(tasks[0]))
            legacy[legacy_field] = legacy_value
            rejected = self.report(
                [legacy],
                evidence_name=f"legacy-{legacy_field}-evidence.jsonl",
                report_name=f"legacy-{legacy_field}-REPORT.md",
            )
            self.assertEqual(2, rejected.returncode)
            self.assertIn("pure Task inventory", rejected.stderr)

    def test_symlinked_artifact_output_is_rejected(self) -> None:
        self.write_chat_export()
        outside = self.root / "outside.jsonl"
        outside.write_text("preserve", encoding="utf-8")
        linked = self.artifacts / "linked.jsonl"
        linked.symlink_to(outside)
        result = self.collect("linked.jsonl")
        self.assertEqual(2, result.returncode)
        self.assertIn("symbolic link", result.stderr)
        self.assertEqual("preserve", outside.read_text(encoding="utf-8"))

    def test_artifact_root_must_be_strictly_inside_workspace_without_symlinks(self) -> None:
        scope = {
            "schema_version": 1,
            "agents": [],
            "chats": [
                {
                    "chat_id": CHAT_ID,
                    "agent": "fixture-agent",
                    "agent_id": AGENT_ID,
                    "authorization": "explicit_chat",
                }
            ],
        }
        scope_path = self.artifacts / "scope.json"
        write_json(scope_path, scope)
        binary, _ = self.make_fake_first_tree()

        def export_with_root(artifact_root: Path) -> subprocess.CompletedProcess[str]:
            return run_cli(
                "export-chats",
                "--artifact-root",
                str(artifact_root),
                "--scope",
                str(scope_path),
                "--agent-workspace",
                f"{AGENT_ID}={self.workspace}",
                "--first-tree-bin",
                str(binary),
                "--now",
                NOW,
                "--output",
                str(artifact_root / "chats.jsonl"),
            )

        outside = self.root / "outside-artifacts"
        outside_result = export_with_root(outside)
        self.assertEqual(2, outside_result.returncode)
        self.assertIn("strict descendant", outside_result.stderr)
        self.assertFalse(outside.exists())

        workspace_result = export_with_root(self.workspace)
        self.assertEqual(2, workspace_result.returncode)
        self.assertIn("dedicated directory", workspace_result.stderr)

        real_parent = self.workspace / "real-artifacts"
        real_parent.mkdir()
        linked_parent = self.workspace / "linked-artifacts"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        linked_result = export_with_root(linked_parent / "audit")
        self.assertEqual(2, linked_result.returncode)
        self.assertIn("traverse a symbolic link", linked_result.stderr)
        self.assertFalse((real_parent / "audit").exists())

    def test_read_grammar_conserves_safe_unresolved_and_unsafe_attempts(self) -> None:
        self.write_chat_export()
        for filename, tool_name, arguments, sentinel in (
            (
                "stdin.jsonl",
                "exec_command",
                {"cmd": f"cat {self.tree_file} -", "workdir": str(self.workspace)},
                "stdin-mixed-sentinel",
            ),
            (
                "lookalike.jsonl",
                "mcp__untrusted__read_file",
                {"path": str(self.tree_file)},
                "lookalike-mixed-sentinel",
            ),
            (
                "semicolon.jsonl",
                "exec_command",
                {
                    "cmd": (
                        f"cat {self.tree_file}; "
                        "printf semicolon-mixed-sentinel"
                    ),
                    "workdir": str(self.workspace),
                },
                "semicolon-mixed-sentinel",
            ),
            (
                "pipe.jsonl",
                "exec_command",
                {
                    "cmd": f"cat {self.tree_file} | head",
                    "workdir": str(self.workspace),
                },
                "pipe-mixed-sentinel",
            ),
            (
                "mutating-find.jsonl",
                "exec_command",
                {
                    "cmd": (
                        f"cat {self.tree_file} && "
                        f"find {self.tree_root} -delete"
                    ),
                    "workdir": str(self.workspace),
                },
                "mutating-find-sentinel",
            ),
            (
                "mutating-git.jsonl",
                "exec_command",
                {
                    "cmd": (
                        f"cat {self.tree_file} && "
                        f"git -C {self.tree_root} branch -D temporary"
                    ),
                    "workdir": str(self.workspace),
                },
                "mutating-git-sentinel",
            ),
        ):
            call_id = f"call-{filename}"
            write_jsonl(
                self.trace_root / filename,
                [
                    session_meta(self.workspace),
                    context_row(CHAT_ID),
                    {
                        "timestamp": "2026-07-22T10:02:00Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": tool_name,
                            "call_id": call_id,
                            "arguments": json.dumps(arguments),
                        },
                    },
                    {
                        "timestamp": "2026-07-22T10:02:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": (
                                "Process exited with code 0\n"
                                "# Architecture\n\n"
                                "Chat history is the authoritative state.\n"
                                + (
                                    sentinel
                                    if filename == "semicolon.jsonl"
                                    else ""
                                )
                            ),
                        },
                    },
                ],
            )

        write_jsonl(
            self.trace_root / "outside-window-unsafe.jsonl",
            [
                session_meta(self.workspace),
                context_row(CHAT_ID),
                {
                    "timestamp": "2026-07-16T10:02:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "call-outside-window-unsafe",
                        "arguments": json.dumps(
                            {
                                "cmd": f"rm {self.tree_file}",
                                "workdir": str(self.workspace),
                            }
                        ),
                    },
                },
                {
                    "timestamp": "2026-07-16T10:02:01Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-outside-window-unsafe",
                        "output": "Process exited with code 0\noutside-window-sentinel",
                    },
                },
            ],
        )

        result = self.collect("rejected-reads.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(self.artifacts / "rejected-reads.jsonl")[0]
        self.assertEqual(2, len(candidate["reads"]))
        self.assertTrue(
            all(read["read_mode"] == "read_only_composite" for read in candidate["reads"])
        )
        self.assertIn("unresolved_stdin_tree_read", candidate["coverage_gaps"])
        self.assertIn("unresolved_tree_read_tool", candidate["coverage_gaps"])
        self.assertIn("unsafe_find_action", candidate["coverage_gaps"])
        self.assertIn("unsafe_git_mutation", candidate["coverage_gaps"])
        self.assertNotIn("unsafe_program_rm", candidate["coverage_gaps"])
        self.assertEqual(
            {
                "accepted_exact": 0,
                "accepted_read_only_composite": 2,
                "unresolved_opaque": 2,
                "rejected_unsafe": 2,
            },
            candidate["collector_diagnostics"]["attempt_status_counts"],
        )
        self.assertEqual(
            6,
            candidate["collector_diagnostics"]["in_window_tree_read_attempts"],
        )
        serialized = json.dumps(candidate, sort_keys=True)
        for sentinel in ("semicolon-mixed-sentinel", "pipe-mixed-sentinel"):
            self.assertNotIn(sentinel, serialized)
        for sentinel in (
            "stdin-mixed-sentinel",
            "lookalike-mixed-sentinel",
            "mutating-find-sentinel",
            "mutating-git-sentinel",
            "outside-window-sentinel",
        ):
            self.assertNotIn(sentinel, serialized)


if __name__ == "__main__":
    unittest.main()
