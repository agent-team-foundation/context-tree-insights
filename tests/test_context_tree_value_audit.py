"""Deterministic tests for the Context Tree value audit.

The audit's job is to be honest about a lossy feed, so most of what is worth
testing is what it refuses to claim: never-read lists that ignore search
coverage, adoption presented as a rate, effects that skipped the adversarial
pass, and influence numbers surviving a run whose judgments were mostly refuted.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "context-tree-value-audit" / "scripts"))

import context_tree_value_audit as audit  # noqa: E402

REPO = "https://github.com/example/context-tree"


def event(
    event_id: str,
    path: str,
    *,
    action: str = "read",
    kind: str = "file",
    chat: str = "chat-1",
    at: str = "2026-07-01T10:00:00Z",
    commit: str | None = None,
    source: str = "claude_read_tool",
) -> dict[str, object]:
    row: dict[str, object] = {
        "id": event_id,
        "chatId": chat,
        "action": action,
        "source": source,
        "targetKind": kind,
        "targetPath": path,
        "treeRepoUrl": REPO,
        "treeBranch": "main",
        "createdAt": at,
    }
    if commit:
        row["treeHeadCommit"] = commit
    return row


def normalized(rows: list[dict[str, object]]) -> list[audit.IoEvent]:
    return [audit.normalize_event(row) for row in rows]


class NormalizationTests(unittest.TestCase):
    def test_rejects_unknown_action_and_target_kind(self) -> None:
        with self.assertRaises(audit.AuditError):
            audit.normalize_event(event("e1", "a.md", action="delete"))
        with self.assertRaises(audit.AuditError):
            audit.normalize_event(event("e1", "a.md", kind="socket"))

    def test_keeps_only_a_valid_head_commit(self) -> None:
        good = audit.normalize_event(event("e1", "a.md", commit="a" * 40))
        bogus = audit.normalize_event(event("e2", "a.md", commit="nope"))
        self.assertEqual(good.tree_head_commit, "a" * 40)
        self.assertIsNone(bogus.tree_head_commit)

    def test_non_normal_content_is_classified_out(self) -> None:
        self.assertFalse(audit.normalize_event(event("e1", "AGENTS.md")).is_normal_content)
        self.assertFalse(audit.normalize_event(event("e2", "members/alice/NODE.md")).is_normal_content)
        self.assertFalse(audit.normalize_event(event("e3", "raw-context/dump.md")).is_normal_content)
        self.assertTrue(audit.normalize_event(event("e4", "system/cli/NODE.md")).is_normal_content)


class AggregationTests(unittest.TestCase):
    def test_separates_reads_writes_and_search_roots(self) -> None:
        agg = audit.aggregate(
            normalized(
                [
                    event("r1", "system/a.md"),
                    event("r2", "system/a.md", chat="chat-2"),
                    event("r3", "system", kind="directory", source="claude_read_tool"),
                    event("w1", "system/b.md", action="write", source="claude_write_tool"),
                ]
            )
        )
        self.assertEqual(agg.node_reads["system/a.md"], 2)
        self.assertEqual(agg.chats_with_read, {"chat-1", "chat-2"})
        self.assertEqual(agg.node_writes["system/b.md"], 1)
        # A directory event names a search root; it must not credit a node.
        self.assertNotIn("system", agg.node_reads)
        self.assertEqual(agg.searched_dirs, {"system"})

    def test_repo_level_event_covers_every_node(self) -> None:
        agg = audit.aggregate(normalized([event("r1", "/", kind="repo")]))
        self.assertTrue(audit.covered_by_search("anything/deep/node.md", agg.searched_dirs))


class NeverReadTests(unittest.TestCase):
    def _tree(self, root: Path) -> None:
        for relative in ("NODE.md", "system/NODE.md", "system/cli.md", "goal/NODE.md", "members/a/NODE.md"):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# node\n", encoding="utf-8")

    def test_lists_only_nodes_with_no_read_and_no_search_above_them(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._tree(root)
            agg = audit.aggregate(normalized([event("r1", "goal/NODE.md")]))
            never = audit.never_read_nodes(root, agg)
            self.assertIn("system/NODE.md", never)
            self.assertIn("system/cli.md", never)
            self.assertNotIn("goal/NODE.md", never)
            # member content is not normal decision content
            self.assertNotIn("members/a/NODE.md", never)

    def test_a_searched_directory_protects_every_node_beneath_it(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._tree(root)
            agg = audit.aggregate(normalized([event("r1", "system", kind="directory")]))
            never = audit.never_read_nodes(root, agg)
            # `Grep`/`Glob` record only the search root, so nothing under it can
            # be called never-read without risking a delete recommendation for a
            # node the search actually surfaced.
            self.assertNotIn("system/NODE.md", never)
            self.assertNotIn("system/cli.md", never)
            self.assertIn("goal/NODE.md", never)


class SamplingTests(unittest.TestCase):
    def test_samples_only_normal_file_reads_and_is_reproducible(self) -> None:
        events = normalized(
            [event(f"r{index}", f"system/n{index}.md") for index in range(20)]
            + [
                event("dir", "system", kind="directory"),
                event("agents", "AGENTS.md"),
                event("write", "system/n0.md", action="write"),
            ]
        )
        reads = [item for item in events if item.action == "read"]
        first = audit.sample_reads(reads, 5, seed=7)
        second = audit.sample_reads(reads, 5, seed=7)
        self.assertEqual([item.event_id for item in first], [item.event_id for item in second])
        self.assertEqual(len(first), 5)
        for item in first:
            self.assertEqual(item.target_kind, "file")
            self.assertTrue(item.is_normal_content)

    def test_returns_everything_when_the_sample_exceeds_the_population(self) -> None:
        reads = normalized([event("r1", "system/a.md"), event("r2", "system/b.md")])
        self.assertEqual(len(audit.sample_reads(reads, 50, seed=1)), 2)


class JudgmentValidationTests(unittest.TestCase):
    CASES = {
        "r1": {"read_id": "r1", "target_path": "system/a.md", "read_at": "2026-07-01T10:00:00Z"},
        "r2": {"read_id": "r2", "target_path": "system/b.md", "read_at": "2026-07-01T11:00:00Z"},
    }

    def test_accepts_a_null_effect_and_a_refuted_effect(self) -> None:
        rows = audit.validate_judgments(
            [
                {"read_id": "r1", "effect": None},
                {
                    "read_id": "r2",
                    "effect": {"type": "redirected", "summary": "Changed the approach."},
                    "refuted": True,
                    "refutation": "The human asked for it first.",
                },
            ],
            self.CASES,
        )
        self.assertIsNone(rows[0]["effect"])
        self.assertTrue(rows[1]["refuted"])
        self.assertEqual(rows[1]["refutation"], "The human asked for it first.")

    def test_a_claimed_effect_must_go_through_the_adversarial_pass(self) -> None:
        with self.assertRaisesRegex(audit.AuditError, "adversarial pass"):
            audit.validate_judgments(
                [
                    {"read_id": "r1", "effect": {"type": "confirmed", "summary": "x"}},
                    {"read_id": "r2", "effect": None},
                ],
                self.CASES,
            )

    def test_refuted_requires_its_explanation(self) -> None:
        with self.assertRaisesRegex(audit.AuditError, "refutation"):
            audit.validate_judgments(
                [
                    {"read_id": "r1", "effect": {"type": "confirmed", "summary": "x"}, "refuted": True},
                    {"read_id": "r2", "effect": None},
                ],
                self.CASES,
            )

    def test_rejects_unknown_effect_types_and_missing_cases(self) -> None:
        with self.assertRaises(audit.AuditError):
            audit.validate_judgments(
                [{"read_id": "r1", "effect": {"type": "helpful", "summary": "x"}, "refuted": False},
                 {"read_id": "r2", "effect": None}],
                self.CASES,
            )
        with self.assertRaisesRegex(audit.AuditError, "missing"):
            audit.validate_judgments([{"read_id": "r1", "effect": None}], self.CASES)

    def test_rejects_a_judgment_for_an_unsampled_read(self) -> None:
        with self.assertRaises(audit.AuditError):
            audit.validate_judgments([{"read_id": "not-sampled", "effect": None}], self.CASES)


class ReportTests(unittest.TestCase):
    GENERATED = datetime(2026, 7, 31, tzinfo=timezone.utc)

    def _render(self, judgments: list[dict[str, object]] | None, never_read: list[str] | None = None) -> str:
        agg = audit.aggregate(
            normalized([event("r1", "system/a.md"), event("w1", "system/b.md", action="write")])
        )
        return audit.render_report(
            generated_at=self.GENERATED,
            window_start=None,
            window_end=None,
            agg=agg,
            never_read=never_read,
            judgments=judgments,
            sample_size=len(judgments or []),
        )

    def test_never_presents_adoption_as_a_rate_and_always_states_the_gaps(self) -> None:
        text = self._render(None)
        self.assertNotIn("%", text.split("## Known recording gaps")[0])
        self.assertIn("lower bound", text)
        self.assertIn("pipeline", text)
        self.assertIn("directory-level event", text)
        self.assertIn("never proof that the Tree went unused", text)

    def test_withholds_influence_numbers_when_most_claims_were_refuted(self) -> None:
        judgments = [
            {"read_id": f"r{index}", "target_path": "system/a.md", "read_at": "t",
             "effect": {"type": "confirmed", "summary": "s"}, "refuted": index < 3}
            for index in range(4)
        ]
        text = self._render(judgments)
        self.assertIn("not reliable", text)
        self.assertIn("withheld", text)
        # The per-effect breakdown must not appear when the run is unreliable.
        self.assertNotIn("| Effect | Upheld |", text)

    def test_shows_the_breakdown_when_claims_survived(self) -> None:
        judgments = [
            {"read_id": "r1", "target_path": "system/a.md", "read_at": "t",
             "effect": {"type": "redirected", "summary": "Dropped plan A."}, "refuted": False},
            {"read_id": "r2", "target_path": "system/b.md", "read_at": "t", "effect": None, "refuted": False},
        ]
        text = self._render(judgments)
        self.assertIn("| Effect | Upheld |", text)
        self.assertIn("Dropped plan A.", text)
        self.assertNotIn("withheld", text)

    def test_reports_an_empty_never_read_list_without_implying_failure(self) -> None:
        text = self._render(None, never_read=[])
        self.assertIn("Every normal node was read or sat under a recorded search root", text)


class CliTests(unittest.TestCase):
    def test_facts_json_runs_end_to_end_from_a_captured_feed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            feed = root / "feed.json"
            feed.write_text(
                json.dumps({"items": [event("r1", "system/a.md"), event("w1", "system/b.md", action="write")]}),
                encoding="utf-8",
            )
            out = root / "facts.json"
            code = audit.main(
                ["facts", "--events-file", str(feed), "--json", "--output", str(out), "--now", "2026-07-31T00:00:00Z"]
            )
            self.assertEqual(code, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["reads"], 1)
            self.assertEqual(payload["writes"], 1)
            self.assertEqual(payload["node_reads"], {"system/a.md": 1})
            self.assertTrue(payload["known_gaps"])
            self.assertEqual(oct(out.stat().st_mode & 0o777), "0o600")

    def test_a_malformed_feed_fails_closed(self) -> None:
        with TemporaryDirectory() as tmp:
            feed = Path(tmp) / "feed.json"
            feed.write_text(json.dumps({"items": [{"id": "r1"}]}), encoding="utf-8")
            self.assertEqual(audit.main(["facts", "--events-file", str(feed), "--json"]), 2)


if __name__ == "__main__":
    unittest.main()
