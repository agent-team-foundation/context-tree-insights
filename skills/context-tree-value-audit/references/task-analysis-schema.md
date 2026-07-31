# Task, Read, and Effect Schema

The audit uses three ordered stages. Task reconstruction is completed and
frozen before Tree Reads are visible to the analyst. Read attribution then
uses that frozen inventory. Effect analysis runs last and may not change either
earlier artifact.

`Chat UUID @ Agent UUID` remains the authorization, trace-mapping, and source
unit. Task is the work unit. Effect is the independently counted value unit.

## Stage 1: Task reconstruction

Run `task-source` after collection. It projects only authorized work messages:
no collector-derived Reads, passages, Tree-mention indexes, decision receipts,
choice projections, or Effect judgments are present. Original message content
is unchanged and may literally discuss Tree, Read, or Effect when that
discussion is part of the work. Reconstruct Tasks only from this message-only
artifact and do not use those literal terms as evidence that a Read or Effect
occurred.

A Task is one continuous work episode in which the audited Agent accepted a
concrete objective and produced an independently judgeable outcome. Scope and
primary deliverable may clarify the boundary but are optional.

Write one schema-v4 `task-inventory-draft.jsonl` row for every clear Task or
excluded candidate:

```json
{
  "schema_version": 4,
  "task_id": "stable-local-task-id",
  "status": "clear",
  "objective": "Choose the state authority",
  "object_scope": "state persistence",
  "primary_deliverable": "A decision selecting one state source",
  "outcome": "Kept the existing state source",
  "started_at": "RFC3339",
  "ended_at": "RFC3339",
  "source_fragments": [
    {
      "audit_id": "CHAT_UUID@AGENT_UUID",
      "message_ids": [
        "objective-message-id",
        "continuation-message-id",
        "outcome-message-id"
      ]
    }
  ],
  "objective_source_message_ids": ["objective-message-id"],
  "outcome_source_message_ids": ["outcome-message-id"]
}
```

`objective`, `outcome`, source fragments, and objective/outcome message IDs are
required. `object_scope` and `primary_deliverable` may be null. `started_at`
must equal the earliest objective source; `ended_at` must equal the latest
outcome source. Outcome sources must be non-empty messages authored by the
audited Agent and must strictly follow all objective sources.

The Task inventory must not contain `episode`, ownership categories,
continuation IDs, boundary rationale, Read, Effect, confidence, support,
sampling, or task-type fields. Assignment, transfer, and visible acceptance are
all expressed by the objective source messages rather than a separate
ownership taxonomy.
The analyst is responsible for judging from those work messages that the
audited Agent received or accepted the objective. The reporter validates source
identity, ordering, and the audited Agent's outcome; it does not infer the
semantic addressee of arbitrary message prose.

Use an excluded row when a defensible Task cannot be reconstructed:

```json
{
  "schema_version": 4,
  "task_id": "stable-local-candidate-id",
  "status": "excluded",
  "objective": null,
  "object_scope": "unclear scope",
  "outcome": null,
  "started_at": "RFC3339",
  "ended_at": "RFC3339",
  "source_fragments": [
    {
      "audit_id": "CHAT_UUID@AGENT_UUID",
      "message_ids": ["message-id"]
    }
  ],
  "exclusion_kind": "missing_objective",
  "exclusion_reason": "No defensible objective and outcome boundary."
}
```

Allowed exclusion kinds:

- `greeting_or_acknowledgement`;
- `status_ping_or_continuation`;
- `context_dependent_clarification`;
- `missing_objective`;
- `missing_outcome`;
- `ownership_not_established`;
- `automatic_or_provider_only`;
- `ambiguous_boundary`;
- `non_independent_subphase`.

Apply this precedence when more than one fits:

1. form-only exclusions;
2. `ownership_not_established`;
3. `missing_objective`;
4. `missing_outcome`;
5. `ambiguous_boundary`.

An excluded row is an observed candidate, not a Task. It contains no clear-Task
sources, primary deliverable, Read, or Effect analysis.

### Task boundaries

Keep planning, implementation, review, QA, corrections, merge approval, status
questions, and short continuations inside one Task when they serve the same
objective and outcome. Split only when a new objective, material scope or
deliverable change, independent outcome, and unambiguous source boundary are
all present.

Weak fragments such as `continue`, `status`, `why`, `please continue`,
`please fix it`, `继续`, `做了吗`, `修一下`, and mention-decorated equivalents
cannot establish a Task objective by themselves. Merge them into a visible
parent episode or exclude them. A concrete message that contains `continue`
but names its objective and outcome remains eligible.

For a single-Agent audit, another Agent's work is context until the audited
Agent receives or visibly accepts an objective. Another Agent's later message
cannot serve as this Agent's outcome.

Merge fragments across Chats only when every fragment carries the same
explicit linkage:

