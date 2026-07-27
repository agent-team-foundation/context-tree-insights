# Task Analysis Schema

Use this reference after `collect` produces `candidates.jsonl`. The Task, not
the Chat, is the judgment and counting unit. `Chat UUID @ Agent UUID` remains
the authorization, trace-mapping, and evidence-source unit.

Write exactly one `task-judgments.jsonl` row per reconstructed Task. Do not
split tasks, exposures, and effects into separate artifact files.

## Clear Task

```json
{
  "schema_version": 1,
  "task_id": "stable-local-task-id",
  "status": "clear",
  "objective": "Choose the state authority",
  "object_scope": "state persistence",
  "outcome": "Kept the existing state source",
  "task_type": "solution_design",
  "started_at": "RFC3339",
  "ended_at": "RFC3339",
  "source_fragments": [
    {
      "audit_id": "CHAT_UUID@AGENT_UUID",
      "message_ids": ["message-id"]
    }
  ],
  "sampling_order": 1,
  "saturation_signals": [],
  "exposure": {
    "status": "confirmed",
    "read_ids": ["read-id"],
    "reason": null
  },
  "effects": [
    {
      "effect": "constrained",
      "original_judgment": "verified",
      "rubric": {
        "real_read": true,
        "decision_bearing_normal_passage": true,
        "task_relevant": true,
        "read_before_choice": true,
        "influence_visible": true
      },
      "read_ids": ["read-id"],
      "choice_message_ids": ["message-id"],
      "outcome_anchor": "message-id-or-stable-outcome-reference",
      "summary": "The constraint prevented a second state source."
    }
  ]
}
```

A clear Task requires a concrete objective, object scope, outcome, start/end
window, and source messages. If any of those boundaries cannot be stated
honestly, use an excluded Task.

Allowed `task_type` values are:

- `solution_design` — 方案设计;
- `implementation_delivery` — 实现交付;
- `review_qa_debugging` — Review、QA、排障;
- `research_explanation` — 调研、解释;
- `coordination_progress` — 协调推进.

`sampling_order` is the acquisition order among clear Tasks and must be
unique and contiguous from 1. `saturation_signals` may contain only
`new_effect_type`, `key_counterexample`, or `conclusion_change`.
`new_effect_type` is not a free-form annotation: every complete expansion
batch must declare it exactly when that batch contains an effect type not seen
in the cumulative earlier sample. Missing or spurious declarations are
rejected.

## Excluded Task

```json
{
  "schema_version": 1,
  "task_id": "stable-local-task-id",
  "status": "excluded",
  "objective": null,
  "object_scope": "unclear scope",
  "outcome": null,
  "task_type": null,
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

Excluded Tasks must not contain `exposure`, `effects`, `sampling_order`, or
`saturation_signals`.

## Task reconstruction

One Chat may contain multiple Tasks. Keep their source messages, windows,
reads, and choices separate.

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
claim cross-Chat linkage.

Every source message must belong to the referenced authorized Chat-Agent
evidence row and fall inside the Task window. The Task window must remain
inside any explicit acquisition bound.

## Exposure

Exposure has only two states:

- `confirmed` — one or more attributable `read_ids` are available;
- `unresolved` — historical evidence cannot resolve exposure; include a
  concrete `reason`, keep `read_ids` empty, and keep `effects` empty.

Do not use `not_observed`. Missing telemetry and an absent decision receipt are
unknown, not evidence that the Tree was not read or did not matter. An
`unresolved` Task is never placed in an "unused" denominator.

Every exposure read must belong to a source Chat, start and complete inside the
Task window, and be assigned to only one reconstructed Task.

## Effects and original judgment

Effects use only:

- `confirmed`;
- `constrained`;
- `redirected`;
- `conflicted`.

Do not use `informed`, `none`, or a numeric weight. `original_judgment` reuses
`verified` and `probable`, and every effect persists the five checks that make
that classification reproducible:

- `real_read`: a successful tool result contains the cited Tree passage;
- `decision_bearing_normal_passage`: the passage states a current decision,
  constraint, rationale, or cross-domain relationship in normal content;
- `task_relevant`: the passage can affect a concrete choice in this Task;
- `read_before_choice`: every cited read completes before the earliest cited
  choice;
- `influence_visible`: a later visible same-Agent message shows the passage
  confirmed, constrained, redirected, or conflicted with the choice.

Use `verified` only when all five checks are `true`. Use `probable` only when
the first four checks are `true` and `influence_visible` is `false` or `null`
because the aligned outcome does not expose complete causality. Do not soften a
failed real-read, normal-passage, relevance, or timing check into `probable`.

Every effect requires read IDs, later same-Agent choice message IDs, a
non-empty outcome anchor, and a concise summary. Effect reads must be included
in the Task exposure and must complete no later than the earliest cited choice.

The same read or choice cannot be copied across different reconstructed Tasks.
The reporter derives an independent effect identity from effect type, reads,
choices, and outcome anchor, so duplicate effect rows do not inflate totals.

## Derived support and conservation

Never persist a `support` field in `task-judgments.jsonl`. The reporter derives:

- `definite`: confirmed exposure plus `verified`;
- `limited`: every other still-valid positive effect.

The report must conserve:

- confirmed exposure Tasks + unresolved exposure Tasks = clear Tasks;
- effect Tasks ≤ clear Tasks;
- the sum of task type × effect cells = independent effects.

## Task quota and saturation

Start with at least 100 clear Tasks and represent all five task types in that
initial cohort. Then expand by 20 clear Tasks at a time. Stop only after two
consecutive complete expansion batches contain no
`new_effect_type`, `key_counterexample`, or `conclusion_change`.

The reporter derives new effect types from the Task effects and cross-validates
the batch annotation before counting an empty batch. A newly observed effect
type therefore resets the consecutive-empty counter even when an auditor
forgets the annotation; the missing annotation is rejected rather than silently
declaring saturation.

A partial run is reported as incomplete or continuing; it is not silently
promoted to a stable rate. If two empty expansion batches establish saturation,
the validator rejects Task rows beyond that reproducible stop point.
