# Collector Evidence Schema

This reference defines the deterministic collector boundary. Task
reconstruction and semantic judgment live in
[task-analysis-schema.md](task-analysis-schema.md).

## Authorization unit

One collector unit is:

```text
CHAT_UUID@AGENT_UUID
```

Every unit in one run uses the same invoking Agent UUID, managed workspace, and
bound Tree. Allowed authorization values are:

- `explicit_agent`: the human explicitly authorized all Chats for the current
  Agent;
- `explicit_chat`: the human supplied exact Chat UUIDs for the current Agent or
  authorized the invoking Chat resolved from runtime `chatId`.

These values record consent, not inferred ownership. A run uses one mode only.
The Chat-Agent pair remains the authorization, source, and trace-mapping unit;
it is not the value-counting unit.

## Chat export

`export-chats` writes authorized visible messages. Each message contains only
its ID, timestamp, sender identity/kind, visible content, and an optional
`decision_receipt`.

When `metadata.contextDecision` is a valid v1 receipt, the export retains only:

```json
{
  "version": 1,
  "effect": "constrained",
  "summary": "The Tree narrowed the acceptable implementation.",
  "evidence": [
    {
      "repoUrl": "https://github.com/example/context-tree",
      "commit": "0123456789abcdef0123456789abcdef01234567",
      "nodePath": "system/example.md",
      "heading": "Decision"
    }
  ]
}
```

No other message metadata is copied. Valid effects are `confirmed`,
`constrained`, `redirected`, and `conflicted`; evidence contains one to three
rows, a 40-character Git commit, and a relative Markdown node path.
`repoUrl` must be a remote repository identity with at least an owner/group
and repository path. HTTP(S) identities must not contain user info; SSH
identities may use only the conventional `git` user; local paths, `file:`
URLs, loopback hosts, credentials, query strings, and fragments are malformed.
Rejected values are never echoed into artifacts or diagnostics.

Receipt absence is unknown and creates no negative diagnostic. A malformed
receipt is omitted and adds `context_decision_invalid` to the Chat coverage
gaps. It never blocks Chat export or the full audit.

## Candidate evidence

`collect` emits one JSON object per authorized Chat-Agent unit:

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
    "start": null,
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
  "visible_messages": [
    {
      "message_id": "message-id",
      "created_at": "RFC3339",
      "sender_id": "sender-id",
      "content": "visible message",
      "decision_receipt": null
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

`window.start` is `null` unless the human supplied `--days`. The option is an
acquisition bound only; it does not decide sample size or the stopping rule.

`tree_identity` is a deterministic opaque identity for the exact
Agent/workspace-bound Tree. The audit-row and read-level values must match.

`mapped_trace_files` and the compatibility-named `session_file` field contain
opaque trace identities, never local filesystem paths. Only local root Codex
sessions that pass bounded preflight for the exact workspace and one authorized
runtime-injected `chatId` may be scanned.

`visible_messages` supports Task reconstruction. `visible_choice_candidates`
contains only later visible messages authored by the audited Agent; human or
other-Agent messages cannot establish that Agent's effect.

`outside_candidate_set` means collection found neither a successful qualifying
Tree read nor a visible Tree-influence signal. It is not evidence of no
exposure or no value. A later Task reconstruction may still mark historical
exposure unresolved.

## Read evidence

The collector retains the existing conservative trace rules:

- bounded metadata/current-context preflight happens before full trace scan;
- one trace must map unambiguously to one authorized Chat and exact workspace;
- only documented built-in read identities are accepted;
- a call is paired with its exact output and continuations;
- one successful, isolated Markdown read is required;
- compound, mixed, mutating, stdin, lookalike, cross-tree, failed, or pending
  output is rejected or recorded as a coverage gap;
- historical output is never replaced with the current Tree file.

`content_class_hint` is path-based triage, not a semantic verdict. A qualifying
effect still requires the Agent to judge a current decision, constraint,
rationale, or cross-domain relationship in normal content.

Missing, cleaned, malformed, truncated, unsupported, or non-Codex traces remain
coverage gaps. They do not become negative exposure evidence.