```json
{
  "linkage": {
    "kind": "work_item",
    "key": "repo#123"
  }
}
```

Allowed kinds are `work_item`, `explicit_handoff`, and
`same_objective_delivery`. Topical similarity alone is insufficient.

### Freeze

`freeze-tasks` validates the draft against the message-only Task source,
normalizes row order, computes one SHA-256 digest, and writes
`task-inventory.jsonl`. Every frozen row carries the same
`inventory_sha256`.

The digest is an internal integrity fence, not a user-facing evidence concept.
If Task reconstruction changes, create a new frozen inventory and rerun Read
and Effect analysis. Never edit the frozen inventory during later stages.

## Stage 2: Read attribution

Write exactly one schema-v4 `read-attributions.jsonl` row for every clear Task:

```json
{
  "schema_version": 4,
  "inventory_sha256": "64-lowercase-hex",
  "task_id": "stable-local-task-id",
  "status": "observed",
  "read_ids": ["read-id"],
  "reason": null
}
```

Read has two states:

- `observed` — one or more attributable Task-window Read IDs exist;
- `unresolved` — historical evidence cannot resolve the Read; `read_ids` is
  empty and `reason` explains the gap.

Zero attributed Reads are represented as unresolved unless the available
historical evidence can support a stronger interpretation. Do not emit
`not_observed`, `unused`, or another negative-value state. Missing telemetry
and receipt absence remain unknown.

Every observed Read must belong to one source Chat, start and complete inside
the frozen Task window, and be attributed to only one Task. Read attribution
cannot create, delete, merge, split, or resize a Task.

Collector command classification is not a Read by itself. For aggregate or
read-only-composite evidence, inspect the retained passage and component paths.
If actual Tree content cannot be attributed, keep the Task unresolved.

## Stage 3: Effect analysis

Write exactly one schema-v4 `effect-judgments.jsonl` row for every clear Task:

```json
{
  "schema_version": 4,
  "inventory_sha256": "64-lowercase-hex",
  "task_id": "stable-local-task-id",
  "effects": [
    {
      "type": "constrained",
      "read_ids": ["read-id"],
      "choice_message_ids": ["choice-message-id"],
      "outcome_message_id": "outcome-message-id",
      "summary": "The constraint ruled out a second state source."
    }
  ],
  "effect_reason": null
}
```

A Task has zero or more Effects. Each Effect independently binds supporting
Reads, one or more later same-Agent choices, a same-Agent outcome message, and
one summary. Valid types are:

- `confirmed` — removed material uncertainty and justified keeping a choice;
- `constrained` — ruled out an option or narrowed the acceptable boundary;
- `redirected` — changed the intended approach;
- `conflicted` — exposed a conflict that still required resolution.

Record an Effect only when:

1. a real Read contains relevant normal Tree content;
2. every cited Read completes before the earliest cited choice;
3. the later same-Agent choice or outcome reasonably shows the Effect;
4. no more direct user instruction or other evidence fully explains it.

The same Read may support multiple distinct choices and therefore multiple
Effects. One choice message cannot be reused across Effects. Outcome messages
may be shared when distinct choices converge on one later result. Effects may
bind intermediate same-Agent outcomes inside the Task; they do not have to use
the Task's terminal outcome source.

When no Effect is defensible, set `"effects": []` and include one short
`effect_reason`. An unresolved Read must have no Effects. Do not add
`verified`, `probable`, confidence tiers, support levels, rubrics, or numeric
weights. A `contextDecision` receipt may support judgment but cannot create an
Effect by itself.

## Separately reviewed historical baseline

An optional schema-v4 baseline remains separate from the current rerun:

```json
{
  "schema_version": 4,
  "basis": "separately_reviewed_task_cases",
  "reviewed_at": "RFC3339",
  "evidence_anchor": {
    "artifact_id": "opaque-reviewed-artifact-id",
    "sha256": "64-lowercase-hex"
  },
  "clear_tasks": 44,
  "effect_tasks": 16,
  "effects": 19,
  "effect_counts": {
    "confirmed": 3,
    "constrained": 9,
    "redirected": 6,
    "conflicted": 1
  }
}
```

Effect counts conserve `effects`; `effect_tasks` cannot exceed clear Tasks or
total Effects.

## Reporting

Report every available Task in the authorized acquisition bound. There is no
minimum Task quota, task-type gate, batch expansion, or saturation status.

The report conserves:

- observed Read Tasks + unresolved Read Tasks = clear Tasks;
- Effect Tasks + observed Read without Effect = observed Read Tasks;
- the four Effect counts = total Effects;
- total Effects is greater than or equal to Effect Tasks.

Always show both Effect Tasks and total Effects. State sample size and evidence
gaps. Never output a global effectiveness rate, causal claim, or ROI.
