---
name: context-tree-value-audit
description: Audit Context Tree decision value at Task level when a human explicitly invokes $context-tree-value-audit in Codex or /context-tree-value-audit in Claude. The audit is evidence-first, manual, read-only, limited to explicitly authorized Chats for the current First Tree Agent, and uses Task quotas plus saturation rather than Chat counts or a default time window. Do not use for ordinary task reads, stored-tree audits, Tree writes, generic Chat analytics, monitoring, or another Agent.
---

# Context Tree Value Audit

## Capability

Run a manual and read-only retrospective that reconstructs Tasks from
authorized Chats, establishes confirmed or unresolved Context Tree exposure
inside each Task window, judges visible effects, and reports Task-level value.

Keep three responsibilities separate:

- `Chat UUID @ Agent UUID` controls authorization, trace mapping, and evidence
  sourcing;
- Task reconstruction defines the judgment and counting unit;
- the bundled script performs deterministic collection, reference validation,
  deduplication, conservation checks, and reporting.

The collector establishes what records exist. The Agent reconstructs
single-Agent-owned continuous work episodes and performs passage-to-choice
judgment. A read or decision receipt is evidence, not server-verified
causality.

## Gate the run

Proceed only when a human explicitly invokes `$context-tree-value-audit` in
Codex or `/context-tree-value-audit` in Claude and asks for this value audit.
Do not trigger from an ordinary task, a normal Context Tree read, a stored-tree
quality audit, or an implicit analytics request.

Keep the run:

- manual and read-only;
- limited to one invoking Agent, one managed workspace, and one bound Context
  Tree;
- limited to the invoking Agent's supported local Runtime evidence;
- confined to a new private artifact directory inside the invoking Agent
  workspace.

Do not modify Chat history, traces, Tree content, git state, schedules, agent
configuration, databases, or product state. The visible reply and provider's
automatic trace append are not audit writes. Do not override the current
Runtime provider, invoke another Runtime adapter, or scan another Agent.

## Authorize the source scope

Resolve the exact current Agent UUID and bound Tree root from the managed
workspace identity. Resolve the immutable Agent `name` slug used by mentions,
URLs, CLI selectors, and local mirror paths from `FIRST_TREE_AGENT_SLUG`, and
cross-check `FIRST_TREE_AGENT_ID` and the First Tree CLI's producer-owned local
binding resolution of that slug against the workspace UUID. The local listing
is used only for this one identity check and is never persisted or promoted
into the authorized source scope. `displayName` is a mutable UI label and must
never be used as the CLI selector. Reject
symlinks, missing or malformed runtime identity, an Agent mismatch, an unbound
Tree, or more than one workspace or Tree.

Choose exactly one mode from the human's explicit request:

1. `explicit_agent`: all Chats visible to this one current Agent, only when the
   human explicitly asks for the current Agent's full Chat scope;
2. `explicit_chat`: exact Chat UUIDs for this Agent, or the explicitly
   authorized invoking Chat resolved from runtime `chatId`.

Trust the human's explicit scope. Do not broaden it, mix modes, infer another
Agent, or scan across workspaces. Ask the human only when scope is ambiguous.

Write `scope.json`:

```json
{
  "schema_version": 1,
  "agents": [
    {
      "name": "current-agent",
      "agent_id": "00000000-0000-0000-0000-000000000001",
      "authorization": "explicit_agent"
    }
  ],
  "chats": []
}
```

or:

```json
{
  "schema_version": 1,
  "agents": [],
  "chats": [
    {
      "chat_id": "00000000-0000-0000-0000-000000000000",
      "agent": "current-agent",
      "agent_id": "00000000-0000-0000-0000-000000000001",
      "authorization": "explicit_chat"
    }
  ]
}
```

Every row must name the same current Agent identity. Do not add human,
organization, or other authorization-context fields; explicit scope is the
complete authorization model.

## Collect deterministic evidence

Read [references/evidence-schema.md](references/evidence-schema.md) and
[references/runtime-evidence-adapters.md](references/runtime-evidence-adapters.md).
Locate the Skill directory, create a private timestamped artifact directory,
and keep all inputs and outputs inside it. Require directory mode `0700` and
file mode `0600`. Set `FIRST_TREE_BIN` for a channel-specific executable.

