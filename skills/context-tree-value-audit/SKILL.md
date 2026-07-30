---
name: context-tree-value-audit
description: Audit how Context Tree reads affected complete work Tasks when a human explicitly invokes $context-tree-value-audit in Codex or /context-tree-value-audit in Claude. The audit is evidence-first, manual, read-only, limited to explicitly authorized Chats for the current First Tree Agent, and reports the available sample without a minimum Task quota. Do not use for ordinary task reads, stored-tree audits, Tree writes, generic Chat analytics, monitoring, or another Agent.
---

# Context Tree Value Audit

## Capability

Run a manual and read-only retrospective that reconstructs single-Agent-owned
continuous Tasks from authorized Chats, determines whether a Tree Read is
observed or unresolved, and reports zero or more independent Effects where a
Read reasonably confirmed, constrained, redirected, or conflicted with later
choices.

Keep three analysis stages strictly ordered:

- reconstruct Task from message-only work evidence;
- freeze the Task inventory before any Read is visible to the analyst;
- attribute Reads, then analyze zero or more Effects without changing Task
  boundaries.

`Chat UUID @ Agent UUID` remains the authorization and evidence-source unit.
Task is the work unit. Effect is the independently counted value unit. The
bundled script performs deterministic projection, freezing, reference
validation, deduplication, conservation checks, and reporting. A Read or
decision receipt is evidence, not server-verified causality.

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
create a minimum sample requirement. Use `--now` for reproducible reruns.
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

## Reconstruct Tasks, then attribute Reads, then judge Effects

Read
[references/task-analysis-schema.md](references/task-analysis-schema.md).

First project a message-only source. This output deliberately excludes
collector-derived Reads, passages, Tree-mention indexes, decision receipts,
choice projections, and Effect judgments. It retains original work-message
content verbatim, including literal Tree, Read, or Effect discussion when that
discussion is part of the objective:

```bash
python3 "$CTVA_SKILL_DIR/scripts/context_tree_value_audit.py" task-source \
  --artifact-root "$CTVA_ARTIFACT_DIR" \
  --agent-workspace "AGENT_UUID=/absolute/current/agent/workspace" \
  --candidates "$CTVA_ARTIFACT_DIR/candidates.jsonl" \
  --output "$CTVA_ARTIFACT_DIR/task-source.jsonl"
```

During Task reconstruction, read only `task-source.jsonl`. Do not inspect
`candidates.jsonl`, trace evidence, Reads, receipts, choices, or any anticipated
Effect. Write one schema-v4 `task-inventory-draft.jsonl` row for every clear
Task or excluded candidate, then freeze it:

```bash
python3 "$CTVA_SKILL_DIR/scripts/context_tree_value_audit.py" freeze-tasks \
  --artifact-root "$CTVA_ARTIFACT_DIR" \
  --agent-workspace "AGENT_UUID=/absolute/current/agent/workspace" \
  --task-source "$CTVA_ARTIFACT_DIR/task-source.jsonl" \
  --task-inventory-draft "$CTVA_ARTIFACT_DIR/task-inventory-draft.jsonl" \
  --task-inventory-output "$CTVA_ARTIFACT_DIR/task-inventory.jsonl"
```

A clear Task is one independently judgeable continuous work episode owned by
the audited Agent. It needs a concrete objective, independently judgeable
outcome, bounded source fragments, and explicit objective/outcome sources.
Material scope and primary deliverable help clarify boundaries but are
optional. Otherwise mark the candidate excluded with a structured exclusion
kind.

Short continuations, status prompts, context-dependent questions, merge
approval, repeated review/fix requests, and ordinary phase transitions are not
separate Tasks. Merge plan → implementation → review → QA → final delivery,
plus corrections to the same deliverable, into one episode. Split only when
there is a new objective, material scope or deliverable change, independent
outcome, and unambiguous source boundary.

For a single-Agent audit, another Agent's work is context until this Agent
receives or visibly accepts an objective. A later independent review, takeover,
verification gate, or orchestration objective may form a new episode only when
it passes every clear-Task gate.
Judge that acceptance from the work messages themselves. The reporter checks
source identity, ordering, and a same-Agent outcome, but does not infer who
arbitrary prose addresses.

