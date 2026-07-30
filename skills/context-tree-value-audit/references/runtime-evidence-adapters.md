# Runtime Evidence Adapters

The audit core is Runtime-neutral. Authorization, Task reconstruction, Read
judgment, Effect judgment, and reporting do not change by provider. Only
historical Tree-read evidence recovery varies.

The collector requires and resolves the current Runtime from
`FIRST_TREE_PROVIDER`; absence or an unknown value fails closed. An explicit
`--runtime-provider` is only an equality assertion and must match it.
`claude-code-tui` uses the `claude-code` transcript adapter because both
persist the same transcript family.

## Support matrix

| Runtime | Historical evidence source | Status |
| --- | --- | --- |
| Codex | Root session JSONL in the local Codex sessions directory | Supported |
| Claude Code | Root project transcript JSONL with complete `tool_use` / `tool_result` blocks (`CLAUDE_CONFIG_DIR` when set) | Supported |
| Claude Code TUI | Claude project transcript JSONL (`CLAUDE_CONFIG_DIR` when set) | Supported through the Claude adapter |
| Cursor | Existing native records do not retain complete attributable tool output | Unsupported; affected Reads unresolved |
| Kimi Code | Native wire lacks a durable First Tree Chat/Agent binding boundary | Unsupported; affected Reads unresolved |

Supported adapters consume evidence already produced by each Runtime. This
Skill does not modify Runtime handlers or introduce a shared Tree-read CLI,
sidecar, general tool abstraction, or provider-neutral full-output ledger.

## Shared acceptance boundary

Every adapter must establish:

- one authorized Chat and the exact current Agent UUID;
- one local session associated with the managed workspace;
- one paired, completed, non-empty tool result with no explicit failure signal;
- a statically attributable Markdown read inside the bound Tree;
- timestamps inside the acquisition window.

The shared read grammar then classifies the attempt as exact, read-only
composite, unresolved, or unsafe. Provider-native output never bypasses Tree
path isolation, mutation checks, or output-attribution checks. A unique,
completed, non-empty, attributable result with no explicit failure signal may
be candidate evidence even when the provider has no separate positive-success
flag. Missing, failed, duplicate, pending, incomplete, or out-of-window
results remain unresolved and produce no read IDs.

## Provider-specific notes

### Codex

Bounded session metadata and the runtime-injected current Chat context are
checked before the full trace is scanned. Calls, outputs, and continuations use
the existing Codex grammar.

### Claude Code and Claude Code TUI

Only root transcript rows are considered; sidechain/subagent rows are ignored.
The adapter uses `$CLAUDE_CONFIG_DIR/projects` when the Runtime sets a custom
Claude configuration root, otherwise `~/.claude/projects`.
One session ID, one workspace, and one authorized current Chat context must be
recoverable before tool blocks are paired, and the full scan must keep the
same session and Chat. Only canonical external-human rows can establish Chat
identity; tool results, compact summaries, meta rows, and other echoed text
cannot. Legacy per-Chat work directories may provide the Chat identity when no
injected context exists.

### Cursor and Kimi Code

The collector recognizes these Runtime names but does not infer a historical
Read from incomplete native records. It emits a provider-specific
`historical_evidence_not_supported` coverage gap, no read IDs, and leaves every
affected Task Read unresolved. Adding audit-only persistence to First Tree Runtime
handlers is outside this Skill's scope.

## Missing evidence

Missing roots, cleaned files, malformed identity, missing or duplicate calls
or results, failed or pending results, incomplete call/result pairs, truncated
output, or unsupported historical sessions remain `unresolved`. They never
become accepted evidence, proof of no Tree use, or zero effect.