```bash
python3 "$CTVA_SKILL_DIR/scripts/context_tree_value_audit.py" export-chats \
  --artifact-root "$CTVA_ARTIFACT_DIR" \
  --scope "$CTVA_ARTIFACT_DIR/scope.json" \
  --agent-workspace "AGENT_UUID=/absolute/current/agent/workspace" \
  --output "$CTVA_ARTIFACT_DIR/chats.jsonl"

python3 "$CTVA_SKILL_DIR/scripts/context_tree_value_audit.py" collect \
  --artifact-root "$CTVA_ARTIFACT_DIR" \
  --chats "$CTVA_ARTIFACT_DIR/chats.jsonl" \
  --agent-workspace "AGENT_UUID=/absolute/current/agent/workspace" \
  --tree-root "/absolute/current/agent/bound/context-tree" \
  --output "$CTVA_ARTIFACT_DIR/candidates.jsonl"
```

There is no default lookback. Use `--days N` only when the human explicitly
wants a time-based acquisition ceiling. It limits data fetching; it does not
determine sample size or the stopping rule. Use `--now` for reproducible reruns.
Normally let the collector resolve the local evidence root from
`FIRST_TREE_PROVIDER`; use `--trace-root` only for an explicitly resolved root
for that same Runtime.

Before fully scanning a trace, require bounded metadata/current-context
preflight to establish one authorized `chatId` for the exact workspace. Never
search arbitrary full traces to discover an authorized Chat. Classify every
in-window call that references bound-Tree Markdown exactly once as
`accepted_exact`, `accepted_read_only_composite`, `unresolved_opaque`, or
`rejected_unsafe`; the four counts must conserve the attempt total. Allow only
statically closed read-only wrappers, paths, programs, and forwarded outputs.
Keep exact output/continuation pairing and reject writes, mutation, network
access, and literal Tree-external reads. Unknown or dynamic shapes remain
unresolved rather than becoming negative exposure. Missing, failed, duplicate,
pending, incomplete, or out-of-window results are unresolved and produce no
accepted read evidence. A unique, completed, non-empty, attributable result
with no explicit failure signal may remain candidate evidence even when its
provider has no separate positive-success flag.

For message metadata:

- project only a valid `metadata.contextDecision` v1 into
  `decision_receipt`;
- treat receipt absence as unknown;
- omit malformed receipts and add `context_decision_invalid`;
- never fail Chat export because analysis metadata is malformed.

## Reconstruct and judge Tasks

Read
[references/task-analysis-schema.md](references/task-analysis-schema.md), then
write exactly one `task-judgments.jsonl` row for every reconstructed Task.

A clear Task is one independently judgeable continuous work episode owned by
the audited Agent. It needs a concrete objective, material object scope,
independently judgeable outcome or terminal state, bounded source fragments
from objective through outcome, explicit ownership/objective/outcome anchors,
and one primary terminal deliverable. Otherwise mark it excluded with a
structured exclusion kind. Excluded Tasks carry no exposure or effects.

Short continuations, status prompts, context-dependent questions, merge
approval, repeated review/fix requests, and ordinary phase transitions are not
separate Tasks. Merge plan → implementation → review → QA → final delivery,
plus corrections to the same deliverable, into one episode. Split only when
there is a new objective, material scope or deliverable change, independent
outcome, and unambiguous source boundary.

For a single-Agent audit, another Agent's work is context until this Agent is
visibly assigned, transferred, or accepts an objective. Type each clear Task
from its primary terminal deliverable. Coordination is a Task only when
dispatch, handoff, gate, or terminal routing is itself the objective and
outcome.

One Chat may still contain multiple qualifying episodes. Merge across Chats
only for one PR/MR/Issue, a visible handoff, or the same objective and primary
delivery, and record the explicit shared linkage. Do not copy one read or
choice into different Tasks.

Exposure is only:

- `confirmed`, with attributable Task-window reads;
- `unresolved`, with a reason explaining the evidence gap, no reads, and no
  effects.

Do not invent `not_observed`. Missing telemetry and receipt absence are
unknown, not proof of non-use.

