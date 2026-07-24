# Context Tree Insights

`context-tree-insights` is an umbrella Codex Skill for evidence-first analysis
of Context Tree use. The private V0 pilot contains one capability: a manual,
read-only retrospective that reconstructs whether a passage read from the
Context Tree visibly influenced a later Agent choice.

It is intentionally not integrated into First Tree core. It does not add a
bundled Skill, CLI contract, client briefing, database table, schedule, Tree
write, or provider adapter. It runs for one First Tree Codex Agent, one managed
workspace, and one bound Tree at a time.

## Safety and interpretation

- Invocation is explicit only: `$context-tree-insights`.
- The invoking human must authorize either all Chats for the current Agent,
  exact Chat UUIDs for that Agent, or the invoking current Chat resolved to its
  runtime `chatId`.
- Local Codex traces are preflighted against exact authorized `chatId` values
  before full content is scanned. Only canonical Codex user-message rows can
  establish identity; the adjacent event mirror must agree, while tool-output
  and compaction echoes cannot authorize or invalidate a trace.
- Missing, cleaned, ambiguous, malformed, truncated, or unsupported traces are
  reported as coverage gaps.
- Evidence uses opaque Tree and trace identities rather than leaking local
  filesystem paths.
- A Tree read is not value by itself. Positive evidence requires a
  decision-bearing passage, task relevance, pre-choice timing, and conservative
  passage-to-choice analysis.
- Authorized Chats are coverage, not an eligible denominator for a value rate.

The audit writes only private local artifacts in the invoking Agent workspace.
Do not commit real Chat exports, provider traces, raw passages, evidence JSONL,
reports, or any artifact derived from production activity to this repository.

## Repository layout

```text
skills/context-tree-insights/
  SKILL.md
  VERSION
  agents/openai.yaml
  references/evidence-schema.md
  scripts/context_tree_insights.py
tests/
evals/manual-behavior-checklist.md
```

Only `skills/context-tree-insights` is the installable Skill payload. Tests,
evaluation material, and repository documentation stay outside it.

## Install into one Agent workspace

This repository does not install or enable the Skill automatically. Project
the `skills/context-tree-insights` directory into the selected Agent
workspace's local Skill directory:

```bash
CTI_REPO="/absolute/path/to/context-tree-insights"
CTI_AGENT_WORKSPACE="/absolute/path/to/selected/agent/workspace"
CTI_DESTINATION="$CTI_AGENT_WORKSPACE/.agents/skills/context-tree-insights"

test ! -e "$CTI_DESTINATION"
mkdir -p "$CTI_AGENT_WORKSPACE/.agents/skills"
cp -R "$CTI_REPO/skills/context-tree-insights" "$CTI_DESTINATION"
```

Start a new Codex session in that workspace after installation. The
`allow_implicit_invocation: false` policy keeps it out of normal tasks; invoke
it with `$context-tree-insights`.

Pin a reviewed commit or release when installing for another Agent. Updating
the repository does not update an installed projection; replace it only as an
explicit administrative action.

## Run

The Skill orchestrates three deterministic stages:

1. `export-chats` resolves the explicit authorization scope and exports only
   visible records for that scope.
2. `collect` maps authorized Chats to local Codex traces, reconstructs isolated
   Tree reads and later visible choices, and records coverage gaps.
3. The Agent applies the documented passage-level rubric, then `report`
   validates judgments and creates `evidence.jsonl` plus `REPORT.md`.

The default window is seven days and can be changed with a positive `--days`
value. Set `FIRST_TREE_BIN` for the active channel when needed, for example
`first-tree-staging`. Detailed commands and scope examples are in
[`SKILL.md`](skills/context-tree-insights/SKILL.md).

## Validate

Run the deterministic floor before publishing a revision:

```bash
python3 scripts/validate_skill.py
python3 -m compileall -q skills tests scripts
python3 -m unittest discover -s tests -v
```

Then execute
[`evals/manual-behavior-checklist.md`](evals/manual-behavior-checklist.md)
against a designated pilot Agent with authorized, disposable or sanitized
records. Model-backed evaluation is outside the V0 gate; the observable manual
checklist covers the Agent-controlled behavior.
