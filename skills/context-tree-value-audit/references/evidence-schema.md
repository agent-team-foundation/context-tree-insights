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

The Agent name in scope and evidence is the immutable lowercase slug from the
invoking runtime's `FIRST_TREE_AGENT_SLUG`. The runtime's
`FIRST_TREE_AGENT_ID` must equal the UUID in the managed workspace identity.
The First Tree CLI must resolve that slug to the same UUID through its
producer-owned local binding loader—the same mapping used by later
`chat --agent` commands. The local Agent listing exists only in memory for this
identity preflight; it is not persisted, analyzed, or used to broaden consent.
Workspace `displayName` is a mutable human-facing label and is never a CLI
selector or authorization identity. The consumer accepts both the current
1-64 character Agent-name grammar and the complete historical
`[a-z0-9_-]{1,100}` grammar for still-runnable grandfathered Agent names,
including legacy names with a leading `-` or `_`. It does not reinterpret
arbitrary filesystem text as a selector or parse the local YAML mirror
independently of its producer.

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
URLs, loopback or unspecified hosts, non-canonical numeric hosts, credentials,
query strings, and fragments are malformed. Host validation is purely
syntactic and never performs DNS resolution; percent-encoded hosts and hosts
made entirely from decimal or hexadecimal numeric components are rejected.
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
  "runtime_provider": "claude-code",
  "candidate_status": "candidate",
  "mapped_trace_files": ["trace-opaque-hash"],
  "collector_diagnostics": {
    "in_window_tree_read_attempts": 1,
    "attempt_status_counts": {
      "accepted_exact": 1,
      "accepted_read_only_composite": 0,
      "unresolved_opaque": 0,
      "rejected_unsafe": 0
    },
    "attempt_reason_counts": {}
  },
  "reads": [
    {
      "read_id": "stable-id",
      "timestamp": "RFC3339",
      "completed_at": "RFC3339",
      "session_file": "trace-opaque-hash",
      "call_id": "provider-call-id",
      "nested_call_index": null,
      "tool_name": "exec_command",
      "runtime_provider": "claude-code",
      "reader_agent_id": "AGENT_UUID",
      "tree_identity": "tree-opaque-hash",
      "node_paths": ["system/example.md"],
      "read_components": [
        {
          "reader": "sed",
          "node_paths": ["system/example.md"]
        }
      ],
      "read_mode": "isolated",
      "output_attribution": "exact",
      "auxiliary_output_possible": false,
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
A Chat whose latest activity is after `window.end` must still be fetched and
filtered because it may contain messages inside the historical window. A Chat
may be skipped from its summary timestamp only when that timestamp is strictly
before `window.start`.

`tree_identity` is a deterministic opaque identity for the exact
Agent/workspace-bound Tree. The audit-row and read-level values must match.
`runtime_provider` is the canonical local evidence adapter. Schema-v1
artifacts produced by 0.2.x omitted it because that release was Codex-only;
the reporter interprets that legacy omission as `codex`.

`mapped_trace_files` and the compatibility-named `session_file` field contain
opaque evidence identities, never local filesystem paths. Each local Runtime
source must pass its adapter's bounded preflight for the exact workspace, one
authorized Chat, and the current Agent before complete outputs may be scanned.
The exact sources and support matrix are defined in
[runtime-evidence-adapters.md](runtime-evidence-adapters.md).

`collector_diagnostics` counts command-shape decisions, not effects. Every
in-window call whose payload can be tied to bound-Tree Markdown is classified
exactly once:

- `accepted_exact` — one statically closed content read with exact output
  forwarding;
- `accepted_read_only_composite` — a statically closed read-only wrapper,
  multi-file read, sequence, loop, or pipeline;
- `unresolved_opaque` — dynamic interpolation, unknown program, incomplete
  path closure, or output attribution that cannot be proved;
- `rejected_unsafe` — mutation, file output, network access, or a proven
  Tree-external read.

The four status counts must sum to `in_window_tree_read_attempts`. Reason
counts conserve the unresolved and rejected calls. The acquisition window is
applied to call start time before diagnostics, so an older call cannot
contaminate the current run's gaps. A call that starts in-window but whose
result completes after the acquisition end remains one `unresolved_opaque`
attempt; it does not disappear from the denominator.

`visible_messages` supports Task reconstruction. `visible_choice_candidates`
contains only later visible messages authored by the audited Agent; human or
other-Agent messages cannot establish that Agent's effect.

`outside_candidate_set` means collection found neither a successful qualifying
Tree read nor a visible Tree-influence signal. It is not evidence of no
exposure or no value. A later Task reconstruction may still mark historical
exposure unresolved.

## Read evidence

The collector retains conservative trace rules while recognizing real
read-only command shapes:

- bounded metadata/current-context preflight happens before full trace scan;
- one trace must map unambiguously to one authorized Chat and exact workspace;
- documented direct readers and statically extractable
  `functions.exec`/`exec_command` content reads are accepted;
- an outer `functions.exec` assignment may omit only the final JavaScript
  semicolon when it still forwards the same nested result's `.output` directly;
  every nested command and workdir must remain literal;
- a call is paired with its exact output and continuations; an attributable
  in-window provider call with a missing, duplicate, or otherwise invalid
  result remains one `unresolved_opaque` attempt instead of disappearing from
  the attempt denominator;
- explicit multi-file reads, multiple read statements, static `for` loops,
  single-branch literal filesystem guards, read-only pipelines, filesystem
  predicates, hierarchy selectors, labels, line counts, and bounded read-only
  git diagnostics may coexist at the command-classification layer;
- a hierarchy selector must parse as the exact `first-tree tree tree` command
  path with only its documented read options and explicit `--no-pull` (apart
  from an exact standalone help form), and `rg` accepts only a closed option
  grammar with explicit `--no-config`; implicit refresh/config, file-valued,
  external-program, unknown, and Tree-external options never become accepted
  read-only diagnostics;
- shell readers and diagnostics use exact bare executable tokens; a
  path-qualified executable is not trusted merely because its basename
  matches an allowed reader;
- conditional guards with dynamic values, alternate branches, nested control,
  or an unsafe body stay unresolved or rejected;
- null-sink diagnostic output is allowed, while file output is rejected;
- nested shell calls are kept as separate read slices when provider output
  preserves that boundary; otherwise the read is marked
  `output_attribution: aggregate` and receives an attribution gap;
- deterministic static labels are removed only when exactly attributable;
  an accepted command that mixes unseparated dynamic diagnostic output with
  Tree output receives an attribution gap and produces no read ID;
- `auxiliary_output_possible` records that a composite contained safe
  auxiliary operations, but persisted passage bytes have already passed the
  attribution gate;
- dynamic, unknown, stdin, lookalike, cross-tree, failed, pending, mutating, or
  network shapes are unresolved or rejected and produce no read ID;
- historical output is never replaced with the current Tree file.

`read_components` conserves `node_paths`. `read_mode: isolated` implies
`output_attribution: exact`; `read_only_composite` uses aggregate attribution
unless provider-native output blocks permit safe nested-call slicing. An
accepted command shape is still only candidate evidence: the Task auditor
must verify that the recorded passage actually contains decision-bearing Tree
content before confirming exposure or an effect.

When one outer orchestration call forwards multiple provider-native output
blocks, the collector emits one read row per attributable nested shell call
and sets `nested_call_index`. The outer call still contributes exactly one
four-state attempt classification; read-row count is therefore not required to
equal attempt count.

`content_class_hint` is path-based triage, not a semantic verdict. A qualifying
effect still requires the Agent to judge a current decision, constraint,
rationale, or cross-domain relationship in normal content.

Missing, cleaned, malformed, truncated, unsupported, or unmapped Runtime
evidence remains a coverage gap. It does not become negative exposure evidence.
