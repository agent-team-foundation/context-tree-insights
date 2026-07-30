# Task Analysis Schema

Use this reference after `collect` produces `candidates.jsonl`. The Task, not
the Chat, is the judgment and counting unit. `Chat UUID @ Agent UUID` remains
the authorization, trace-mapping, and evidence-source unit.

Write exactly one `task-judgments.jsonl` row per reconstructed continuous work
episode. Do not split tasks, exposures, and effects into separate artifact
files. Task judgment schema v2 is intentionally incompatible with
boundary-light v1 judgments.

## Clear Task

```json
{
  "schema_version": 2,
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
      "message_ids": [
        "assignment-message-id",
        "continue-message-id",
        "delivery-message-id"
      ]
    }
  ],
  "episode": {
    "ownership": {
      "kind": "assigned",
      "anchor_message_ids": ["assignment-message-id"],
      "reason": "A human assigned this objective to the audited Agent."
    },
    "objective_anchor_message_ids": ["assignment-message-id"],
    "outcome_anchor_message_ids": ["delivery-message-id"],
    "continuation_message_ids": ["continue-message-id"],
    "primary_deliverable": "A decision selecting the authoritative state source.",
    "boundary_reason": "The assignment and final decision bound one continuous objective.",
    "task_type_reason": "The primary terminal result is a design choice."
  },
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
      "choice_message_ids": ["delivery-message-id"],
      "outcome_anchor": "delivery-message-id",
      "summary": "The constraint prevented a second state source."
    }
  ]
}
```

A clear Task is one independently judgeable, continuous work episode owned by
the audited Agent. It requires all six gates:

1. ownership established by an assignment, transfer, or visible acceptance;
2. a concrete normalized objective;
3. a material object scope;
4. an independently judgeable outcome or terminal state;
5. bounded source fragments from objective through outcome;
6. one primary terminal deliverable that determines the Task type.

The `episode` object makes those gates auditable. Ownership must be
`assigned`, `transferred`, or `accepted`. `assigned` and `transferred` need a
non-current-Agent ownership and objective anchor; `accepted` needs a
current-Agent ownership and objective anchor. At least one objective-anchor
source message must itself state a concrete objective; synthesized judgment
prose cannot turn a weak prompt into one. Every Task needs a current-Agent
outcome anchor. Every episode anchor must be one of the Task's authorized source
messages, and the outcome cannot precede ownership or objective. Ownership and
objective may use the same handoff message. Continuation messages must be
recorded separately from objective and outcome anchors.

A short continuation, status prompt, or context-dependent question is not a
clear Task by itself. Examples include `continue`, `status`, `why`, `继续`,
`做了吗`, `你在干啥`, `进展呢`, `地址呢`, `为什么`, `什么意思`,
`你这个修复什么`, `那这个呢`, `再检查`, `修一下`, and `重新看`.
Polite or modal wrappers do not make those fragments concrete:
`please continue`, `status please`, `请继续`, and `修一下吧` remain weak.
The anchored context-dependent command set also keeps deictic variants such as
`please continue fixing it`, `继续修一下`, and `帮忙修下` weak.
Edge-only Unicode punctuation/symbol decoration and closed high-frequency
modifiers do not change that result, so `“please continue”`,
`please just continue`, `请继续吧～`, and `请继续（谢谢）` remain weak.
One or more leading First Tree Agent mentions use the exact slug grammar and
stop before punctuation or adjacent prose: `@agent-one @agent-two，请继续`
remains weak, while
`@agent-one @agent-two，请继续完成状态源方案并交付独立决定` remains
concrete.
Strip only those closed decorations and wrappers; a message such as
`Please continue the state-source design and deliver the authority decision`
remains concrete because the residual text names an objective and deliverable.
Merge it into its parent episode when that parent is visible; otherwise exclude
it. Never invent the missing objective from surrounding work performed by
another Agent.

Allowed `task_type` values are:

- `solution_design` — 方案设计;
- `implementation_delivery` — 实现交付;
- `review_qa_debugging` — Review、QA、排障;
- `research_explanation` — 调研、解释;
- `coordination_orchestration` — coordination whose dispatch, handoff, gate,
  or terminal routing result is itself the primary deliverable.

Choose the type from the primary terminal deliverable, not the first verb in
the conversation:

- code, UI, a PR/MR, a published artifact, or an external state change is
  `implementation_delivery`;
- a verdict, defect localization, QA result, or release gate without delivering
  the corresponding fix is `review_qa_debugging`;
- an executable option, architecture, or product decision is
  `solution_design`;
- a factual synthesis or explanation without a new design decision is
  `research_explanation`;