Effects are only `confirmed`, `constrained`, `redirected`, or `conflicted`.
Keep the original passage-level confidence as `verified` or `probable`, and
persist its five checks: real read, decision-bearing normal passage, Task
relevance, read before choice, and visible influence. `verified` requires all
five and requires every cited passage to match the bound Tree's local
`origin/HEAD` snapshot. `probable` requires the first four while visible
influence is false or unknown, and is the strongest allowed classification for
an unverified source. Do not use
`informed`, `none`, or numeric weights. Every effect needs Task-window reads,
later same-Agent choice messages, and an outcome anchor.

Do not write `support`. The reporter derives definite support from confirmed
exposure plus verified judgment; every other valid positive effect is limited
support.

## Apply Task quota and saturation

Acquire and judge at least 100 clear Tasks, with all five task types represented
in that initial cohort. Then expand by 20 clear Tasks per batch. Stop only after
two consecutive complete expansion batches add no new effect type, key
counterexample, or conclusion change.

Record `sampling_order` and any `saturation_signals` on each clear Task so the
stop is reproducible. The reporter derives effect-type novelty from actual
effects and rejects a missing or spurious `new_effect_type` annotation before
counting an empty batch. A partial run remains incomplete or continuing. Do
not turn a time bound or Chat count into a sample-size rule. Never retain,
split, or invent a weak Task to meet the quota or type coverage. If the
authorized corpus has fewer clear Tasks or genuinely lacks a type, preserve
the applicable partial status. When exposure analysis is ready, use
`minimum_not_met` or `task_type_coverage_not_met`.

## Validate and report

```bash
python3 "$CTVA_SKILL_DIR/scripts/context_tree_value_audit.py" report \
  --artifact-root "$CTVA_ARTIFACT_DIR" \
  --agent-workspace "AGENT_UUID=/absolute/current/agent/workspace" \
  --candidates "$CTVA_ARTIFACT_DIR/candidates.jsonl" \
  --task-judgments "$CTVA_ARTIFACT_DIR/task-judgments.jsonl" \
  --reviewed-baseline "$CTVA_ARTIFACT_DIR/reviewed-baseline.jsonl" \
  --evidence-output "$CTVA_ARTIFACT_DIR/evidence.jsonl" \
  --report-output "$CTVA_ARTIFACT_DIR/REPORT.md"
```

Omit `--reviewed-baseline` when no independently reviewed earlier case set
exists. When supplied, it must be a one-row, hash-anchored aggregate that
conserves its reviewed Task, effect, and support counts. The reporter renders
it in a separate historical-baseline section; it never imports those effects
into unresolved current Tasks or into current saturation.

The deterministic reporter rejects Task judgment schema v1, weak fragment-only
source objectives, missing or invalid episode ownership and anchors, reused
episode identity anchors, reads or choices outside the established episode,
unauthorized source messages, Task-window violations, unlinked cross-Chat
merges, duplicated reads/choices, invalid effects or confidence, unbound
outcome anchors, persisted support, and non-conserving aggregates.

The report must include:

- a complete inventory of all submitted/adjudicated sample rows: clear Tasks
  with boundary rationale and exposure/effects, plus excluded candidates;
- confirmed and unresolved exposure Tasks;
- effect Tasks and deduplicated independent effects;
- the four-effect distribution;
- task type × effect;
- derived definite/limited support;
- quota and saturation status;
- authorized Chat, message, trace, and coverage-gap counts;
- the four-class in-window Tree-read attempt conservation table;
- local-default-branch-match versus unverified-source counts;
- explicit language that unresolved and receipt absence are unknown;
- `N/A / pending`, without effect totals or saturation, when no clear Task has
  evidence-ready exposure;
- a separately labeled, evidence-anchored historical baseline when supplied,
  without merging it into the current rerun;
- no global effectiveness rate.

Because all authorized Chats are not an eligible value denominator, return local links
to `REPORT.md` and `evidence.jsonl`, the acquisition bound if one was supplied,
authorization mode, sample status, and any material coverage gap. Keep
artifacts private in the invoking Agent workspace and never commit them.
Describe the result as an exploratory evidence scan, not causal proof, ROI, or
an effectiveness rate.
