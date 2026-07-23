---
name: context-tree-insights
description: Produce evidence-first insights about Context Tree use when a human explicitly invokes $context-tree-insights. V0 supports only a manual, read-only retrospective of how Context Tree passages influenced decisions in explicitly authorized Chats for the current First Tree Codex Agent. Do not use for ordinary task reads, stored-tree quality audits, Tree writes, generic Chat analytics, automatic monitoring, or work involving another Agent.
---

# Context Tree Insights

## V0 capability

Run a historical value audit that connects an actual Context Tree passage read
by the invoking Agent to a later visible choice by that same Agent. Keep
deterministic collection separate from semantic judgment:

- the bundled script establishes authorization, trace mapping, reads, timing,
  visible choices, coverage, and report invariants;
- the Agent judges whether a passage was decision-bearing, relevant, and
  visibly influential.

This umbrella Skill may gain other Context Tree insight capabilities later.
V0 contains only this audit.

## Gate the run

Proceed only when a human explicitly invokes `$context-tree-insights` and asks
for the historical value audit. Do not trigger from an ordinary task, a normal
Context Tree read, or a request to audit the stored Tree itself.

Keep the run:

- manual and read-only;
- limited to one invoking Agent, its one managed workspace, and its one bound
  Context Tree;
- limited to local Codex provider traces;
- within a positive lookback window, defaulting to seven days;
- confined to a newly created artifact directory inside the invoking Agent
  workspace.

Do not modify Chat history, traces, Tree content, git state, schedules, agent
configuration, databases, or product state. The normal visible reply and the
provider's automatic trace append are not audit writes. Do not invoke another
provider adapter or scan another Agent.

## Authorize the scope

Resolve the exact current Agent name and UUID from the managed workspace
identity. Resolve the exact bound Tree root from that workspace's runtime
configuration. Reject symlinks, missing identity, an Agent mismatch, an
unbound Tree, or more than one workspace or Tree.

Choose exactly one scope mode from the human's explicit request:

1. `explicit_agent`: the human authorizes all Chats for this one current Agent.
2. `explicit_chat`: the human supplies one or more exact Chat UUIDs for this
   same current Agent, or explicitly authorizes the invoking current Chat,
   whose exact UUID comes from the runtime-injected `chatId`.

Do not infer authorization from Team visibility, Chat visibility, Agent
ownership, or access to the local trace directory. Do not combine the two
modes in one run. Ask the human when the authorization scope is ambiguous.

Write `scope.json` with one of these shapes:

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

Every entry must name the same exact current Agent identity. Each evidence unit
is one `Chat UUID @ Agent UUID`.

## Collect deterministic evidence

Locate this Skill directory, create a private timestamped artifact directory,
and keep every input and output inside it. Require mode `0700` for the
directory and `0600` for files. Set `FIRST_TREE_BIN` when the environment uses
a channel-specific executable such as `first-tree-staging`.

```bash
python3 "$CTI_SKILL_DIR/scripts/context_tree_insights.py" export-chats \
  --artifact-root "$CTI_ARTIFACT_DIR" \
  --scope "$CTI_ARTIFACT_DIR/scope.json" \
  --agent-workspace "AGENT_UUID=/absolute/current/agent/workspace" \
  --days 7 \
  --output "$CTI_ARTIFACT_DIR/chats.jsonl"

python3 "$CTI_SKILL_DIR/scripts/context_tree_insights.py" collect \
  --artifact-root "$CTI_ARTIFACT_DIR" \
  --chats "$CTI_ARTIFACT_DIR/chats.jsonl" \
  --agent-workspace "AGENT_UUID=/absolute/current/agent/workspace" \
  --tree-root "/absolute/current/agent/bound/context-tree" \
  --days 7 \
  --output "$CTI_ARTIFACT_DIR/candidates.jsonl"
```

Use `--now` for reproducible reruns and `--trace-root` only for an explicitly
resolved local Codex sessions directory.

Before a trace is fully scanned, require a bounded metadata/current-context
preflight to establish one unambiguous authorized `chatId` for the exact
workspace. Never search arbitrary full traces to discover an authorized Chat.
Treat an unmapped, ambiguous, malformed, cleaned, truncated, non-Codex,
subagent, cross-workspace, or out-of-window trace as a coverage gap. Never
replace historical tool output with the current Tree file.

Accept a Tree passage only from a successful, attributable read whose output
can be isolated. Reject or downgrade compound commands or mixed outputs that
cannot prove which bytes came from the authorized Tree node. Accept only the
documented built-in read tool identities; reject suffix lookalikes, stdin, and
extra file operands. Pair calls with their exact outputs and continuations, and
record read completion before using it as pre-choice evidence.

## Judge at passage level

Read [references/evidence-schema.md](references/evidence-schema.md) before
writing `judgments.jsonl`. Review every row whose `candidate_status` is
`candidate`; do not turn `outside_candidate_set` rows into failures.

Apply all five checks:

1. `real_read`: a successful tool result contains the cited Tree passage.
2. `decision_bearing_normal_passage`: the passage states a current decision,
   constraint, rationale, or cross-domain relationship in normal content.
3. `task_relevant`: the passage could affect a concrete choice in that task.
4. `read_before_choice`: the read completed before the cited choice.
5. `influence_visible`: a later visible message from this Agent shows the
   passage confirmed, constrained, redirected, or conflicted with the choice.

Classify conservatively:

- `verified`: all five checks are true.
- `probable`: the first four are true and the outcome aligns, but visible
  causality is incomplete.
- `unproven`: available evidence does not meet the bar; this is not proof of
  no value.

Assign one effect to a `verified` or `probable` judgment:
`confirmed`, `constrained`, `redirected`, or `conflicted`. Do not assign an
effect to `unproven`. A file read, selector, index, member route, workflow
instruction, archive, proposal, or Tree mention is not value by itself.

Minimize sensitive content in model context. Inspect only the candidate
passages and visible choices needed for the rubric. Do not print full traces,
raw evidence bundles, or long passages into the Chat.

## Validate and report

```bash
python3 "$CTI_SKILL_DIR/scripts/context_tree_insights.py" report \
  --artifact-root "$CTI_ARTIFACT_DIR" \
  --agent-workspace "AGENT_UUID=/absolute/current/agent/workspace" \
  --candidates "$CTI_ARTIFACT_DIR/candidates.jsonl" \
  --judgments "$CTI_ARTIFACT_DIR/judgments.jsonl" \
  --evidence-output "$CTI_ARTIFACT_DIR/evidence.jsonl" \
  --report-output "$CTI_ARTIFACT_DIR/REPORT.md"
```

The deterministic reporter must reject missing candidate judgments, unknown
IDs, invalid rubric/result combinations, evidence-free positive results, and
post-choice reads claimed as pre-choice.

The report must include:

- `verified`, `probable`, and `unproven` counts;
- effect distribution and representative passage-to-choice cases;
- authorized Chat, visible-message, mapped-trace, candidate, and judgment
  coverage;
- every material coverage gap and the local-Codex V0 boundary;
- an explicit statement that read counts do not equal value;
- an explicit statement that all authorized Chats are not an eligible
  denominator because historical records cannot show which tasks had relevant
  decision-bearing Tree content available.

Return local links to `REPORT.md` and `evidence.jsonl`, the exact time window
and authorization mode, and any gap that materially limits interpretation.
Keep artifacts in the invoking Agent workspace and never commit them.
