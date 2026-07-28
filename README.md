# Context Tree Insights

`context-tree-insights` 0.2.2 is an explicit-only Codex Skill for task-first,
evidence-first analysis of Context Tree decision value. It reconstructs Tasks
from authorized Chats, separates confirmed from unresolved exposure, judges
four visible effect types, and stops sampling through a Task quota plus
saturation.

It is intentionally separate from First Tree core. It does not add a bundled
Skill, runtime event, database table, message-path validation, schedule,
Context Tree write, Web surface, or another provider adapter. It runs for one
First Tree Codex Agent, one managed workspace, and one bound Tree at a time.

## Safety and interpretation

- Invocation is explicit only: `$context-tree-insights`.
- The invoking human authorizes all Chats for the current Agent, exact Chat
  UUIDs for that Agent, or the invoking Chat resolved from runtime `chatId`.
- `Chat UUID @ Agent UUID` remains the authorization and trace-mapping unit;
  Task is the judgment and counting unit.
- Local Codex traces are preflighted against authorized Chat IDs before full
  content is scanned.
- Missing, cleaned, ambiguous, malformed, truncated, or unsupported traces are
  coverage gaps.
- A valid `contextDecision` is projected minimally. Absence is unknown;
  malformed metadata is diagnostic and never blocks Chat export; repository
  identities must be remote and credential-free.
- A Tree read is evidence of explicit activity, not semantic use or causal
  value by itself.
- Single-file reads and statically closed read-only composites are recovered;
  dynamic or unknown shapes stay unresolved, and unsafe shapes are rejected.
- Unresolved exposure is never counted as unused.
- Missing evidence produces `N/A / pending`, never a numeric zero effect.
- The report does not produce a global effectiveness rate.

The audit writes only private local artifacts in the invoking Agent workspace.
Never commit real Chat exports, traces, passages, task judgments, evidence
JSONL, reports, or production-derived artifacts.

## Repository layout

```text
skills/context-tree-insights/
  SKILL.md
  VERSION
  agents/openai.yaml
  references/
    evidence-schema.md
    task-analysis-schema.md
  scripts/context_tree_insights.py
tests/
evals/manual-behavior-checklist.md
```

Only `skills/context-tree-insights` is the installable Skill payload. Tests,
evaluation material, and repository documentation stay outside it.

## Install into one Agent workspace

This repository does not install or enable the Skill automatically. Project
the Skill directory into one selected Agent workspace:

```bash
CTI_REPO="/absolute/path/to/context-tree-insights"
CTI_AGENT_WORKSPACE="/absolute/path/to/selected/agent/workspace"
CTI_DESTINATION="$CTI_AGENT_WORKSPACE/.agents/skills/context-tree-insights"

test ! -e "$CTI_DESTINATION"
mkdir -p "$CTI_AGENT_WORKSPACE/.agents/skills"
cp -R "$CTI_REPO/skills/context-tree-insights" "$CTI_DESTINATION"
```

Start a new Codex session after installation. The
`allow_implicit_invocation: false` policy keeps the Skill out of ordinary
tasks. Pin a reviewed commit or release when installing for another Agent.

## Pipeline

The Skill orchestrates four stages:

1. `export-chats` resolves explicit authorization and exports visible records.
2. `collect` maps authorized Chats to local Codex traces, classifies every
   in-window Tree-read attempt into a conserving four-state grammar, and
   reconstructs exact or read-only-composite evidence plus visible choices.
3. The Agent reconstructs Tasks, Task-window exposure, effects, and sampling
   signals in `task-judgments.jsonl`, including the reproducible five-check
   rubric behind each `verified` or `probable` effect.
4. `report` validates source ownership, windows, cross-Chat linkage,
   deduplication, sampling, and aggregate conservation, then creates
   `evidence.jsonl` and `REPORT.md`. An optional hash-anchored reviewed
   baseline is shown separately, so a current collector gap cannot erase
   previously reviewed positive cases or silently import them into the rerun.

There is no default time window. `--days` is an optional data-acquisition
bound. Sample size is controlled by at least 100 clear Tasks with all five task
types represented, followed by 20-Task expansions until two consecutive
batches add no effect type, key counterexample, or conclusion change.

Detailed commands and schemas are in
[`SKILL.md`](skills/context-tree-insights/SKILL.md),
[`evidence-schema.md`](skills/context-tree-insights/references/evidence-schema.md),
and
[`task-analysis-schema.md`](skills/context-tree-insights/references/task-analysis-schema.md).

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
