#!/usr/bin/env python3
"""Context Tree value audit built on the durable `context_tree_io_events` feed.

Exposure is a recorded fact, not an inference: `first-tree tree io` returns the
calling agent's own Context Tree reads and writes, captured at tool-execution
time by the runtime. This script does the deterministic half of the audit —
aggregate the feed, pick a sample, assemble case material — and leaves exactly
one judgment to the model: did a given read change what the agent did next.

Two recording gaps are known and are carried into every report rather than
silently absorbed:

* shell reads that go through a pipeline (`cat NODE.md | head -40`) are not
  recorded, so adoption is a LOWER BOUND, never a rate;
* `Grep` / `Glob` record one directory-level event for the search root, not one
  per matched node, so a node inside a searched directory can never be called
  never-read.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

SCHEMA_VERSION = 1
EFFECT_TYPES = ("confirmed", "constrained", "redirected", "conflicted")
ACTIONS = ("read", "write")
TARGET_KINDS = ("file", "directory", "repo")
# Path-based triage only. A node being "normal" does not make a read valuable;
# it only means the node is the kind of content a decision can come from.
NON_NORMAL_PREFIXES = ("members/", "raw-context/")
NON_NORMAL_NAMES = ("AGENTS.md", "CLAUDE.md", "README.md")
SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z")


class AuditError(RuntimeError):
    """Invalid input, or a deterministic step that cannot complete honestly."""


# ── time ──────────────────────────────────────────────────────────────────


def parse_time(value: str, *, field_name: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise AuditError(f"{field_name} is not an RFC 3339 timestamp: {value}") from error
    if parsed.tzinfo is None:
        raise AuditError(f"{field_name} must carry a timezone: {value}")
    return parsed.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ── CLI bridge ────────────────────────────────────────────────────────────


def resolve_binary(explicit: str | None) -> str:
    requested = explicit or os.environ.get("FIRST_TREE_BIN")
    candidates = [requested] if requested else ["first-tree", "first-tree-staging"]
    for candidate in candidates:
        if not candidate:
            continue
        if os.sep in candidate:
            path = Path(candidate).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                return str(path.resolve())
            continue
        found = shutil.which(candidate)
        if found:
            return found
    raise AuditError("No First Tree CLI found; set FIRST_TREE_BIN or pass --first-tree-bin.")


def run_cli_json(binary: str, args: Sequence[str]) -> Any:
    command = [binary, "--json", *args]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise AuditError(
            f"Read-only First Tree command failed: {' '.join(args)} "
            f"(exit {completed.returncode}; output withheld)."
        )
    out = completed.stdout.strip()
    if not out:
        raise AuditError(f"First Tree command produced no JSON: {' '.join(args)}")
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as error:
        raise AuditError(f"Invalid JSON from {' '.join(args)}: {error}") from error
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise AuditError(f"First Tree command did not succeed: {' '.join(args)}")
    return payload.get("data")


def fetch_io_events(
    binary: str,
    *,
    since: datetime | None,
    until: datetime | None,
    chat_id: str | None,
    agent: str | None,
    page_limit: int = 200,
    max_pages: int = 200,
) -> list[dict[str, Any]]:
    """Page the agent-scoped IO feed. Fails closed rather than truncating."""
    events: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(max_pages):
        args = ["tree", "io", "--limit", str(page_limit)]
        if since is not None:
            args += ["--since", iso(since)]
        if until is not None:
            args += ["--until", iso(until)]
        if chat_id:
            args += ["--chat", chat_id]
        if agent:
            args += [f"--agent={agent}"]
        if cursor:
            args += ["--cursor", cursor]
        data = run_cli_json(binary, args)
        if not isinstance(data, dict):
            raise AuditError("tree io returned no data object.")
        items = data.get("items")
        if not isinstance(items, list):
            raise AuditError("tree io returned no items array.")
        events.extend(item for item in items if isinstance(item, dict))
        next_cursor = data.get("nextCursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            return events
        if next_cursor in seen_cursors:
            raise AuditError("tree io pagination repeated a cursor.")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    raise AuditError(
        f"tree io did not finish within {max_pages} pages; narrow --since/--until."
    )


# ── event model ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IoEvent:
    event_id: str
    chat_id: str
    action: str
    source: str
    target_kind: str
    target_path: str
    tree_head_commit: str | None
    created_at: datetime

    @property
    def is_normal_content(self) -> bool:
        path = self.target_path
        if path in NON_NORMAL_NAMES or Path(path).name in NON_NORMAL_NAMES:
            return False
        return not path.startswith(NON_NORMAL_PREFIXES)


def normalize_event(raw: Mapping[str, Any]) -> IoEvent:
    def text(key: str) -> str:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise AuditError(f"IO event is missing `{key}`.")
        return value.strip()

    action = text("action")
    if action not in ACTIONS:
        raise AuditError(f"IO event has an unknown action: {action}")
    target_kind = text("targetKind")
    if target_kind not in TARGET_KINDS:
        raise AuditError(f"IO event has an unknown targetKind: {target_kind}")
    commit = raw.get("treeHeadCommit")
    return IoEvent(
        event_id=text("id"),
        chat_id=text("chatId"),
        action=action,
        source=text("source"),
        target_kind=target_kind,
        target_path=text("targetPath"),
        tree_head_commit=commit if isinstance(commit, str) and SHA_RE.match(commit) else None,
        created_at=parse_time(text("createdAt"), field_name="IO event createdAt"),
    )


# ── aggregation (no sampling, no judgment) ────────────────────────────────


@dataclass
class Aggregate:
    reads: list[IoEvent] = field(default_factory=list)
    writes: list[IoEvent] = field(default_factory=list)
    chats_with_read: set[str] = field(default_factory=set)
    chats_seen: set[str] = field(default_factory=set)
    node_reads: Counter[str] = field(default_factory=Counter)
    searched_dirs: set[str] = field(default_factory=set)
    node_writes: Counter[str] = field(default_factory=Counter)
    source_counts: Counter[str] = field(default_factory=Counter)


def aggregate(events: Iterable[IoEvent]) -> Aggregate:
    agg = Aggregate()
    for event in events:
        agg.chats_seen.add(event.chat_id)
        agg.source_counts[f"{event.action}:{event.source}"] += 1
        if event.action == "write":
            agg.writes.append(event)
            if event.target_kind == "file":
                agg.node_writes[event.target_path] += 1
            continue
        agg.reads.append(event)
        agg.chats_with_read.add(event.chat_id)
        if event.target_kind == "file":
            agg.node_reads[event.target_path] += 1
        else:
            # Directory / repo events name a search root, not a node. They
            # cannot credit a specific node, but they DO forbid calling any
            # node beneath them never-read.
            agg.searched_dirs.add("" if event.target_kind == "repo" else event.target_path.rstrip("/"))
    return agg


def covered_by_search(node_path: str, searched_dirs: set[str]) -> bool:
    """True when some recorded search root contains this node."""
    if "" in searched_dirs:  # a repo-level event covers everything
        return True
    parts = Path(node_path).parts
    for index in range(len(parts)):
        if "/".join(parts[:index]) in searched_dirs:
            return True
    return False


def never_read_nodes(tree_root: Path, agg: Aggregate) -> list[str]:
    """Nodes with no file-level read and no directory-level search above them.

    Deliberately conservative: a node inside a searched directory is excluded
    even though the search may never have opened it. Over-reporting here would
    recommend deleting a node that was in fact consulted.
    """
    candidates: list[str] = []
    for path in sorted(tree_root.rglob("*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            relative = path.relative_to(tree_root).as_posix()
        except ValueError:
            continue
        if any(part.startswith(".") for part in Path(relative).parts):
            continue
        if relative in NON_NORMAL_NAMES or relative.startswith(NON_NORMAL_PREFIXES):
            continue
        if agg.node_reads.get(relative):
            continue
        if covered_by_search(relative, agg.searched_dirs):
            continue
        candidates.append(relative)
    return candidates


# ── case material for the judgment step ───────────────────────────────────


def git_show(tree_root: Path, commit: str, node_path: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(tree_root), "show", f"{commit}:{node_path}"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"},
    )
    return completed.stdout if completed.returncode == 0 else None


def node_content_at_read(tree_root: Path, event: IoEvent, max_chars: int) -> dict[str, Any]:
    """Recover what the node said when it was read, preferring the exact commit."""
    if event.tree_head_commit:
        content = git_show(tree_root, event.tree_head_commit, event.target_path)
        if content is not None:
            body, truncated = clip(content, max_chars)
            return {"status": "exact_commit", "commit": event.tree_head_commit, "content": body, "truncated": truncated}
    current = tree_root / event.target_path
    if current.is_file() and not current.is_symlink():
        try:
            body, truncated = clip(current.read_text(encoding="utf-8"), max_chars)
        except (OSError, UnicodeDecodeError):
            return {"status": "unavailable", "reason": "node_unreadable"}
        return {"status": "current_working_copy", "content": body, "truncated": truncated}
    return {"status": "unavailable", "reason": "node_absent_at_audit_time"}


def clip(text: str, limit: int) -> tuple[str, bool]:
    return (text, False) if len(text) <= limit else (text[:limit], True)


def sample_reads(reads: Sequence[IoEvent], size: int, seed: int) -> list[IoEvent]:
    """Uniform sample over recorded reads.

    Sampling is random on purpose. Picking the cases whose surrounding decision
    stream is still available would bias the sample toward recent, still-live
    sessions; instead we sample first and report how many cases turned out to
    be unresolvable.
    """
    eligible = [event for event in reads if event.target_kind == "file" and event.is_normal_content]
    if size >= len(eligible):
        return list(eligible)
    return random.Random(seed).sample(eligible, size)


# ── report ────────────────────────────────────────────────────────────────

KNOWN_GAPS = [
    "Shell reads that pass through a pipeline (for example `cat NODE.md | head -40`) are not recorded, "
    "so adoption below is a lower bound, not a rate.",
    "`Grep` / `Glob` record one directory-level event for the search root rather than one event per matched "
    "node, so a node inside a searched directory is never listed as never-read.",
]


def render_report(
    *,
    generated_at: datetime,
    window_start: datetime | None,
    window_end: datetime | None,
    agg: Aggregate,
    never_read: list[str] | None,
    judgments: Sequence[Mapping[str, Any]] | None,
    sample_size: int,
) -> str:
    lines: list[str] = [
        "# Context Tree Value Audit",
        "",
        f"Generated: {iso(generated_at)}",
        "Window: "
        + (f"{iso(window_start)} – " if window_start else "unbounded – ")
        + (iso(window_end) if window_end else "now"),
        "",
        "This is an evidence report over one agent's own recorded Context Tree IO. "
        "It is not causal proof, an effectiveness rate, or ROI.",
        "",
        "## Exposure",
        "",
        "| Measure | Count |",
        "| --- | ---: |",
        f"| Chats with at least one recorded Tree read | {len(agg.chats_with_read)} |",
        f"| Chats with any recorded Tree IO | {len(agg.chats_seen)} |",
        f"| Recorded reads | {len(agg.reads)} |",
        f"| Recorded writes | {len(agg.writes)} |",
        f"| Distinct nodes read | {len(agg.node_reads)} |",
        "",
        "Adoption is reported as counts, not as a percentage of all work: reads that the runtime "
        "could not record are invisible here, so any ratio would overstate its own precision.",
        "",
    ]

    if agg.node_reads:
        lines += ["## Most-read nodes", "", "| Node | Reads |", "| --- | ---: |"]
        for path, count in agg.node_reads.most_common(15):
            lines.append(f"| `{path}` | {count} |")
        lines.append("")

    if never_read is not None:
        lines += [
            "## Never-read nodes",
            "",
            f"{len(never_read)} normal node(s) had no file-level read and sat under no recorded search root "
            "in this window.",
            "",
        ]
        if never_read:
            lines += ["```"] + [f"{path}" for path in never_read[:100]] + ["```", ""]
            if len(never_read) > 100:
                lines.append(f"…and {len(never_read) - 100} more.\n")
            lines.append(
                "A node that is never consulted is a candidate for removal or merge — but confirm against a "
                "longer window before deleting anything; this list only covers the window above.\n"
            )
        else:
            lines.append("Every normal node was read or sat under a recorded search root.\n")

    if agg.node_writes:
        lines += ["## Write activity", "", "| Node | Writes |", "| --- | ---: |"]
        for path, count in agg.node_writes.most_common(15):
            lines.append(f"| `{path}` | {count} |")
        lines.append("")

    if judgments is not None:
        effects = [item for item in judgments if item.get("effect")]
        refuted = [item for item in effects if item.get("refuted") is True]
        upheld = [item for item in effects if item.get("refuted") is not True]
        counts = Counter(str(item["effect"]["type"]) for item in upheld)
        rate = (len(refuted) / len(effects)) if effects else None
        lines += [
            "## Influence (sampled)",
            "",
            "| Measure | Count |",
            "| --- | ---: |",
            f"| Sampled reads | {sample_size} |",
            f"| Judged as influencing a later choice | {len(effects)} |",
            f"| Refuted by the adversarial pass | {len(refuted)} |",
            f"| Upheld | {len(upheld)} |",
            "",
        ]
        if rate is None:
            lines.append("No influence was claimed in this sample, so there is no refutation rate.\n")
        else:
            lines.append(f"**Refutation rate: {len(refuted)}/{len(effects)} ({rate:.0%})**\n")
            if rate > 0.5:
                lines += [
                    "> ⚠️ More than half of the claimed effects were refuted. **The influence numbers in this "
                    "run are not reliable and are withheld.** Treat the exposure section above as the only "
                    "usable output, and investigate the judgment step before quoting any effect count.",
                    "",
                ]
            else:
                lines += ["| Effect | Upheld |", "| --- | ---: |"]
                for effect_type in EFFECT_TYPES:
                    lines.append(f"| {effect_type} | {counts[effect_type]} |")
                lines.append("")
                for item in upheld:
                    effect = item["effect"]
                    lines += [
                        f"- **{effect['type']}** — {effect.get('summary', '').strip()}",
                        f"  - read `{item['read_id']}` on `{item['target_path']}` at {item['read_at']}",
                    ]
                if upheld:
                    lines.append("")

    lines += ["## Known recording gaps", ""]
    lines += [f"- {gap}" for gap in KNOWN_GAPS]
    lines += [
        "",
        "Missing evidence is unknown, never proof that the Tree went unused.",
        "",
    ]
    return "\n".join(lines)


# ── commands ──────────────────────────────────────────────────────────────


def resolve_tree_root(value: str | None) -> Path:
    raw = Path(value).expanduser() if value else None
    if raw is None:
        raise AuditError("--tree-root is required to resolve node paths and content.")
    if not raw.is_absolute() or raw.is_symlink():
        raise AuditError("--tree-root must be an absolute, non-symlink directory.")
    root = raw.resolve(strict=False)
    if not root.is_dir():
        raise AuditError(f"--tree-root is not a directory: {root}")
    return root


def load_events(args: argparse.Namespace) -> list[IoEvent]:
    if args.events_file:
        path = Path(args.events_file).expanduser()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AuditError(f"Could not read --events-file: {error}") from error
        raw_items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(raw_items, list):
            raise AuditError("--events-file must contain an items array.")
    else:
        binary = resolve_binary(args.first_tree_bin)
        since = parse_time(args.since, field_name="--since") if args.since else None
        until = parse_time(args.until, field_name="--until") if args.until else None
        if since and until and since > until:
            raise AuditError("--since must not be after --until.")
        raw_items = fetch_io_events(
            binary,
            since=since,
            until=until,
            chat_id=args.chat,
            agent=args.agent,
        )
    return [normalize_event(item) for item in raw_items if isinstance(item, dict)]


def write_output(path: str | None, text: str) -> None:
    if not path:
        sys.stdout.write(text)
        return
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.write_text(text, encoding="utf-8")
    os.chmod(target, 0o600)


def command_facts(args: argparse.Namespace) -> None:
    events = load_events(args)
    agg = aggregate(events)
    tree_root = resolve_tree_root(args.tree_root) if args.tree_root else None
    never_read = never_read_nodes(tree_root, agg) if tree_root else None
    window_start = parse_time(args.since, field_name="--since") if args.since else None
    window_end = parse_time(args.until, field_name="--until") if args.until else None
    generated_at = parse_time(args.now, field_name="--now") if args.now else datetime.now(timezone.utc)
    if args.json:
        write_output(
            args.output,
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "generated_at": iso(generated_at),
                    "reads": len(agg.reads),
                    "writes": len(agg.writes),
                    "chats_with_read": sorted(agg.chats_with_read),
                    "node_reads": dict(agg.node_reads.most_common()),
                    "node_writes": dict(agg.node_writes.most_common()),
                    "searched_dirs": sorted(agg.searched_dirs),
                    "never_read_nodes": never_read,
                    "source_counts": dict(sorted(agg.source_counts.items())),
                    "known_gaps": KNOWN_GAPS,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        return
    write_output(
        args.output,
        render_report(
            generated_at=generated_at,
            window_start=window_start,
            window_end=window_end,
            agg=agg,
            never_read=never_read,
            judgments=None,
            sample_size=0,
        ),
    )


def command_sample(args: argparse.Namespace) -> None:
    events = load_events(args)
    agg = aggregate(events)
    tree_root = resolve_tree_root(args.tree_root)
    chosen = sample_reads(agg.reads, args.size, args.seed)
    cases = [
        {
            "read_id": event.event_id,
            "chat_id": event.chat_id,
            "read_at": iso(event.created_at),
            "target_path": event.target_path,
            "source": event.source,
            "node": node_content_at_read(tree_root, event, args.max_content_chars),
        }
        for event in chosen
    ]
    write_output(
        args.output,
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "eligible_reads": len([e for e in agg.reads if e.target_kind == "file" and e.is_normal_content]),
                "sample_size": len(cases),
                "seed": args.seed,
                "cases": cases,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )


def validate_judgments(raw: Any, cases: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise AuditError("Judgments must be a JSON array.")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        where = f"judgments[{index}]"
        if not isinstance(item, dict):
            raise AuditError(f"{where} must be an object.")
        read_id = item.get("read_id")
        if not isinstance(read_id, str) or read_id not in cases:
            raise AuditError(f"{where}.read_id does not match a sampled case.")
        if read_id in seen:
            raise AuditError(f"{where} duplicates read_id {read_id}.")
        seen.add(read_id)
        effect = item.get("effect")
        row: dict[str, Any] = {
            "read_id": read_id,
            "target_path": cases[read_id]["target_path"],
            "read_at": cases[read_id]["read_at"],
            "effect": None,
            "refuted": False,
        }
        if effect is None:
            out.append(row)
            continue
        if not isinstance(effect, dict):
            raise AuditError(f"{where}.effect must be an object or null.")
        effect_type = effect.get("type")
        if effect_type not in EFFECT_TYPES:
            raise AuditError(f"{where}.effect.type must be one of: {', '.join(EFFECT_TYPES)}.")
        summary = effect.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise AuditError(f"{where}.effect.summary is required.")
        refuted = item.get("refuted")
        if not isinstance(refuted, bool):
            raise AuditError(
                f"{where}.refuted must be true or false — every claimed effect must go through the "
                "adversarial pass."
            )
        if refuted and not str(item.get("refutation", "")).strip():
            raise AuditError(f"{where}.refutation is required when refuted is true.")
        row["effect"] = {"type": effect_type, "summary": summary.strip()}
        row["refuted"] = refuted
        if refuted:
            row["refutation"] = str(item["refutation"]).strip()
        out.append(row)
    missing = set(cases) - seen
    if missing:
        raise AuditError(
            "Every sampled case needs a judgment; missing: " + ", ".join(sorted(missing)) + "."
        )
    return out


def command_report(args: argparse.Namespace) -> None:
    events = load_events(args)
    agg = aggregate(events)
    tree_root = resolve_tree_root(args.tree_root) if args.tree_root else None
    never_read = never_read_nodes(tree_root, agg) if tree_root else None

    try:
        sample_payload = json.loads(Path(args.sample).expanduser().read_text(encoding="utf-8"))
        judgment_payload = json.loads(Path(args.judgments).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"Could not read sample or judgments: {error}") from error
    raw_cases = sample_payload.get("cases") if isinstance(sample_payload, dict) else None
    if not isinstance(raw_cases, list):
        raise AuditError("--sample must contain a cases array.")
    cases = {
        str(case["read_id"]): case
        for case in raw_cases
        if isinstance(case, dict) and isinstance(case.get("read_id"), str)
    }
    judgments = validate_judgments(judgment_payload, cases)
    generated_at = parse_time(args.now, field_name="--now") if args.now else datetime.now(timezone.utc)
    write_output(
        args.output,
        render_report(
            generated_at=generated_at,
            window_start=parse_time(args.since, field_name="--since") if args.since else None,
            window_end=parse_time(args.until, field_name="--until") if args.until else None,
            agg=agg,
            never_read=never_read,
            judgments=judgments,
            sample_size=len(cases),
        ),
    )


# ── parser ────────────────────────────────────────────────────────────────


def add_feed_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--since", help="RFC 3339 lower bound on event time.")
    parser.add_argument("--until", help="RFC 3339 upper bound on event time.")
    parser.add_argument("--chat", help="Restrict to one Chat UUID.")
    parser.add_argument("--agent", help="Local agent name (defaults to FIRST_TREE_AGENT_ID).")
    parser.add_argument("--first-tree-bin", help="First Tree CLI executable.")
    parser.add_argument(
        "--events-file",
        help="Read a captured `tree io --json` payload instead of calling the CLI (tests, replay).",
    )
    parser.add_argument("--output", help="Write here instead of stdout (mode 0600).")
    parser.add_argument("--now", help="Fixed RFC 3339 generation time for reproducible output.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Context Tree value audit over the durable agent IO feed.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    facts = sub.add_parser("facts", help="Aggregate exposure, node distribution, and write health.")
    add_feed_options(facts)
    facts.add_argument("--tree-root", help="Bound Context Tree root; enables the never-read node list.")
    facts.add_argument("--json", action="store_true", help="Emit structured facts instead of Markdown.")
    facts.set_defaults(handler=command_facts)

    sample = sub.add_parser("sample", help="Draw a random read sample and assemble case material.")
    add_feed_options(sample)
    sample.add_argument("--tree-root", required=True, help="Bound Context Tree root.")
    sample.add_argument("--size", type=int, default=40, help="Sample size (default 40).")
    sample.add_argument("--seed", type=int, default=0, help="Sampling seed for reproducibility.")
    sample.add_argument("--max-content-chars", type=int, default=8000, help="Per-node content cap.")
    sample.set_defaults(handler=command_sample)

    report = sub.add_parser("report", help="Validate judgments and render the final report.")
    add_feed_options(report)
    report.add_argument("--tree-root", help="Bound Context Tree root; enables the never-read node list.")
    report.add_argument("--sample", required=True, help="Sample JSON produced by `sample`.")
    report.add_argument("--judgments", required=True, help="Judgment JSON array authored by the analyst.")
    report.set_defaults(handler=command_report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    os.umask(0o077)
    args = build_parser().parse_args(argv)
    try:
        if getattr(args, "size", 1) <= 0:
            raise AuditError("--size must be greater than zero.")
        args.handler(args)
    except AuditError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
