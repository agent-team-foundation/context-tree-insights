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
SECOND_CHAT_ID = "22222222-2222-4222-8222-222222222222"
UNAUTHORIZED_CHAT_ID = "88888888-8888-4888-8888-888888888888"
MESSAGE_ID = "33333333-3333-4333-8333-333333333333"
SECOND_MESSAGE_ID = "44444444-4444-4444-8444-444444444444"
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
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        openai = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        reference = (SKILL_ROOT / "references" / "evidence-schema.md").read_text(
            encoding="utf-8"
        )
        task_reference = (
            SKILL_ROOT / "references" / "task-analysis-schema.md"
        ).read_text(encoding="utf-8")

        self.assertIn("name: context-tree-insights", skill)
        self.assertIn("$context-tree-insights", skill)
        self.assertIn("manual and read-only", skill)
        self.assertIn("Do not trigger from an ordinary task", skill)
        self.assertIn("all authorized Chats are not an eligible", skill)
        self.assertIn("allow_implicit_invocation: false", openai)
        self.assertIn("explicit_agent", reference)
        self.assertIn("explicit_chat", reference)
        for rubric_key in (
            "real_read",
            "decision_bearing_normal_passage",
            "task_relevant",
            "read_before_choice",
            "influence_visible",
        ):
            self.assertIn(rubric_key, task_reference)
        self.assertIn("all five checks are `true`", task_reference)
        self.assertIn("first four checks are `true`", task_reference)
        self.assertNotIn(
            "/Users/", "\n".join((skill, openai, reference, task_reference))
        )


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

    def make_fake_first_tree(
        self, message_metadata: dict[str, Any] | None = None
    ) -> tuple[Path, Path]:
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
    ) -> subprocess.CompletedProcess[str]:
        scope_path = self.artifacts / "scope.json"
        output_path = self.artifacts / output_name
        write_json(scope_path, scope)
        binary, _ = self.make_fake_first_tree(message_metadata)
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
        return run_cli(*arguments)

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

    def task_judgment(
        self,
        candidate: dict[str, Any],
        *,
        task_id: str = "task-1",
        message_id: str = MESSAGE_ID,
        sampling_order: int = 1,
        exposure_status: str = "confirmed",
        read_ids: list[str] | None = None,
        effects: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        selected_reads = (
            read_ids
            if read_ids is not None
            else [candidate["reads"][0]["read_id"]]
            if candidate["reads"]
            else []
        )
        if effects is None:
            effects = (
                [
                    {
                        "effect": "constrained",
                        "original_judgment": "verified",
                        "rubric": {
                            "real_read": True,
                            "decision_bearing_normal_passage": True,
                            "task_relevant": True,
                            "read_before_choice": True,
                            "influence_visible": True,
                        },
                        "read_ids": selected_reads,
                        "choice_message_ids": [message_id],
                        "outcome_anchor": message_id,
                        "summary": "The Tree constraint prevented a second state table.",
                    }
                ]
                if selected_reads and exposure_status == "confirmed"
                else []
            )
        return {
            "schema_version": 1,
            "task_id": task_id,
            "status": "clear",
            "objective": "Choose one state source",
            "object_scope": "state persistence",
            "outcome": "Kept the existing authoritative state source.",
            "task_type": "solution_design",
            "started_at": "2026-07-22T10:00:00Z",
            "ended_at": "2026-07-22T10:06:00Z",
            "source_fragments": [
                {
                    "audit_id": candidate["audit_id"],
                    "message_ids": [message_id],
                }
            ],
            "sampling_order": sampling_order,
            "saturation_signals": [],
            "exposure": {
                "status": exposure_status,
                "read_ids": selected_reads,
                "reason": (
                    "Historical trace coverage cannot confirm a read."
                    if exposure_status == "unresolved"
                    else None
                ),
            },
            "effects": effects,
        }

    def report(
        self,
        tasks: list[dict[str, Any]],
        *,
        candidates_name: str = "candidates.jsonl",
        evidence_name: str = "evidence.jsonl",
        report_name: str = "REPORT.md",
    ) -> subprocess.CompletedProcess[str]:
        task_path = self.artifacts / "task-judgments.jsonl"
        write_jsonl(task_path, tasks)
        return run_cli(
            "report",
            "--artifact-root",
            str(self.artifacts),
            "--agent-workspace",
            f"{AGENT_ID}={self.workspace}",
            "--candidates",
            str(self.artifacts / candidates_name),
            "--task-judgments",
            str(task_path),
            "--evidence-output",
            str(self.artifacts / evidence_name),
            "--report-output",
            str(self.artifacts / report_name),
            "--generated-at",
            NOW,
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
        result = self.collect("candidates.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        candidate = read_jsonl(self.artifacts / "candidates.jsonl")[0]
        task = self.task_judgment(candidate)

        first = self.report(
            [task],
            evidence_name="evidence-one.jsonl",
            report_name="REPORT-one.md",
        )
        second = self.report(
            [task],
            evidence_name="evidence-two.jsonl",
            report_name="REPORT-two.md",
        )
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
        self.assertIn("| Clear Tasks | 1 |", markdown)
        self.assertIn("| Confirmed exposure Tasks | 1 |", markdown)
        self.assertIn("| Independent effects | 1 |", markdown)
        self.assertIn("| constrained | 1 |", markdown)
        self.assertIn("definite **1**", markdown)
        self.assertIn("not a global effectiveness rate", markdown)
        evidence = read_jsonl(self.artifacts / "evidence-one.jsonl")
        self.assertEqual(
            "definite", evidence[0]["effects"][0]["derived_support"]
        )

        duplicate_task = json.loads(json.dumps(task))
        duplicate_task["effects"].append(
            json.loads(json.dumps(duplicate_task["effects"][0]))
        )
        deduplicated = self.report(
            [duplicate_task],
            evidence_name="deduplicated-evidence.jsonl",
            report_name="deduplicated-REPORT.md",
        )
        self.assertEqual(0, deduplicated.returncode, deduplicated.stderr)
        deduplicated_report = (
            self.artifacts / "deduplicated-REPORT.md"
        ).read_text(encoding="utf-8")
        self.assertIn("| Independent effects | 1 |", deduplicated_report)
        self.assertIn("| solution_design | 0 | 1 | 0 | 0 | 1 |", deduplicated_report)

        limited_task = json.loads(json.dumps(task))
        limited_task["effects"][0]["original_judgment"] = "probable"
        limited_task["effects"][0]["rubric"]["influence_visible"] = False
        limited = self.report(
            [limited_task],
            evidence_name="limited-evidence.jsonl",
            report_name="limited-REPORT.md",
        )
        self.assertEqual(0, limited.returncode, limited.stderr)
        self.assertEqual(
            "limited",
            read_jsonl(self.artifacts / "limited-evidence.jsonl")[0]["effects"][0][
                "derived_support"
            ],
        )

        missing_rubric_task = json.loads(json.dumps(task))
        missing_rubric_task["effects"][0].pop("rubric")
        missing_rubric = self.report(
            [missing_rubric_task],
            evidence_name="missing-rubric-evidence.jsonl",
            report_name="missing-rubric-REPORT.md",
        )
        self.assertEqual(2, missing_rubric.returncode)
        self.assertIn(".rubric must be an object", missing_rubric.stderr)

        overstated_probable_task = json.loads(json.dumps(task))
        overstated_probable_task["effects"][0]["original_judgment"] = "probable"
        overstated_probable = self.report(
            [overstated_probable_task],
            evidence_name="overstated-probable-evidence.jsonl",
            report_name="overstated-probable-REPORT.md",
        )
        self.assertEqual(2, overstated_probable.returncode)
        self.assertIn("influence_visible false or null", overstated_probable.stderr)

        task["effects"][0]["effect"] = "informed"
        invalid_effect = self.report(
            [task],
            evidence_name="evidence-invalid.jsonl",
            report_name="REPORT-invalid.md",
        )
        self.assertEqual(2, invalid_effect.returncode)
        self.assertIn(".effect must be one of", invalid_effect.stderr)

        task["effects"][0]["effect"] = "constrained"
        task["effects"][0].pop("outcome_anchor")
        missing_anchor = self.report(
            [task],
            evidence_name="evidence-missing-anchor.jsonl",
            report_name="REPORT-missing-anchor.md",
        )
        self.assertEqual(2, missing_anchor.returncode)
        self.assertIn("outcome_anchor", missing_anchor.stderr)

        task = self.task_judgment(candidate)
        candidate["reads"][0]["completed_at"] = "2026-07-22T10:02:01Z"
        candidate["tree_identity"] = "tree-tampered"
        write_jsonl(self.artifacts / "candidates.jsonl", [candidate])
        wrong_tree = self.report(
            [task],
            evidence_name="evidence-wrong-tree.jsonl",
            report_name="REPORT-wrong-tree.md",
        )
        self.assertEqual(2, wrong_tree.returncode)
        self.assertIn("workspace-bound Tree", wrong_tree.stderr)

    def test_report_handles_excluded_task_without_representative_case(
        self,
    ) -> None:
        self.write_chat_export()
        self.write_trace_fixtures()
        collected = self.collect("candidates.jsonl")
        self.assertEqual(0, collected.returncode, collected.stderr)
        candidate = read_jsonl(self.artifacts / "candidates.jsonl")[0]
        candidate["candidate_status"] = "outside_candidate_set"
        candidate["mapped_trace_files"] = []
        candidate["reads"] = []
        candidate["visible_tree_mentions"] = []
        write_jsonl(self.artifacts / "candidates.jsonl", [candidate])
        excluded = {
            "schema_version": 1,
            "task_id": "excluded-1",
            "status": "excluded",
            "objective": None,
            "object_scope": "unknown",
            "outcome": None,
            "task_type": None,
            "started_at": "2026-07-22T10:00:00Z",
            "ended_at": "2026-07-22T10:06:00Z",
            "source_fragments": [
                {
                    "audit_id": candidate["audit_id"],
                    "message_ids": [MESSAGE_ID],
                }
            ],
            "exclusion_reason": "No clear objective and outcome boundary.",
        }
        result = self.report(
            [excluded],
            evidence_name="outside-evidence.jsonl",
            report_name="outside-REPORT.md",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        report = (self.artifacts / "outside-REPORT.md").read_text(encoding="utf-8")
        self.assertIn("No representative effect Task was selected.", report)
        self.assertIn("| Excluded Tasks | 1 |", report)

    def test_one_chat_splits_into_two_tasks_and_duplicate_read_is_rejected(
        self,
    ) -> None:
        self.write_chat_export()
        self.write_trace_fixtures()
        collected = self.collect("candidates.jsonl")
        self.assertEqual(0, collected.returncode, collected.stderr)
        candidate = read_jsonl(self.artifacts / "candidates.jsonl")[0]
        second_message = {
            "message_id": SECOND_MESSAGE_ID,
            "created_at": "2026-07-22T10:05:30Z",
            "sender_id": AGENT_ID,
            "sender_kind": None,
            "content": "A separate coordination task completed.",
        }
        candidate["visible_messages"].append(second_message)
        candidate["chat"]["message_count"] += 1
        write_jsonl(self.artifacts / "candidates.jsonl", [candidate])

        first_task = self.task_judgment(candidate)
        second_task = self.task_judgment(
            candidate,
            task_id="task-2",
            message_id=SECOND_MESSAGE_ID,
            sampling_order=2,
            exposure_status="unresolved",
            read_ids=[],
            effects=[],
        )
        second_task["objective"] = "Coordinate delivery"
        second_task["object_scope"] = "handoff status"
        second_task["outcome"] = "Recorded a separate coordination outcome."
        second_task["task_type"] = "coordination_progress"

        split = self.report(
            [first_task, second_task],
            evidence_name="split-evidence.jsonl",
            report_name="split-REPORT.md",
        )
        self.assertEqual(0, split.returncode, split.stderr)
        report = (self.artifacts / "split-REPORT.md").read_text(encoding="utf-8")
        self.assertIn("| Clear Tasks | 2 |", report)
        self.assertIn("| Unresolved exposure Tasks | 1 |", report)
        self.assertIn(
            "Unresolved exposure is unknown coverage, not an unused/no-value denominator.",
            report,
        )

        unresolved_with_read = json.loads(json.dumps(second_task))
        unresolved_with_read["sampling_order"] = 1
        unresolved_with_read["exposure"]["read_ids"] = [
            candidate["reads"][0]["read_id"]
        ]
        unresolved_read_result = self.report(
            [unresolved_with_read],
            evidence_name="unresolved-read-evidence.jsonl",
            report_name="unresolved-read-REPORT.md",
        )
        self.assertEqual(2, unresolved_read_result.returncode)
        self.assertIn(
            "must not contain read_ids", unresolved_read_result.stderr
        )

        unresolved_with_effect = json.loads(json.dumps(second_task))
        unresolved_with_effect["sampling_order"] = 1
        unresolved_with_effect["effects"] = [
            json.loads(json.dumps(first_task["effects"][0]))
        ]
        unresolved_effect_result = self.report(
            [unresolved_with_effect],
            evidence_name="unresolved-effect-evidence.jsonl",
            report_name="unresolved-effect-REPORT.md",
        )
        self.assertEqual(2, unresolved_effect_result.returncode)
        self.assertIn(
            "must not contain effects", unresolved_effect_result.stderr
        )

        duplicated = self.task_judgment(
            candidate,
            task_id="task-2",
            message_id=SECOND_MESSAGE_ID,
            sampling_order=2,
            exposure_status="confirmed",
            read_ids=[candidate["reads"][0]["read_id"]],
            effects=[],
        )
        duplicate_result = self.report(
            [first_task, duplicated],
            evidence_name="duplicate-evidence.jsonl",
            report_name="duplicate-REPORT.md",
        )
        self.assertEqual(2, duplicate_result.returncode)
        self.assertIn("copied across incompatible Tasks", duplicate_result.stderr)

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

    def test_sampling_saturates_reproducibly_at_100_plus_20_plus_20(self) -> None:
        self.write_chat_export()
        self.write_trace_fixtures()
        collected = self.collect("candidates.jsonl")
        self.assertEqual(0, collected.returncode, collected.stderr)
        candidate = read_jsonl(self.artifacts / "candidates.jsonl")[0]
        source_candidate = json.loads(json.dumps(candidate))
        candidate["candidate_status"] = "outside_candidate_set"
        candidate["mapped_trace_files"] = []
        candidate["reads"] = []
        candidate["visible_choice_candidates"] = []
        candidate["visible_tree_mentions"] = []
        candidate["visible_messages"] = [
            {
                "message_id": f"sample-message-{index:03d}",
                "created_at": "2026-07-22T10:05:00Z",
                "sender_id": AGENT_ID,
                "sender_kind": None,
                "content": f"Sample task {index}",
            }
            for index in range(1, 141)
        ]
        candidate["chat"]["message_count"] = 140
        write_jsonl(self.artifacts / "candidates.jsonl", [candidate])
        tasks = [
            self.task_judgment(
                candidate,
                task_id=f"sample-task-{index:03d}",
                message_id=f"sample-message-{index:03d}",
                sampling_order=index,
                exposure_status="unresolved",
                read_ids=[],
                effects=[],
            )
            for index in range(1, 141)
        ]
        task_types = [
            "solution_design",
            "implementation_delivery",
            "review_qa_debugging",
            "research_explanation",
            "coordination_progress",
        ]
        for index, task in enumerate(tasks):
            task["task_type"] = task_types[index % len(task_types)]
        result = self.report(
            tasks,
            evidence_name="saturation-evidence.jsonl",
            report_name="saturation-REPORT.md",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        report = (self.artifacts / "saturation-REPORT.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Status: `saturated`; clear Tasks: **140**", report)
        self.assertIn("| 101–120 | none |", report)
        self.assertIn("| 121–140 | none |", report)

        spurious_signal_tasks = json.loads(json.dumps(tasks))
        spurious_signal_tasks[100]["saturation_signals"] = ["new_effect_type"]
        spurious_signal = self.report(
            spurious_signal_tasks,
            evidence_name="spurious-signal-evidence.jsonl",
            report_name="spurious-signal-REPORT.md",
        )
        self.assertEqual(2, spurious_signal.returncode)
        self.assertIn("must not declare new_effect_type", spurious_signal.stderr)

        effect_candidate = json.loads(json.dumps(candidate))
        effect_candidate["candidate_status"] = "candidate"
        effect_candidate["mapped_trace_files"] = source_candidate[
            "mapped_trace_files"
        ]
        effect_candidate["reads"] = source_candidate["reads"]
        effect_candidate["visible_messages"][120] = source_candidate[
            "visible_choice_candidates"
        ][0]
        effect_candidate["visible_choice_candidates"] = source_candidate[
            "visible_choice_candidates"
        ]
        write_jsonl(self.artifacts / "candidates.jsonl", [effect_candidate])

        novel_tasks = json.loads(json.dumps(tasks))
        novel_tasks[120] = self.task_judgment(
            effect_candidate,
            task_id="sample-task-121",
            message_id=MESSAGE_ID,
            sampling_order=121,
        )
        missing_signal = self.report(
            novel_tasks,
            evidence_name="missing-signal-evidence.jsonl",
            report_name="missing-signal-REPORT.md",
        )
        self.assertEqual(2, missing_signal.returncode)
        self.assertIn("must declare new_effect_type", missing_signal.stderr)

        novel_tasks[120]["saturation_signals"] = ["new_effect_type"]
        reset = self.report(
            novel_tasks,
            evidence_name="reset-evidence.jsonl",
            report_name="reset-REPORT.md",
        )
        self.assertEqual(0, reset.returncode, reset.stderr)
        reset_report = (self.artifacts / "reset-REPORT.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "Status: `continue_sampling`; clear Tasks: **140**",
            reset_report,
        )
        self.assertIn("| 121–140 | new_effect_type |", reset_report)

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
