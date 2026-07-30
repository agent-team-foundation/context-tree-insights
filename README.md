# Context Tree Value Audit

`context-tree-value-audit` 0.3.0 is an explicit-only Skill for task-first,
evidence-first analysis of Context Tree decision value for the current First
Tree Runtime when its native historical evidence is supported. It reconstructs
complete Tasks from authorized Chats, records whether a Tree Read is observed
or unresolved, and judges one optional Effect without a minimum sample gate.

The 0.2 series renamed the installable Skill from
`context-tree-insights` to `context-tree-value-audit`. Replace the old Skill
directory during upgrade; do not install both names because they represent one
explicit audit capability, not two independent workflows.

The audit core remains separate from First Tree core. Codex, Claude Code, and
Claude Code TUI use their existing native local transcripts. Cursor and Kimi
Code remain unsupported for historical value audits because their existing
local records cannot yet prove complete, Chat-bound Tree reads; affected Reads
are unresolved.
There is no shared Tree-read CLI, generic tool abstraction, runtime event,
database table, schedule, Context Tree write, or Web surface. Each run covers
one First Tree Agent, one managed workspace, one current Runtime, and one bound
Tree.

## Safety and interpretation

- Invocation is explicit only: `$context-tree-value-audit` in Codex or
  `/context-tree-value-audit` in Claude Code / Claude Code TUI.
- The invoking human may authorize the current Chat, exact Chat UUIDs, or all
  Chats visible to this one current Agent. The Skill trusts that explicit
  scope and never broadens it or crosses to another Agent.
- `Chat UUID @ Agent UUID` remains the authorization and trace-mapping unit;
  Task is the judgment and counting unit.
- Task means one complete objective-to-outcome work item. Planning,
  implementation, review, QA, corrections, and continuations for the same
  deliverable remain one Task.
- Local Runtime evidence is preflighted against authorized Chat and Agent IDs
  before complete recorded output is scanned.
- Missing, cleaned, ambiguous, malformed, truncated, or unsupported traces are
  coverage gaps.
- A valid `contextDecision` is projected minimally. Absence is unknown;
  malformed metadata is diagnostic and never blocks Chat export; repository
  identities must be remote and credential-free.
- A Tree read is evidence of explicit activity, not semantic use or causal
  value by itself.
- Single-file reads and statically closed read-only composites are recovered;
  dynamic or unknown shapes stay unresolved, and unsafe shapes are rejected.
- A read attempt with one completed, non-empty, attributable result and no
  explicit failure signal may become candidate evidence. Missing, failed,
  duplicate, pending, or out-of-window results stay unresolved.
- Read is only `observed` or `unresolved`; unresolved is never counted as
  unused.
- Effect is optional and only `confirmed`, `constrained`, `redirected`, or
  `conflicted`.
- A decision receipt may support an Effect but cannot create one by itself.
- There is no fixed Task quota, task-type gate, or saturation state.
- The output is a sampled evidence report, not causal proof, ROI, or a
  global effectiveness rate.

The audit writes only private local artifacts in the invoking Agent workspace.
Never commit real Chat exports, traces, passages, task judgments, evidence
JSONL, reports, or production-derived artifacts.

## Repository layout

```text
skills/context-tree-value-audit/
  SKILL.md
  VERSION
  agents/openai.yaml
  references/
    evidence-schema.md
    runtime-evidence-adapters.md
    task-analysis-schema.md
  scripts/context_tree_value_audit.py
projections/claude/context-tree-value-audit/
  SKILL.md
tests/
evals/manual-behavior-checklist.md
```

`skills/context-tree-value-audit` is the canonical payload. The small Claude
projection supplies Claude's manual-invocation metadata and delegates to the
canonical payload. Tests, evaluation material, and repository documentation
stay outside both.

## Install into one Agent workspace

This repository does not install or enable the Skill automatically. Project
the Skill directory into one selected Agent workspace. For a fresh install:

