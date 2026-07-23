# Evidence and Judgment Schema

Use this reference only after deterministic collection produces
`candidates.jsonl`. Do not manually rewrite collected passages, paths, IDs, or
timestamps.

## Contents

- [Audit unit and authorization](#audit-unit-and-authorization)
- [Candidate evidence](#candidate-evidence)
- [Judgment evidence](#judgment-evidence)
- [Review order](#review-order)

## Audit unit and authorization

One audit unit is the exact pair:

```text
CHAT_UUID@AGENT_UUID
```

Every unit in one V0 run must use the same invoking Agent UUID, managed
workspace, and bound Tree. Allowed authorization values are:

- `explicit_agent`: the human explicitly requested all Chats for the current
  Agent;
- `explicit_chat`: the human explicitly supplied this exact Chat UUID or
  authorized the invoking current Chat resolved from runtime `chatId`.

These values record consent, not inferred ownership. A run uses one mode only.

## Candidate evidence

`collect` emits one JSON object per authorized audit unit:

```json
{
  "schema_version": 1,
  "audit_id": "CHAT_UUID@AGENT_UUID",
  "chat": {
    "chat_id": "CHAT_UUID",
    "title": "Chat topic",
    "authorization": "explicit_chat",
    "source_agent": "agent-name",
    "source_agent_id": "AGENT_UUID",
    "message_count": 12
  },
  "window": {
    "start": "RFC3339",
    "end": "RFC3339"
  },
  "tree_identity": "tree-opaque-hash",
  "candidate_status": "candidate",
  "mapped_trace_files": ["trace-opaque-hash"],
  "reads": [
    {
      "read_id": "stable-id",
      "timestamp": "RFC3339",
      "completed_at": "RFC3339",
      "session_file": "trace-opaque-hash",
      "call_id": "provider-call-id",
      "tool_name": "exec_command",
      "reader_agent_id": "AGENT_UUID",
      "tree_identity": "tree-opaque-hash",
      "node_paths": ["system/example.md"],
      "content_class_hint": "normal",
      "command": "normalized read descriptor",
      "command_truncated": false,
      "passage": "actual recorded tool output",
      "passage_truncated": false,
      "success": true
    }
  ],
  "visible_choice_candidates": [
    {
      "message_id": "message-id",
      "created_at": "RFC3339",
      "sender_id": "AGENT_UUID",
      "content": "visible later output"
    }
  ],
  "visible_tree_mentions": [],
  "coverage_gaps": []
}
```

`tree_identity` is a deterministic opaque identity for the exact
Agent/workspace-bound Tree. It is not an absolute path. The audit-row and
read-level values must match.

`content_class_hint` is path-based triage, not a semantic verdict. Verify the
cited passage itself. A qualifying passage must be isolated from one successful
read of the authorized bound Tree; mixed or compound output cannot qualify
merely because it contains an authorized `.md` path. Tool names must exactly
match the documented built-in read tools; suffix lookalikes, stdin, and extra
file operands are not isolated reads.

`mapped_trace_files` and the compatibility-named `session_file` field contain
opaque `trace-*` identities, never local filesystem paths. They identify only
local root Codex sessions that pass a bounded preflight for the exact workspace
and one authorized runtime-injected `chatId`. An unauthorized, ambiguous, or
unmapped trace must not be scanned for content. `reader_agent_id` must equal
`source_agent_id`.

`visible_choice_candidates` contains only later visible messages authored by
that same Agent. Human or other-Agent messages cannot establish this Agent's
influence.

`outside_candidate_set` means collection found neither a successful qualifying
Tree read nor a visible Tree-influence signal. It is not `unproven`, evidence
of no value, or an eligible denominator.

## Judgment evidence

Create exactly one JSONL row for every `candidate`:

```json
{
  "audit_id": "CHAT_UUID@AGENT_UUID",
  "result": "verified",
  "effect": "constrained",
  "rubric": {
    "real_read": true,
    "decision_bearing_normal_passage": true,
    "task_relevant": true,
    "read_before_choice": true,
    "influence_visible": true
  },
  "read_ids": ["stable-read-id"],
  "choice_message_ids": ["message-id"],
  "decision_theme": "Concise decision theme",
  "summary": "The passage narrowed the implementation to the existing state source.",
  "representative": true,
  "coverage_gaps": []
}
```

### Results

- `verified`: every rubric field is `true`.
- `probable`: the first four fields are `true`; `influence_visible` is `false`
  or `null` because the aligned outcome does not expose complete causality.
- `unproven`: available evidence does not close the claim. Set `effect` to
  `null`.

Use `null` for a genuinely unknowable rubric fact and `false` for contrary
evidence. Do not use `probable` to soften a failed real-read,
normal-passage, task-relevance, or pre-choice check.

### Effects

Use one effect for `verified` and `probable` only:

- `confirmed`: corroborated an already selected direction;
- `constrained`: narrowed scope or prevented an invalid extension;
- `redirected`: changed the direction or implementation path;
- `conflicted`: exposed a conflict between the choice and current normal
  content.

Both positive results require at least one successful `read_id` and one
same-Agent `choice_message_id`. When `read_before_choice` is true, every cited
read needs a completion time no later than the earliest cited choice. A known
post-choice read cannot be positive evidence.

## Review order

For each candidate:

1. Verify the referenced successful read contains the exact cited passage.
2. Identify the current decision, constraint, rationale, or cross-domain
   relationship in normal content. Indexes, workflow instructions, member
   routing, archives, and proposals cannot qualify alone.
3. State the concrete task choice the passage could affect.
4. Compare the read completion and visible-message timestamps.
5. Cite the later same-Agent message that exposes or aligns with the effect.
6. Choose the conservative result and preserve every missing or truncated
   evidence item in `coverage_gaps`.

Do not infer hidden reasoning. An aligned outcome without visible causality is
at most `probable`. Summarize passages in the report instead of copying long
raw content.
