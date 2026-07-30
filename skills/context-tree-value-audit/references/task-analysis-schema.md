# Task, Read, and Effect Schema

Use this reference after `collect` produces `candidates.jsonl`. Task is the
judgment and counting unit. `Chat UUID @ Agent UUID` remains only the
authorization, trace-mapping, and evidence-source unit.

Write exactly one schema-v3 `task-judgments.jsonl` row for every reconstructed
Task or excluded candidate.

## Clear Task

```json
{
  "schema_version": 3,
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
      "message_ids": [
        "assignment-message-id",
        "continue-message-id",
        "outcome-message-id"
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
    "outcome_anchor_message_ids": ["outcome-message-id"],
    "continuation_message_ids": ["continue-message-id"],
    "primary_deliverable": "A decision selecting the authoritative state source.",
    "boundary_reason": "The assignment and final decision bound one continuous objective."
  },
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

A clear Task is one independently judgeable, continuous work episode owned by
the audited Agent. It requires all six gates:

1. ownership established by an assignment, transfer, or visible acceptance;
2. a concrete normalized objective;
3. a material object scope;
4. an independently judgeable outcome or terminal state;
5. bounded source fragments from objective through outcome;
6. one primary terminal deliverable.

The `episode` object makes those gates auditable. Ownership must be
`assigned`, `transferred`, or `accepted`. `assigned` and `transferred` need a
non-current-Agent ownership and objective anchor; `accepted` needs a
current-Agent ownership and objective anchor. At least one concrete objective
anchor must come from that ownership-compatible sender: non-current for
`assigned`/`transferred`, current for `accepted`. A weak assignment plus another
sender's later concrete message cannot be combined into a clear objective.
Synthesized judgment prose cannot turn a weak prompt into one. Every Task needs
one or more distinct, strictly later outcome anchors, and every outcome anchor
must be a non-empty current-Agent message. Every episode anchor must be one of
the Task's authorized source messages. Ownership and objective may use the same
handoff message; outcome and continuation anchors must remain separate from the
ownership/objective identity anchors. The Read/choice evidence window begins
only after the earliest ownership-kind-compatible ownership anchor and the
earliest ownership-compatible, non-weak objective anchor are both established;
earlier incompatible-sender ownership or weak objective anchors cannot move
that window backward.

A short continuation, status prompt, or context-dependent question is not a
clear Task by itself. Examples include `continue`, `status`, `why`, `继续`,
`做了吗`, `你在干啥`, `进展呢`, `地址呢`, `为什么`, `什么意思`,
`你这个修复什么`, `那这个呢`, `再检查`, `修一下`, and `重新看`.
Polite or modal wrappers do not make those fragments concrete:
`please continue`, `status please`, `请继续`, and `修一下吧` remain weak.
The anchored context-dependent command set also keeps deictic variants such as
`please continue fixing it`, `please fix it`, `continue the work`,
`继续修一下`, `修复一下`, `修这个`, and `帮忙修下` weak.
Edge-only Unicode punctuation/symbol decoration and closed high-frequency
modifiers do not change that result, so `“please continue”`,
`please just continue`, `请继续吧～`, and `请继续（谢谢）` remain weak.
One or more leading First Tree Agent mentions use the exact slug grammar and
stop before punctuation or adjacent prose: `@agent-one @agent-two，请继续`
remains weak, while
`@agent-one @agent-two，请继续完成状态源方案并交付独立决定` remains
concrete. Strip only those closed decorations and wrappers; a message such as
`Please continue the state-source design and deliver the authority decision`
remains concrete because the residual text names an objective and deliverable.
Merge a weak fragment into its parent episode when that parent is visible;
otherwise exclude it. Never invent the missing objective from work performed by
another Agent.

Treat one complete objective-to-outcome work item as one Task. Keep planning,
implementation, review, QA, corrections, merge approval, status questions,
and short continuations for the same deliverable in that Task. Split only when
there is a new objective, materially different scope or deliverable, an
independent outcome, and an unambiguous source boundary.

## Excluded Task

```json
{
  "schema_version": 3,
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
  "exclusion_kind": "missing_objective",
  "exclusion_reason": "No defensible objective and outcome boundary."
}
```

Excluded candidates do not contain `episode`, `read`, `effect`, or
`effect_reason`. They must contain one structured `exclusion_kind`:

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
source boundary. Keep the resulting source messages, windows, Reads, and
choices separate.

For a single-Agent audit, work assigned to another Agent is Chat context, not
this Agent's Task. Start this Agent's Task only at a visible assignment,
transfer, or acceptance. A later independent review, takeover, verification
gate, or orchestration objective may form a new owned episode when it passes
all six gates. An ordinary status check always stays in its parent episode.

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
Task window, occur no earlier than established episode ownership/objective and
no later than the episode outcome, and be assigned to only one Task.

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
non-empty outcome anchor equal to one of the episode outcome message IDs, and
one concrete summary sentence. Effect choices must be authorized Task source
messages inside the established episode. The selected Effect outcome anchor
must be no earlier than every cited Read completion and cited choice.

Ownership, objective, and outcome identity anchors cannot be copied across
different clear Tasks. One message that appears to bundle multiple objectives
does not provide an unambiguous split boundary; merge or exclude unless
separate source anchors establish the episodes. The same Read or choice cannot
be copied across Tasks.

If those conditions are not met, set `"effect": null` and include one short
`effect_reason`. Do not add `verified`, `probable`, confidence tiers, support
levels, numeric weights, or multiple Effects. A `contextDecision` receipt may
support the judgment but cannot create an Effect by itself.

## Separately reviewed historical baseline

An optional `reviewed-baseline.jsonl` contains one schema-v3 aggregate:

```json
{
  "schema_version": 3,
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

Include:

- one complete clear Task inventory with ownership, objective, scope, primary
  deliverable, outcome, Read, Effect, and evidence summary;
- each clear Task's ownership/objective/outcome anchors and boundary rationale;
- one complete excluded-candidate inventory with structured exclusion kind,
  observed scope, and reason.

The report must conserve:

- observed Read Tasks + unresolved Read Tasks = clear Tasks;
- Effect Tasks + observed Reads without an Effect = observed Read Tasks;
- the four Effect counts = Effect Tasks.

Always state the sample size and evidence gaps. Do not output a global
effectiveness rate, causal claim, or ROI.