- ordinary status updates, reminders, merge approval, and phase transitions
  stay inside their parent episode and are not
  `coordination_orchestration`.

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
  "schema_version": 2,
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
  "exclusion_kind": "missing_objective",
  "exclusion_reason": "No defensible objective and outcome boundary."
}
```

Excluded Tasks must not contain `exposure`, `effects`, `sampling_order`, or
`saturation_signals`. They must contain one structured `exclusion_kind`:

- `greeting_or_acknowledgement`;
- `status_ping_or_continuation`;
- `context_dependent_clarification`;
- `missing_objective`;
- `missing_scope`;
- `missing_outcome`;
- `ownership_not_established`;
- `automatic_or_provider_only`;
- `ambiguous_boundary`;
- `non_independent_subphase`.

When more than one label could apply, use this precedence so reruns converge:

1. form-only exclusions: `automatic_or_provider_only`,
   `greeting_or_acknowledgement`, `status_ping_or_continuation`,
   `context_dependent_clarification`, `non_independent_subphase`;
2. `ownership_not_established`;
3. `missing_objective`;
4. `missing_scope`;
5. `missing_outcome`;
6. `ambiguous_boundary`.

An excluded row is an observed candidate, not a Task. Keep any partially known
objective/scope/outcome fields honest, and use `exclusion_reason` to identify
other passed or failed gates; do not add a partial `episode` object.

## Task reconstruction

One Chat may contain multiple Tasks, but a new message or phase does not create
a new Task. Merge:

- short continuation, status, clarification, review-again, fix-again, or merge
  messages into the active parent episode;
- plan → implementation → review → QA → final delivery for one objective and
  primary deliverable;
- corrections and revisions to that same deliverable.

Split only when all four are present: a new objective, a material scope or
deliverable change, an independently judgeable outcome, and an unambiguous
source boundary. Keep the resulting source messages, windows, reads, and
choices separate.

For a single-Agent audit, work assigned to another Agent is Chat context, not
this Agent's Task. Start this Agent's Task only at a visible assignment,
transfer, or acceptance. A later independent review, takeover, verification
gate, or coordination objective may form a new owned episode when it passes
all six gates. An ordinary status check always stays in its parent episode.

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
Task window, occur no earlier than established episode ownership/objective and
no later than the episode outcome, and be assigned to only one reconstructed
Task.

Collector command classification is not exposure by itself. For
`read_only_composite` or `output_attribution: aggregate`, inspect the recorded
passage and component paths. `auxiliary_output_possible` means the accepted
command contained safe auxiliary operations, not that their bytes were kept.
The collector removes exactly attributable static labels and emits no read ID
when dynamic diagnostic output cannot be separated. If actual Tree content is
still not attributable, keep the Task exposure unresolved.

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

`verified` also requires every cited read to carry
`tree_source.status: default_branch_match`. The collector assigns that status
only when the recorded passage matches the same node in the bound Tree's local
`origin/HEAD` snapshot. An `unverified_source` may support `probable`, never
`verified`. This is a local content match, not remote provenance.

An accepted read-only command shape can still fail `real_read` when its output
contains only status text, labels, selectors, counts, or diagnostics. Exact
trace recovery improves evidence quality; it is not the only semantic signal,
and a collector failure never reverses a separately reviewed positive case
into a zero effect.

Every effect requires read IDs, later same-Agent choice message IDs from the
Task source fragments, an outcome anchor equal to one of the episode outcome
message IDs, and a concise summary. Effect reads must be included in the Task
exposure and must complete no later than the earliest cited choice. Reads and
choices must remain inside the established episode, not merely the declared
Task window.

Ownership, objective, and outcome identity anchors cannot be copied across
different clear Tasks. One message that appears to bundle multiple objectives
does not provide an unambiguous split boundary; merge or exclude unless
separate source anchors establish the episodes.

The same read or choice cannot be copied across different reconstructed Tasks.
The reporter derives an independent effect identity from effect type, reads,
choices, and outcome anchor, so duplicate effect rows do not inflate totals.

### Separately reviewed historical baseline

Do not inject an older positive case into a current unresolved Task. If an
earlier Task-level review remains valid but its exact current collector IDs
cannot be recreated, pass an optional one-row `reviewed-baseline.jsonl` to the
reporter. It must contain:

```json
{
  "schema_version": 1,
  "basis": "separately_reviewed_task_cases",
  "reviewed_at": "RFC3339",
  "evidence_anchor": {
    "artifact_id": "opaque-reviewed-artifact-id",
    "sha256": "64-lowercase-hex"
  },
  "clear_tasks": 162,
  "effect_tasks": 37,
  "independent_effects": 37,
  "effect_counts": {
    "confirmed": 5,
    "constrained": 17,
    "redirected": 13,
    "conflicted": 2
  },
  "support_counts": {
    "definite": 24,
    "limited": 13
  }
}
```

Both count maps must conserve `independent_effects`. The baseline appears in a
separate report section and never changes current exposure, effect totals,
quota, or saturation. This preserves reviewed evidence without allowing
arbitrary effects on unresolved Tasks.

## Derived support and conservation

Never persist a `support` field in `task-judgments.jsonl`. The reporter derives:

- `definite`: confirmed exposure plus `verified`;
- `limited`: every other still-valid positive effect.

The derived effect evidence also carries `tree_source_status` so the report
separately counts local default-branch matches and unverified sources.

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

Never retain, split, or invent a weak Task to reach 100 or fill a missing type.
When the authorized corpus is smaller or genuinely lacks one of the five
types, preserve the clear/excluded judgments and the applicable partial status.
When exposure analysis is ready, report `minimum_not_met` or
`task_type_coverage_not_met`.

Unresolved exposure cannot make a batch "empty" for effect saturation. When no
clear Task has evidence-ready exposure, effect totals, distributions, support,
representatives, and saturation are all `N/A / pending`, not numeric zero. If
some clear Tasks are confirmed while others remain unresolved, observed
positive effects may be reported, but saturation remains pending.
