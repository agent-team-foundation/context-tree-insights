# Task, Read, and Effect Schema

Use this reference after `collect` produces `candidates.jsonl`. Task is the
judgment and counting unit. `Chat UUID @ Agent UUID` remains only the
authorization, trace-mapping, and evidence-source unit.

Write exactly one schema-v2 `task-judgments.jsonl` row for every reconstructed
Task or excluded candidate.

## Clear Task

```json
{
  "schema_version": 2,
  "task_id": "stable-local-task-id",
  "status": "clear",
  "objective": "Choose the state authority",
  "object_scope": "state persistence",
  "outcome": "Kept the existing state source",
  "started_at": "RFC3339",
  "ended_at": "RFC3339",
  "source_fragments": [
    {
      "audit_id": "CHAT_UUID@AGENT_UUID",
      "message_ids": ["assignment-message-id", "outcome-message-id"]
    }
  ],
  "read": {
    "status": "observed",
    "read_ids": ["read-id"],
    "reason": null
  },
  "effect": {
    "type": "constrained",
    "read_ids": ["read-id"],
    "choice_message_ids": ["outcome-message-id"],
    "outcome_anchor": "outcome-message-id",
    "summary": "The constraint ruled out a second state source."
  },
  "effect_reason": null
}
```

A clear Task requires a concrete objective, material object scope,
independently judgeable outcome, bounded start/end window, and authorized
source messages.

Treat one complete objective-to-outcome work item as one Task. Keep planning,
implementation, review, QA, corrections, merge approval, status questions,
and short continuations for the same deliverable in that Task. Split only when
there is a new objective, materially different scope or deliverable, an
independent outcome, and an unambiguous source boundary.

## Excluded Task

```json
{
  "schema_version": 2,
  "task_id": "stable-local-task-id",
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
  "exclusion_reason": "No defensible objective and outcome boundary."
}
```

Excluded Tasks do not contain `read`, `effect`, or `effect_reason`.

## Cross-Chat Task

Merge fragments from more than one Chat only when every fragment carries the
same explicit linkage:

```json
{
  "linkage": {
    "kind": "work_item",
    "key": "repo#123"
  }
}
```

Allowed linkage kinds are:

- `work_item` for one PR, MR, or Issue;
- `explicit_handoff` for a visible handoff;
- `same_objective_delivery` for the same objective and primary delivery.

The reporter rejects an unlinked cross-Chat Task. A single-Chat Task must not
claim cross-Chat linkage. Every source message must belong to the referenced
authorized Chat-Agent evidence row and fall inside the Task and acquisition
windows.

## Read

Read has only two states:

- `observed` — one or more attributable Task-window `read_ids` exist;
- `unresolved` — historical evidence cannot resolve the Read; include a short
  `reason`, keep `read_ids` empty, and keep Effect null.

Do not use `confirmed`, `not_observed`, `unused`, or a negative-value state.
Missing telemetry and an absent decision receipt are unknown. An unresolved
Read is never evidence that the Tree was not read or had no value.

Every observed Read must belong to a source Chat, start and complete inside the
Task window, and be assigned to only one Task.

Collector command classification is not a Read by itself. For
`read_only_composite` or `output_attribution: aggregate`, inspect the recorded
passage and component paths. If actual Tree content is not attributable, keep
the Read unresolved.

## Effect

Effect is either null or one object whose `type` is:

- `confirmed` — removed material uncertainty and justified keeping the choice;
- `constrained` — ruled out an option or narrowed the acceptable boundary;
- `redirected` — changed the intended approach;
- `conflicted` — exposed a conflict that still required resolution.

Record an Effect only when all four conditions hold:

1. a real Read contains a relevant normal Tree decision, constraint, rationale,
   or cross-domain relationship;
2. every cited Read completes before the earliest cited choice;
3. the later same-Agent choice or outcome reasonably shows one of the four
   effects;
4. no more direct user instruction or other evidence fully explains the
   result.

Every Effect requires observed Read IDs, later same-Agent choice message IDs, a
non-empty outcome anchor, and one concrete summary sentence. The same Read or
choice cannot be copied across Tasks.

If those conditions are not met, set `"effect": null` and include one short
`effect_reason`. Do not add `verified`, `probable`, confidence tiers, support
levels, numeric weights, or multiple Effects. A `contextDecision` receipt may
support the judgment but cannot create an Effect by itself.

## Separately reviewed historical baseline

An optional `reviewed-baseline.jsonl` contains one schema-v2 aggregate:

```json
{
  "schema_version": 2,
  "basis": "separately_reviewed_task_cases",
  "reviewed_at": "RFC3339",
  "evidence_anchor": {
    "artifact_id": "opaque-reviewed-artifact-id",
    "sha256": "64-lowercase-hex"
  },
  "clear_tasks": 44,
  "effect_tasks": 16,
  "effect_counts": {
    "confirmed": 2,
    "constrained": 8,
    "redirected": 5,
    "conflicted": 1
  }
}
```

The Effect counts must conserve `effect_tasks`. The reporter keeps the
baseline separate from the current rerun.

## Reporting

Report every available clear Task and excluded candidate in the authorized
acquisition bound. There is no minimum Task quota, task-type coverage gate,
batch expansion, or saturation status.

The report must conserve:

- observed Read Tasks + unresolved Read Tasks = clear Tasks;
- Effect Tasks + observed Reads without an Effect = observed Read Tasks;
- the four Effect counts = Effect Tasks.

Always state the sample size and evidence gaps. Do not output a global
effectiveness rate, causal claim, or ROI.
