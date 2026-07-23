from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "context-tree-insights"
SCRIPT = SKILL_ROOT / "scripts" / "context_tree_insights.py"
AGENT_ID = "55555555-5555-4555-8555-555555555555"
OTHER_AGENT_ID = "99999999-9999-4999-8999-999999999999"
CHAT_ID = "11111111-1111-4111-8111-111111111111"
UNAUTHORIZED_CHAT_ID = "88888888-8888-4888-8888-888888888888"
MESSAGE_ID = "33333333-3333-4333-8333-333333333333"
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


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True,
        check=False,
        text=True,
    )


def write_workspace_identity(workspace: Path, tree_root: Path, agent_id: str = AGENT_ID) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    write_json(
        workspace / ".first-tree-workspace" / "identity.json",
        {
            "agentId": agent_id,
            "displayName": "fixture-agent",
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


class RepositoryContractTests(unittest.TestCase):
    def test_skill_is_an_explicit_only_umbrella(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        openai = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        reference = (SKILL_ROOT / "references" / "evidence-schema.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("name: context-tree-insights", skill)
        self.assertIn("$context-tree-insights", skill)
        self.assertIn("manual and read-only", skill)
        self.assertIn("Do not trigger from an ordinary task", skill)
        self.assertIn("all authorized Chats are not an eligible", skill)
        self.assertIn("allow_implicit_invocation: false", openai)
        self.assertIn("explicit_agent", reference)
        self.assertIn("explicit_chat", reference)
        self.assertNotIn("/Users/", "\n".join((skill, openai, reference)))


class DeterministicPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="context-tree-insights-")
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
        write_workspace_identity(self.workspace, self.tree_root)
        self.trace_root = self.root / "sessions"
        self.trace_root.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_fake_first_tree(self) -> tuple[Path, Path]:
        binary = self.root / "fake-first-tree"
        log = self.root / "first-tree-commands.log"
        source = f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

args = sys.argv[1:]
with Path({str(log)!r}).open("a", encoding="utf-8") as handle:
    handle.write(" ".join(args) + "\\n")

if "agent" in args:
    print(json.dumps({{"ok": False, "error": "agent list must not be called"}}))
    raise SystemExit(9)
if "chat" in args and "list" in args:
    data = {{
        "items": [{{
            "id": {CHAT_ID!r},
            "topic": "Fixture Chat",
            "lastMessageAt": "2026-07-22T10:05:00Z"
        }}],
        "nextCursor": None
    }}
elif "chat" in args and "history" in args:
    data = {{
        "items": [{{
            "id": {MESSAGE_ID!r},
            "createdAt": "2026-07-22T10:05:00Z",
            "senderId": {AGENT_ID!r},
            "content": "The Context Tree constraint keeps one authoritative state source."
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

    def export_scope(self, scope: dict[str, Any], output_name: str = "chats.jsonl") -> subprocess.CompletedProcess[str]:
        scope_path = self.artifacts / "scope.json"
        output_path = self.artifacts / output_name
        write_json(scope_path, scope)
        binary, _ = self.make_fake_first_tree()
        return run_cli(
            "export-chats",
            "--artifact-root",
            str(self.artifacts),
            "--scope",
            str(scope_path),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--first-tree-bin",
            str(binary),
            "--days",
            "7",
            "--now",
            NOW,
            "--output",
            str(output_path),
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

    def test_exact_chat_export_never_calls_agent_list_and_is_private(self) -> None:
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
        self.assertIn(f"chat history {CHAT_ID}", commands)
        self.assertNotIn("chat list", commands)
        self.assertNotIn("agent list", commands)
        self.assertEqual(0o700, stat.S_IMODE(self.artifacts.stat().st_mode))
        self.assertEqual(
            0o600,
            stat.S_IMODE((self.artifacts / "chats.jsonl").stat().st_mode),
        )

    def test_explicit_agent_export_uses_chat_list_without_agent_enumeration(self) -> None:
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
        commands = (self.root / "first-tree-commands.log").read_text(encoding="utf-8")
        self.assertIn("chat list", commands)
        self.assertNotIn("agent list", commands)

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
                            "message_id": MESSAGE_ID,
                            "created_at": "2026-07-22T10:05:00Z",
                            "sender_id": AGENT_ID,
                            "content": (
                                "The Context Tree requires one authoritative state "
                                "source, so I will not add a second table."
                            ),
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

    def test_collect_prefilters_trace_and_isolates_single_tree_reads(self) -> None:
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
        self.assertEqual(1, len(candidate["reads"]))
        read = candidate["reads"][0]
        self.assertEqual(["system/architecture.md"], read["node_paths"])
        self.assertEqual(candidate["tree_identity"], read["tree_identity"])
        self.assertIn("authoritative state", read["passage"])
        self.assertTrue(all(item.startswith("trace-") for item in candidate["mapped_trace_files"]))
        self.assertIn("composite_shell_tree_read_rejected", candidate["coverage_gaps"])
        self.assertEqual([MESSAGE_ID], [
            message["message_id"] for message in candidate["visible_choice_candidates"]
        ])

        serialized = json.dumps(candidate, sort_keys=True)
        self.assertNotIn("private-unauthorized-sentinel", serialized)
        self.assertNotIn("mixed-output-sentinel", serialized)
        self.assertNotIn("outside-bound-tree-sentinel", serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertEqual(
            0o600,
            stat.S_IMODE((self.artifacts / "candidates-one.jsonl").stat().st_mode),
        )

    def test_report_is_deterministic_and_rejects_overstated_probable(self) -> None:
        self.write_chat_export()
        self.write_trace_fixtures()
        result = self.collect("candidates.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(self.artifacts / "candidates.jsonl")[0]
        read_id = candidate["reads"][0]["read_id"]
        judgments = self.artifacts / "judgments.jsonl"
        judgment = {
            "audit_id": f"{CHAT_ID}@{AGENT_ID}",
            "result": "verified",
            "effect": "constrained",
            "rubric": {
                "real_read": True,
                "decision_bearing_normal_passage": True,
                "task_relevant": True,
                "read_before_choice": True,
                "influence_visible": True,
            },
            "read_ids": [read_id],
            "choice_message_ids": [MESSAGE_ID],
            "decision_theme": "One authoritative state source",
            "summary": "The Tree constraint prevented a second state table.",
            "representative": True,
            "coverage_gaps": [],
        }
        write_jsonl(judgments, [judgment])

        def report(evidence: str, markdown: str) -> subprocess.CompletedProcess[str]:
            return run_cli(
                "report",
                "--artifact-root",
                str(self.artifacts),
                "--agent-workspace",
                f"{AGENT_ID}={self.workspace}",
                "--candidates",
                str(self.artifacts / "candidates.jsonl"),
                "--judgments",
                str(judgments),
                "--evidence-output",
                str(self.artifacts / evidence),
                "--report-output",
                str(self.artifacts / markdown),
                "--generated-at",
                NOW,
            )

        first = report("evidence-one.jsonl", "REPORT-one.md")
        second = report("evidence-two.jsonl", "REPORT-two.md")
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual(
            (self.artifacts / "evidence-one.jsonl").read_bytes(),
            (self.artifacts / "evidence-two.jsonl").read_bytes(),
        )
        self.assertEqual(
            (self.artifacts / "REPORT-one.md").read_bytes(),
            (self.artifacts / "REPORT-two.md").read_bytes(),
        )
        markdown = (self.artifacts / "REPORT-one.md").read_text(encoding="utf-8")
        self.assertIn("| verified | 1 |", markdown)
        self.assertIn("| constrained | 1 |", markdown)
        self.assertIn("not an eligible denominator", markdown)
        self.assertIn("not an effective-read rate", markdown)

        judgment["result"] = "probable"
        write_jsonl(judgments, [judgment])
        overstated = report("evidence-invalid.jsonl", "REPORT-invalid.md")
        self.assertEqual(2, overstated.returncode)
        self.assertIn("satisfies the verified bar", overstated.stderr)

        judgment["result"] = "verified"
        write_jsonl(judgments, [judgment])
        candidate["reads"][0]["completed_at"] = None
        write_jsonl(self.artifacts / "candidates.jsonl", [candidate])
        missing_completion = report(
            "evidence-missing-completion.jsonl",
            "REPORT-missing-completion.md",
        )
        self.assertEqual(2, missing_completion.returncode)
        self.assertIn("completion timestamps", missing_completion.stderr)

        candidate["reads"][0]["completed_at"] = "2026-07-22T10:02:01Z"
        candidate["tree_identity"] = "tree-tampered"
        write_jsonl(self.artifacts / "candidates.jsonl", [candidate])
        wrong_tree = report("evidence-wrong-tree.jsonl", "REPORT-wrong-tree.md")
        self.assertEqual(2, wrong_tree.returncode)
        self.assertIn("workspace-bound Tree", wrong_tree.stderr)

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

    def test_read_grammar_rejects_stdin_and_suffix_lookalikes(self) -> None:
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
                            "output": f"Process exited with code 0\n{sentinel}",
                        },
                    },
                ],
            )

        result = self.collect("rejected-reads.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(self.artifacts / "rejected-reads.jsonl")[0]
        self.assertEqual([], candidate["reads"])
        self.assertIn("stdin_tree_read_rejected", candidate["coverage_gaps"])
        self.assertIn("unsupported_tree_read_tool", candidate["coverage_gaps"])
        serialized = json.dumps(candidate, sort_keys=True)
        self.assertNotIn("stdin-mixed-sentinel", serialized)
        self.assertNotIn("lookalike-mixed-sentinel", serialized)


if __name__ == "__main__":
    unittest.main()
