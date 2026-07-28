# Manual Behavior Checklist

Use this checklist before admitting a `context-tree-value-audit` revision. Run it
in designated First Tree Agent workspaces against disposable or sanitized
records. Never commit generated artifacts.

For a 0.2.4 upgrade, confirm the installed payload exposes only
`$context-tree-value-audit`; the superseded `$context-tree-insights` directory
must not remain as a second callable Skill. Exercise the README's minimal
move/copy/compare flow and confirm the old payload is outside both Skill
discovery roots. Confirm the Claude manual-invocation projection delegates to
the new canonical payload.

## Run record

Record in a private note:

- date, tester, repository commit, and installed Skill commit;
- Agent name/UUID, managed workspace, and bound Tree;
- First Tree binary/channel and authorization mode;
- exact Chat UUIDs when using `explicit_chat`;
- optional acquisition bound;
- artifact directory;
- clear Task quota and expansion batches.
- current Runtime and evidence-adapter version.

Capture the Tree HEAD, `git status --short`, and initial artifact directory
listing. Do not copy real trace passages into the test note.

## 1. Explicit routing and scope

In a fresh Chat, explicitly invoke `$context-tree-value-audit` in Codex or
`/context-tree-value-audit` in Claude and authorize either all Chats for the
current Agent or exact Chat UUIDs.

Pass when:

- the Skill loads only after explicit invocation;
- the scope contains one exact Agent, workspace, Tree, and authorization mode;
- the immutable runtime Agent slug is used for CLI selection even when the
  workspace `displayName` differs;
- a missing or malformed runtime slug, or a runtime/workspace UUID mismatch,
  fails closed;
- current underscore/trailing-separator Agent names and the complete
  historical `[a-z0-9_-]{1,100}` grammar, including leading `-` / `_`, remain
  selectable for still-runnable grandfathered Agents, while names outside the
  producer grammar fail closed;
- the First Tree CLI's producer-owned local binding resolution of the runtime
  slug must return the same UUID as later `chat --agent` calls; the Skill does
  not reimplement the local YAML parser or persist/enumerate other Agents into
  the audit scope;
- another Agent, workspace, Tree, or unlisted Chat fails closed;
- only one private artifact directory is created;
- ordinary tasks do not load the Skill or scan history;
- `policy.allow_implicit_invocation` remains `false`.

## 2. Runtime evidence adapters remain isolated

Run the supported matrix with sanitized records:

- Codex root session JSONL;
- Claude Code root transcript JSONL;
- Claude Code TUI through the same Claude transcript family.

Pass when:

- the selected adapter exactly matches `FIRST_TREE_PROVIDER`;
- missing or invalid `FIRST_TREE_PROVIDER` fails closed instead of defaulting
  to an adapter;
- every adapter maps one authorized Chat, current Agent, workspace, and bound
  Tree before accepting complete output;
- Claude sidechain/subagent rows, tool-result echoes, and later session/Chat
  drift do not become root evidence;
- Cursor and Kimi Code produce explicit
  `historical_evidence_not_supported` gaps, no read IDs, and pending Tasks;
- no First Tree Runtime handler, local state schema, server, database, or Web
  surface is changed for the audit;
- equal-timestamp results appended before their calls remain unresolved;
- a missing, cleaned, malformed, or unmapped source remains unresolved;
- the audit core emits the same candidate and Task schema for every Runtime.

## 3. Collector safety remains intact

Use sanitized traces covering:

- canonical current-context plus matching mirror;
- conflicting mirror, mirror-only, missing Chat ID, and two canonical Chat IDs;
- successful direct file read;
- `functions.exec` with one literal nested read, `Promise.all`, multiple
  literal reads, static `for`, multi-path operands, safe pipelines,
  predicates, labels, hierarchy selectors, line counts, and read-only git;
- dynamic interpolation, unknown programs, stdin, suffix lookalikes, failed
  output, and pending/completed continuations;
- null-sink output, file output, git mutation, network programs, and literal
  non-Tree paths;
- another Tree path and an unauthorized trace with a unique sentinel.

Pass when:

- authorization preflight happens before full content scanning;
- only the exact authorized root Codex trace is mapped;
- exact and statically closed read-only composite reads of the bound Tree are
  retained, with nested output sliced when provider blocks preserve it;
- each in-window Tree-read attempt lands in exactly one of
  `accepted_exact`, `accepted_read_only_composite`, `unresolved_opaque`, or
  `rejected_unsafe`, and the four counts conserve the total;
- calls outside the acquisition window do not contaminate attempt counts or
  coverage gaps;
- dynamic/unknown calls remain unresolved; mutation, file output, network
  access, and Tree-external reads are rejected;
- unauthorized, unresolved, and unsafe sentinels never appear in output;
- deterministic labels are removed from passages; unseparated dynamic
  diagnostics produce no read ID, even when the command grammar itself is
  accepted;
- wrapper aliases, output mutation, reversed forwarding, callback side
  effects, duplicate properties, unsafe git options, and `rg` patterns that
  merely look like Markdown paths all fail closed;
- initial calls and exact `write_stdin`/`wait` continuations form one attempt;
- gaps remain diagnostic rather than being turned into negative exposure;
- artifacts keep `0700`/`0600` permissions and opaque local identities.

## 4. Receipt present, absent, and malformed

Export three sanitized messages:

1. a valid `metadata.contextDecision` v1 with unrelated metadata and extra
   receipt fields;
2. no `contextDecision`;
3. a malformed `contextDecision`.

Pass when:

