# Manual Behavior Checklist

Use this observable checklist before admitting a `context-tree-insights`
revision to the private pilot. Run it in a designated First Tree Codex Agent
workspace against disposable or sanitized records. Never commit the generated
artifacts.

## Run record

Record these values in a private test note outside the repository:

- date, tester, repository commit, and installed Skill commit;
- exact Agent name and UUID;
- exact managed workspace and bound Tree;
- active First Tree binary/channel;
- authorization mode and exact Chat UUIDs, when applicable;
- lookback window and local artifact directory.

Confirm that the Agent workspace and Tree are clean enough to make before/after
checks meaningful. Capture the Tree HEAD and `git status --short`. Capture the
initial artifact directory listing. Do not copy real trace content into the
test note.

## 1. Explicit invocation

In a fresh Chat, ask:

```text
Use $context-tree-insights to audit how Context Tree influenced this Agent over the past 7 days. I explicitly authorize all Chats for this current Agent.
```

Pass when all are observable:

- the transcript contains the explicit `$context-tree-insights` invocation;
- the local provider trace shows the Skill instructions were loaded only after
  that invocation;
- the Agent announces and follows the historical value-audit workflow;
- the scope records `explicit_agent`, one exact Agent identity, one workspace,
  and one bound Tree;
- only a new private local artifact directory is created;
- the final reply links the local report and evidence bundle and states window,
  scope, and material coverage gaps.

## 2. Ordinary tasks do not trigger

In another fresh Chat, submit an ordinary task that may require a normal
Context Tree read but does not name `$context-tree-insights`, for example:

```text
Explain the current repository constraint for adding a CLI command.
```

Pass when:

- no Context Tree value-audit scope or artifact directory is created;
- no historical Chat or trace scan occurs;
- the local provider trace contains no Skill-body load and no
  `context_tree_insights.py` command;
- `agents/openai.yaml` still has
  `policy.allow_implicit_invocation: false`.

## 3. Authorization scope is exact

Run the explicit-trigger case twice with sanitized Chats:

1. `explicit_agent`: explicitly authorize all Chats for the current Agent.
2. `explicit_chat`: explicitly authorize two named Chat UUIDs for that same
   Agent.

Pass when:

- the first export contains only Chats resolved for the one current Agent;
- the second export contains exactly the named Chat-Agent pairs, including an
  explicit no-visible-messages row when applicable;
- neither run contains another Agent UUID, workspace, or Tree;
- the modes are not mixed;
- adding a different Agent, workspace, Tree, or an unlisted Chat to the scope
  causes a fail-closed error rather than an expanded scan.

## 4. Trace authorization precedes content scanning

Prepare sanitized local trace fixtures for the same workspace:

- one production-shaped trace whose bounded header contains a canonical
  `response_item/message/user` current-context row followed by an
  `event_msg/user_message` mirror with the same authorized Chat id;
- one trace whose adjacent mirror contains a different Chat id;
- one trace that contains only a mirror and no canonical current-context row;
- one trace whose tool output and compaction rows echo a current-context block
  after the canonical identity row;
- one trace whose bounded preflight identifies an unauthorized Chat and whose
  later content contains a unique sentinel plus malformed JSON;
- one trace with no `chatId`;
- one trace with two distinct `chatId` values inside the preflight bound.

Run `collect` for only the authorized Chat.

Pass when:

- only canonical user-message rows establish identity;
- a same-id adjacent mirror is accepted, a conflicting adjacent mirror fails
  closed, and a mirror-only trace remains unmapped;
- tool-output and compaction echoes neither authorize a trace nor invalidate a
  valid canonical mapping;
- only the authorized canonical trace is mapped and scanned for candidate
  evidence;
- the unauthorized trace's sentinel and later malformed content never appear
  in output or content-derived diagnostics;
- missing and ambiguous mappings remain coverage gaps;
- moving the authorized `chatId` beyond the documented preflight bound does
  not authorize a full scan;
- no fallback search of full trace content discovers or authorizes a Chat.

Retain command output and artifact hashes as the observable record; do not
retain the fixture's passage text in the repository.

## 5. Passage-level semantic audit

Use sanitized evidence with:

- one real, task-relevant normal decision passage read before a visible
  same-Agent choice with clear influence;
- one aligned choice where causality is incomplete;
- one read of an index, member route, archive, proposal, or unrelated passage;
- one passage read only after the choice;
- one compound or mixed-output command that cannot isolate the passage.

Pass when:

- the clear case is `verified` with the matching effect;
- the aligned but incomplete case is at most `probable`;
- non-decision-bearing, irrelevant, post-choice, and unisolated cases are
  `unproven` or recorded outside the candidate set as appropriate;
- every positive judgment cites a successful read and a later visible message
  authored by the audited Agent;
- invalid result/rubric/ID/timestamp combinations are rejected by `report`.

## 6. Coverage and denominator language

Include a missing or cleaned local Codex trace in the authorized scope.

Pass when the generated report:

- reports the missing trace as a coverage gap without claiming no value;
- distinguishes `verified`, `probable`, `unproven`, and
  `outside_candidate_set`;
- includes effect distribution and representative cases;
- says that read counts do not equal value;
- says that all authorized Chats are not an eligible denominator;
- states that V0 supports local Codex traces only.

## 7. No product or source mutation

Compare pre-run and post-run state.

Pass when:

- bound Tree HEAD, files, and `git status --short` are unchanged;
- repository files and Agent configuration are unchanged;
- existing Chat history, schedules, receipts, and database/product state are
  unchanged;
- no Tree write, Chat mutation, schedule, Context Tab, server API mutation, or
  other-provider adapter was invoked;
- the only intentional writes are private files beneath the new artifact
  directory;
- normal creation of the invoking Chat's visible response and automatic append
  to its local provider trace are identified separately, not misreported as
  audit product writes.

## Sign-off

Record pass/fail and the observable artifact or transcript location for every
section. A failure in explicit routing, authorization, exact trace preflight,
Agent/workspace/Tree isolation, passage semantics, deterministic validation,
or no-mutation behavior blocks the pilot revision.
