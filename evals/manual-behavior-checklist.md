# Manual Behavior Checklist

Use this checklist before admitting a `context-tree-insights` revision. Run it
in a designated First Tree Codex Agent workspace against disposable or
sanitized records. Never commit generated artifacts.

## Run record

Record in a private note:

- date, tester, repository commit, and installed Skill commit;
- Agent name/UUID, managed workspace, and bound Tree;
- First Tree binary/channel and authorization mode;
- exact Chat UUIDs when using `explicit_chat`;
- optional acquisition bound;
- artifact directory;
- clear Task quota and expansion batches.

Capture the Tree HEAD, `git status --short`, and initial artifact directory
listing. Do not copy real trace passages into the test note.

## 1. Explicit routing and scope

In a fresh Chat, explicitly invoke `$context-tree-insights` and authorize
either all Chats for the current Agent or exact Chat UUIDs.

Pass when:

- the Skill loads only after explicit invocation;
- the scope contains one exact Agent, workspace, Tree, and authorization mode;
- another Agent, workspace, Tree, or unlisted Chat fails closed;
- only one private artifact directory is created;
- ordinary tasks do not load the Skill or scan history;
- `policy.allow_implicit_invocation` remains `false`.

## 2. Collector safety remains intact

Use sanitized traces covering:

- canonical current-context plus matching mirror;
- conflicting mirror, mirror-only, missing Chat ID, and two canonical Chat IDs;
- successful direct file read;
- compound/mixed command, stdin, suffix lookalike, failed output, and pending
  continuation;
- another Tree path and an unauthorized trace with a unique sentinel.

Pass when:

- authorization preflight happens before full content scanning;
- only the exact authorized root Codex trace is mapped;
- only successful isolated reads of the bound Tree are retained;
- unauthorized or mixed sentinels never appear in output;
- gaps remain diagnostic rather than being turned into negative exposure;
- artifacts keep `0700`/`0600` permissions and opaque local identities.

## 3. Receipt present, absent, and malformed

Export three sanitized messages:

1. a valid `metadata.contextDecision` v1 with unrelated metadata and extra
   receipt fields;
2. no `contextDecision`;
3. a malformed `contextDecision`.

Pass when:

- the valid receipt is saved as the minimal v1 projection only;
- unrelated message metadata and extra receipt fields are not copied;
- receipt absence stays unknown and adds no negative gap;
- malformed receipt is omitted with `context_decision_invalid`;
- no malformed receipt blocks the message, Chat export, or audit.

## 4. One Chat splits into multiple Tasks

Use one Chat containing two distinct objectives and outcomes.

Pass when:

- it produces two Task rows with separate source messages and windows;
- clear Tasks have objective, object scope, outcome, and one allowed task type;
- a Task missing those boundaries is marked excluded;
- excluded Tasks contain no exposure or effects;
- one read or choice copied into both Tasks is rejected.

## 5. Cross-Chat handoff merge

Use two Chats for one PR/MR/Issue or a visible handoff.

Pass when:

- one Task may contain both source fragments when each carries the same
  `work_item`, `explicit_handoff`, or `same_objective_delivery` linkage;
- the same fragments without linkage are rejected;
- unrelated Chats cannot be merged by topical similarity alone.

## 6. Confirmed and unresolved exposure

Create one Task with attributable Task-window reads and one historical Task
whose trace coverage cannot resolve exposure.

Pass when:

- the first is `confirmed` with valid read IDs;
- the second is `unresolved` with a reason;
- no `not_observed`, `unused`, or negative-value state is emitted;
- reads outside the Task window or source Chats are rejected;
- unresolved Tasks appear in coverage counts, never an unused denominator.

## 7. Four effects, anchors, and deduplication

Prepare valid examples of `confirmed`, `constrained`, `redirected`, and
`conflicted`, with `verified` or `probable` original judgments.

Pass when:

- `informed`, `none`, unknown effects, and numeric weights are rejected;
- every effect has Task exposure reads, later same-Agent choices, an outcome
  anchor, and a summary;
- post-choice reads and out-of-window choices are rejected;
- duplicate effect evidence does not inflate independent-effect totals;
- input `support` is rejected;
- reporter-derived support is definite only for confirmed + verified and
  limited otherwise.

## 8. Task quota and saturation

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
- rows beyond an already established saturation point are rejected;
- an incomplete sample is reported as incomplete/continuing rather than a
  stable rate;
- `--days`, when supplied, remains only an acquisition bound.

## 9. Report conservation and language

Pass when the report includes:

- clear and excluded Tasks;
- confirmed and unresolved exposure Tasks;
- effect Tasks and independent effects;
- effect distribution and task type × effect;
- derived support and sampling status;
- authorized Chat/message/trace coverage and gaps.

Verify:

- confirmed + unresolved = clear Tasks;
- effect Tasks ≤ clear Tasks;
- task type × effect cells sum to independent effects;
- the report does not output a global effectiveness rate;
- read counts, receipts, and unresolved gaps are not represented as causal
  value or non-value.

## 10. No product or source mutation

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