```bash
CTVA_REPO="/absolute/path/to/context-tree-insights"
CTVA_AGENT_WORKSPACE="/absolute/path/to/selected/agent/workspace"
CTVA_SKILLS_ROOT="$CTVA_AGENT_WORKSPACE/.agents/skills"
CTVA_DESTINATION="$CTVA_SKILLS_ROOT/context-tree-value-audit"
CTVA_CLAUDE_ROOT="$CTVA_AGENT_WORKSPACE/.claude/skills"
CTVA_CLAUDE_DESTINATION="$CTVA_CLAUDE_ROOT/context-tree-value-audit"
CTVA_CLAUDE_SOURCE="$CTVA_REPO/projections/claude/context-tree-value-audit"

test ! -e "$CTVA_DESTINATION"
test ! -e "$CTVA_CLAUDE_DESTINATION"
test ! -L "$CTVA_CLAUDE_DESTINATION"
mkdir -p "$CTVA_SKILLS_ROOT" "$CTVA_CLAUDE_ROOT"
cp -R "$CTVA_REPO/skills/context-tree-value-audit" "$CTVA_DESTINATION"
cp -R "$CTVA_CLAUDE_SOURCE" "$CTVA_CLAUDE_DESTINATION"
diff -qr "$CTVA_CLAUDE_SOURCE" "$CTVA_CLAUDE_DESTINATION"
test -f "$CTVA_CLAUDE_DESTINATION/SKILL.md"
python3 "$CTVA_REPO/scripts/validate_skill.py"
```

For an upgrade from the old 0.2.x name, move the exact legacy payload to a
recoverable directory outside every Skill discovery root, then install and
compare the new payload:

```bash
CTVA_REPO="/absolute/path/to/context-tree-insights"
CTVA_AGENT_WORKSPACE="/absolute/path/to/selected/agent/workspace"
CTVA_SKILLS_ROOT="$CTVA_AGENT_WORKSPACE/.agents/skills"
CTVA_OLD="$CTVA_SKILLS_ROOT/context-tree-insights"
CTVA_NEW="$CTVA_SKILLS_ROOT/context-tree-value-audit"
CTVA_SOURCE="$CTVA_REPO/skills/context-tree-value-audit"
CTVA_QUARANTINE="$CTVA_AGENT_WORKSPACE/.skill-quarantine/context-tree-insights"
CTVA_CLAUDE_ROOT="$CTVA_AGENT_WORKSPACE/.claude/skills"
CTVA_OLD_CLAUDE="$CTVA_CLAUDE_ROOT/context-tree-insights"
CTVA_NEW_CLAUDE="$CTVA_CLAUDE_ROOT/context-tree-value-audit"
CTVA_OLD_CLAUDE_TARGET="../../.agents/skills/context-tree-insights"
CTVA_CLAUDE_SOURCE="$CTVA_REPO/projections/claude/context-tree-value-audit"
CTVA_QUARANTINE_CLAUDE="$CTVA_AGENT_WORKSPACE/.skill-quarantine/context-tree-insights.claude-link"

test -f "$CTVA_OLD/SKILL.md"
test "$(sed -n 's/^name:[[:space:]]*//p' "$CTVA_OLD/SKILL.md")" = "context-tree-insights"
test ! -e "$CTVA_NEW"
test ! -e "$CTVA_NEW_CLAUDE"
test ! -L "$CTVA_NEW_CLAUDE"
test ! -e "$CTVA_QUARANTINE"
test ! -e "$CTVA_QUARANTINE_CLAUDE"
test ! -L "$CTVA_QUARANTINE_CLAUDE"
mkdir -p "$(dirname "$CTVA_QUARANTINE")" "$CTVA_CLAUDE_ROOT"
if test -e "$CTVA_OLD_CLAUDE" || test -L "$CTVA_OLD_CLAUDE"; then
  test -L "$CTVA_OLD_CLAUDE"
  test "$(readlink "$CTVA_OLD_CLAUDE")" = "$CTVA_OLD_CLAUDE_TARGET"
  mv "$CTVA_OLD_CLAUDE" "$CTVA_QUARANTINE_CLAUDE"
fi
mv "$CTVA_OLD" "$CTVA_QUARANTINE"
cp -R "$CTVA_SOURCE" "$CTVA_NEW"
cp -R "$CTVA_CLAUDE_SOURCE" "$CTVA_NEW_CLAUDE"
diff -qr "$CTVA_SOURCE" "$CTVA_NEW"
diff -qr "$CTVA_CLAUDE_SOURCE" "$CTVA_NEW_CLAUDE"
test -f "$CTVA_NEW_CLAUDE/SKILL.md"
python3 "$CTVA_REPO/scripts/validate_skill.py"
test ! -e "$CTVA_OLD"
```

