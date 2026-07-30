# Manual Behavior Checklist

Use this checklist before admitting a `context-tree-value-audit` revision. Run it
in designated First Tree Agent workspaces against disposable or sanitized
records. Never commit generated artifacts.

For a 0.3.0 upgrade, confirm the installed payload exposes only
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
- clear Task count and acquisition bound;
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
- `explicit_agent` is used only after the human explicitly asks for all Chats
  visible to the current Agent;
- `explicit_chat` is used for the invoking Chat or exact supplied Chat UUIDs;
- neither mode carries human, organization, or extra authorization-context
  fields, and neither can cross to another Agent or workspace;
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
  predicates, labels, hierarchy selectors, and line counts;
- dynamic interpolation, unknown programs, stdin, suffix lookalikes, failed
  output, and pending/completed continuations;
- null-sink output, file output, git mutation, network programs, literal
  non-Tree paths, and Git commands with implicit configured-helper potential,
  including index-backed revision resolution and unsafe global options;
- a valid `first-tree tree tree --no-pull` selector and exact help form beside
  the default-refresh form and a mutating First Tree namespace that merely
  contains the same `tree tree` token pair;
- ordinary whitelisted `rg` options beside `--file`, `--ignore-file`, and an
  unknown option, including both separate-value and `--option=value` forms,
  with accepted calls requiring `--no-config --no-ignore` and both
  implicit-config and implicit-ignore forms rejected;
- bare allowed readers beside `./rg`, `/tmp/rg`, path-qualified
  `first-tree-staging`, and another path-qualified reader basename;
- bare and forced-paging `bat` forms, plus a no-config/never-page-looking
  form, all rejected because `bat` is outside the accepted reader grammar;
- benign-looking and file-valued `find` forms rejected alongside explicit
  mutating actions because `find` is outside the accepted diagnostic grammar;
- bare and recursive/dereferencing `ls` forms rejected, plus pipeline
  `head`/`tail`/`nl` help, follow, and unknown options rejected by a closed
  filter grammar;
- Claude Tree-reading `tool_use` rows with a missing result, duplicate result,
  duplicate call ID, a result after the acquisition end, and the same pairing
  failures wholly before the acquisition start;
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
  coverage gaps; a call started in-window with a result after the acquisition
  end remains one unresolved attempt;
- dynamic/unknown calls remain unresolved; mutation, file output, network
  access, and Tree-external reads are rejected;
- unauthorized, unresolved, and unsafe sentinels never appear in output;
- deterministic labels are removed from passages; unseparated dynamic
  diagnostics produce no read ID, even when the command grammar itself is
  accepted;
- wrapper aliases, output mutation, reversed forwarding, callback side
  effects, duplicate properties, unsafe or config-driven Git diagnostics,
  and `rg` patterns that merely look like Markdown paths all fail closed;
- initial calls and exact `write_stdin`/`wait` continuations form one attempt;
- an explicit direct-reader error envelope produces no read ID;
- a missing or duplicate continuation result keeps the whole parent read
  unresolved even if a later continuation appears successful;
- every attributable in-window Claude Tree-reading call stays in the attempt
  denominator; missing, failed, pending, duplicate, incomplete, or
  out-of-window pairing is `unresolved_opaque` and produces no read ID;
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

## 5. Complete Task reconstruction

Use one Chat containing one objective across planning, implementation, review,
QA, correction, and final delivery, followed by a genuinely independent
objective and outcome.

Pass when:

- all phases and continuations for the first deliverable remain one Task;
- it produces two Task rows with separate source messages and windows;
- clear Tasks have objective, object scope, and outcome;
- a Task missing those boundaries is marked excluded;
- excluded Tasks contain no Read or Effect judgment;
- one Read or choice copied into both Tasks is rejected.

## 6. Cross-Chat handoff merge

Use two Chats for one PR/MR/Issue or a visible handoff.

Pass when:

- one Task may contain both source fragments when each carries the same
  `work_item`, `explicit_handoff`, or `same_objective_delivery` linkage;
- the same fragments without linkage are rejected;
- unrelated Chats cannot be merged by topical similarity alone.

## 7. Observed and unresolved Read

Create one Task with attributable Task-window reads and one historical Task
whose trace coverage cannot resolve the Read.

Pass when:

- the first is `observed` with valid Read IDs;
- the second is `unresolved` with a reason;
- unresolved Read has no Read IDs and a null Effect;
- no `not_observed`, `unused`, or negative-value state is emitted;
- Reads outside the Task window or source Chats are rejected;
- unresolved Tasks appear in coverage counts, never an unused denominator.

## 8. Optional Effect

Prepare valid examples of `confirmed`, `constrained`, `redirected`, and
`conflicted`, plus observed-Read Tasks with no Effect.

Pass when:

- unknown Effects, multiple Effects, confidence tiers, and numeric weights are
  rejected;
- every Effect has observed Task Reads, later same-Agent choices, an outcome
  anchor, and a summary;
- post-choice Reads and out-of-window choices are rejected;
- a null Effect requires one short `effect_reason`;
- a decision receipt alone does not create an Effect;
- schema-v1 task types, sampling fields, `verified` / `probable`, rubrics, and
  support fields are rejected;
- there is at most one Effect per Task.

## 9. Sample handling

Run sanitized reports with 1, 16, and 44 clear Tasks.

Pass when:

- every available clear Task is reported without a minimum quota;
- no task-type coverage, batch expansion, or saturation state is emitted;
- `--days`, when supplied, remains only an acquisition bound;
- a Chat with messages inside the bound but later activity after `window.end`
  is fetched and filtered rather than omitted.

## 10. Report conservation and language

Pass when the report includes:

- clear and excluded Tasks;
- observed and unresolved Read Tasks;
- Effect Tasks and observed Reads without an Effect;
- the four-Effect distribution;
- every clear Task's Read and Effect result;
- every excluded Task's reason;
- authorized Chat/message/trace coverage and gaps.
- the four-class in-window Tree-read attempt conservation table.

Verify:

- observed + unresolved = clear Tasks;
- Effect + observed Read without Effect = observed Read Tasks;
- the four Effect counts sum to Effect Tasks;
- the report does not output a global effectiveness rate;
- Read counts, receipts, and unresolved gaps are not represented as causal
  value or non-value.
- the report labels itself sampled and does not imply remote provenance,
  causal proof, or ROI;
- an optional reviewed baseline is hash-anchored, internally conserving, and
  rendered separately; it does not alter current Reads or Effects.

For the 0.2.1 historical pilot rerun, the 210 in-window calls must all remain
accounted for. Compare the new result with the grammar-only overlay
(`19 exact + 145 read-only composite + 42 opaque + 4 unsafe`). Any deliberate
delta must name the command-shape class and the stricter attribution or safety
reason. Do not tune the parser merely to reproduce the target counts.

After collection, redo Task-level Read and Effect judgment. Never reuse
the old blanket `unresolved` / empty-Effect rows as negative cases, and never
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
Agent/workspace/Tree isolation, Task reconstruction, Read semantics,
Effect validation, conservation, or no-mutation behavior
blocks the revision.