- the valid receipt is saved as the minimal v1 projection only;
- unrelated message metadata and extra receipt fields are not copied;
- credential-bearing URLs, local paths, loopback hosts, and non-repository
  identities are omitted without echoing their raw values;
- receipt absence stays unknown and adds no negative gap;
- malformed receipt is omitted with `context_decision_invalid`;
- no malformed receipt blocks the message, Chat export, or audit.

## 5. One Chat splits into multiple Tasks

Use one Chat containing two distinct objectives and outcomes.

Pass when:

- it produces two Task rows with separate source messages and windows;
- clear Tasks have objective, object scope, outcome, and one allowed task type;
- a Task missing those boundaries is marked excluded;
- excluded Tasks contain no exposure or effects;
- one read or choice copied into both Tasks is rejected.

## 6. Cross-Chat handoff merge

Use two Chats for one PR/MR/Issue or a visible handoff.

Pass when:

- one Task may contain both source fragments when each carries the same
  `work_item`, `explicit_handoff`, or `same_objective_delivery` linkage;
- the same fragments without linkage are rejected;
- unrelated Chats cannot be merged by topical similarity alone.

## 7. Confirmed and unresolved exposure

Create one Task with attributable Task-window reads and one historical Task
whose trace coverage cannot resolve exposure.

Pass when:

- the first is `confirmed` with valid read IDs;
- the second is `unresolved` with a reason;
- unresolved exposure has no reads and no effects;
- no `not_observed`, `unused`, or negative-value state is emitted;
- reads outside the Task window or source Chats are rejected;
- unresolved Tasks appear in coverage counts, never an unused denominator.

## 8. Four effects, anchors, and deduplication

Prepare valid examples of `confirmed`, `constrained`, `redirected`, and
`conflicted`, with `verified` or `probable` original judgments.

Pass when:

- `informed`, `none`, unknown effects, and numeric weights are rejected;
- every effect has Task exposure reads, later same-Agent choices, an outcome
  anchor, and a summary;
- every effect persists the five passage-to-choice rubric checks; `verified`
  requires all five while `probable` requires the first four and no visible
  influence;
- post-choice reads and out-of-window choices are rejected;
- duplicate effect evidence does not inflate independent-effect totals;
- input `support` is rejected;
- reporter-derived support is definite only for confirmed + verified and
  limited otherwise.

## 9. Task quota and saturation

Run a sanitized sequence with:

- 100 clear Tasks;
- a 20-Task expansion with no saturation signals;
- a second 20-Task expansion with no saturation signals.

Pass when:

- `sampling_order` is contiguous and reproducible;
- all five task types are represented in the initial 100 clear Tasks;
- the report records 100 + 20 + 20 and saturation at 140;
- a new effect type, key counterexample, or conclusion change resets the
  consecutive-empty counter;
- unresolved exposure never counts as an empty effect batch or establishes
  saturation;
- missing or spurious `new_effect_type` annotations are rejected against the
  actual cumulative effect-type set;
- rows beyond an already established saturation point are rejected;
- an incomplete sample is reported as incomplete/continuing rather than a
  stable rate;
- `--days`, when supplied, remains only an acquisition bound.
- a Chat with messages inside the bound but later activity after `window.end`
  is fetched and filtered rather than omitted.

## 10. Report conservation and language

Pass when the report includes:

- clear and excluded Tasks;
- confirmed and unresolved exposure Tasks;
- effect Tasks and independent effects;
- effect distribution and task type × effect;
- derived support and sampling status;
- authorized Chat/message/trace coverage and gaps.
- the four-class in-window Tree-read attempt conservation table.

Verify:

- confirmed + unresolved = clear Tasks;
- effect Tasks ≤ clear Tasks;
- task type × effect cells sum to independent effects;
- the report does not output a global effectiveness rate;
- read counts, receipts, and unresolved gaps are not represented as causal
  value or non-value.
- zero evidence-ready Tasks render effect totals, distribution, support,
  representatives, and saturation as `N/A / pending`, never numeric zero.
- an optional reviewed baseline is hash-anchored, internally conserving, and
  rendered separately; it does not alter current exposure, effects, or
  saturation.

For the 0.2.1 historical pilot rerun, the 210 in-window calls must all remain
accounted for. Compare the new result with the grammar-only overlay
(`19 exact + 145 read-only composite + 42 opaque + 4 unsafe`). Any deliberate
delta must name the command-shape class and the stricter attribution or safety
reason. Do not tune the parser merely to reproduce the target counts.

After collection, redo Task-level exposure and effect judgment. Never reuse
the old blanket `unresolved` / empty-effects rows as negative cases, and never
let the current rerun erase the separately reviewed 37 positive effect Tasks.

## 11. No product or source mutation

Compare pre-run and post-run state.

Pass when:

- bound Tree HEAD, files, and `git status --short` are unchanged;
- repository files and Agent configuration are unchanged;
- existing Chats, traces, schedules, receipts, database, and product state are
  unchanged;
- no runtime event, message-path validation, raw IO API, Context Tab, Tree
  write, schedule, or other-provider adapter was invoked;
- the only intentional audit writes are private files beneath the artifact
  directory;
- the run remains limited to the current Agent, one workspace, one Tree, and
  local Codex traces.

## Sign-off

Record pass/fail and the observable artifact or transcript location for every
section. A failure in explicit routing, authorization, trace preflight,
Agent/workspace/Tree isolation, Task reconstruction, exposure semantics,
effect validation, quota/saturation, conservation, or no-mutation behavior
blocks the revision.