To roll back, move the new payload aside and restore the quarantined directory:

```bash
test -d "$CTVA_QUARANTINE"
test -d "$CTVA_NEW"
test -d "$CTVA_NEW_CLAUDE"
diff -qr "$CTVA_CLAUDE_SOURCE" "$CTVA_NEW_CLAUDE"
mv "$CTVA_NEW_CLAUDE" "$CTVA_QUARANTINE.failed-new.claude"
mv "$CTVA_NEW" "$CTVA_QUARANTINE.failed-new"
mv "$CTVA_QUARANTINE" "$CTVA_OLD"
if test -L "$CTVA_QUARANTINE_CLAUDE"; then
  mv "$CTVA_QUARANTINE_CLAUDE" "$CTVA_OLD_CLAUDE"
fi
```

Start a new Runtime session after a successful install, upgrade, or rollback,
then confirm the intended single Skill name is callable. The Codex
`allow_implicit_invocation: false` policy and Claude
`disable-model-invocation: true` frontmatter keep the Skill out of ordinary
tasks. Pin a reviewed commit or release when installing for another Agent.

## Pipeline

The Skill orchestrates four stages:

1. `export-chats` resolves explicit authorization and exports visible records.
2. `collect` maps authorized Chats to supported native local evidence,
   classifies every in-window Tree-read attempt into a conserving four-state
   grammar, reconstructs exact or read-only-composite evidence plus visible
   choices, and distinguishes local default-branch matches from unverified
   sources. Unsupported Runtime history produces unresolved Reads.
3. The Agent reconstructs complete Tasks and writes one observed/unresolved
   Read plus at most one Effect in schema-v2 `task-judgments.jsonl`.
4. `report` validates source ownership, windows, cross-Chat linkage,
   Read/choice timing, deduplication, and aggregate conservation, then creates
   `evidence.jsonl` and `REPORT.md`. An optional hash-anchored reviewed
   baseline is shown separately, so a current collector gap cannot erase
   previously reviewed positive cases or silently import them into the rerun.

There is no default time window. `--days` is an optional data-acquisition
bound. Every available Task in the authorized bound is reported; sample size
limits the conclusion rather than whether a report can be produced.

Detailed commands and schemas are in
[`SKILL.md`](skills/context-tree-value-audit/SKILL.md),
[`evidence-schema.md`](skills/context-tree-value-audit/references/evidence-schema.md),
[runtime-evidence-adapters.md](skills/context-tree-value-audit/references/runtime-evidence-adapters.md),
and
[`task-analysis-schema.md`](skills/context-tree-value-audit/references/task-analysis-schema.md).

## Validate

Run the deterministic floor before publishing:

```bash
python3 scripts/validate_skill.py
python3 -m compileall -q skills tests scripts
python3 -m unittest discover -s tests -v
```

Then execute
[`evals/manual-behavior-checklist.md`](evals/manual-behavior-checklist.md)
against a designated pilot Agent with authorized disposable or sanitized
records. Model-backed evaluation remains outside the deterministic gate.