One Chat may contain multiple Tasks. Merge across Chats only for one PR/MR/
Issue, a visible handoff, or the same objective and primary delivery, and
record the explicit shared linkage.

After freeze, do not edit Task rows or boundaries. Write exactly one
schema-v4 `read-attributions.jsonl` row for every clear Task. Each row carries
the frozen `inventory_sha256`.

Read is only:

- `observed`, with attributable Task-window reads;
- `unresolved`, with a reason explaining the evidence gap, no reads, and no
  Effect.

Do not invent `not_observed`. Missing telemetry and receipt absence are
unknown, not proof of non-use.

Then write exactly one schema-v4 `effect-judgments.jsonl` row for every clear
Task, carrying the same inventory digest. Each Task has zero or more Effects;
each Effect has exactly one type: `confirmed`, `constrained`, `redirected`, or
`conflicted`. Record one only when all four conditions hold:

1. a real Read contains a relevant normal Tree decision or constraint;
2. the Read completes before the cited choice;
3. the later same-Agent choice or outcome reasonably shows one of the four
   effects;
4. no more direct user instruction or other evidence fully explains the
   result.

Every Effect needs attributed Read IDs, later same-Agent choice message IDs,
a same-Agent outcome message, and a concise summary. The same Read may support
multiple distinct choices, but one choice cannot be reused across Effects. If
the evidence is insufficient, use an empty Effect list and record one short
reason. Do not add confidence tiers, support levels, numeric weights,
`verified`, or `probable`. A decision receipt may support the judgment but
cannot create an Effect by itself.

Report every available Task in the authorized acquisition bound. There is no
minimum Task quota, task-type coverage gate, batch-expansion rule, or saturation
state. State the sample size and evidence gaps so readers can limit the
conclusion to the sampled scope.

## Validate and report

```bash
python3 "$CTVA_SKILL_DIR/scripts/context_tree_value_audit.py" report \
  --artifact-root "$CTVA_ARTIFACT_DIR" \
  --agent-workspace "AGENT_UUID=/absolute/current/agent/workspace" \
  --candidates "$CTVA_ARTIFACT_DIR/candidates.jsonl" \
  --task-inventory "$CTVA_ARTIFACT_DIR/task-inventory.jsonl" \
  --read-attributions "$CTVA_ARTIFACT_DIR/read-attributions.jsonl" \
  --effect-judgments "$CTVA_ARTIFACT_DIR/effect-judgments.jsonl" \
  --evidence-output "$CTVA_ARTIFACT_DIR/evidence.jsonl" \
  --report-output "$CTVA_ARTIFACT_DIR/REPORT.md"
```

Optionally supply a v4 `--reviewed-baseline` when an independently reviewed
earlier case set exists. The reporter keeps its hash-anchored Task and Effect
counts separate from the current rerun.

The deterministic pipeline rejects old combined judgment schemas, Task drafts
that contain Read/Effect fields, weak fragment-only objectives, missing or
invalid objective/outcome sources, reused identity sources, changed inventory
digests, Reads or choices outside the frozen Task, unauthorized source
messages, Task-window violations, unlinked cross-Chat merges, duplicated Reads
across Tasks, reused choices across Effects, invalid Effects, invalid outcome
messages, superseded judgment fields, and non-conserving aggregates.

The report must include:

- a complete frozen inventory of clear Tasks and excluded candidates with
  structured exclusion reasons;
- observed and unresolved Read Tasks;
- Effect Tasks, total Effects, and observed Reads without an Effect;
- the four-Effect distribution over total Effects;
- every clear Task's Read and zero-or-more Effect results;
- every excluded Task's reason;
- authorized Chat, message, trace, and coverage-gap counts;
- the four-class in-window Tree-read attempt conservation table;
- explicit language that unresolved and receipt absence are unknown;
- a separately labeled, evidence-anchored historical baseline when supplied,
  without merging it into the current rerun;
- no global effectiveness rate.

Because all authorized Chats are not an eligible value denominator, return local links
to `REPORT.md` and `evidence.jsonl`, the acquisition bound if one was supplied,
authorization mode, sample size, and any material coverage gap. Keep
artifacts private in the invoking Agent workspace and never commit them.
Describe the result as a sampled evidence report, not causal proof, ROI, or an
effectiveness rate.
