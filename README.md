# Context Tree Value Audit

A First Tree Skill that answers two questions about one agent's Context Tree
usage:

1. **Observed exposure** — which nodes have a recorded read, which have none,
   and what write events reached the feed?
2. **Influence** — for a random sample of reads, did the read change what the
   agent did next?

Exposure counts recorded events — a lower bound, not complete activity.
Influence is sampled, judged by a model, and
**every claimed effect must survive an adversarial pass that tries to explain the
same choice without the Tree**. The report publishes the refutation rate, and
withholds the influence numbers entirely when most claims are refuted.

## Why it looks like this

Version 1.0 is a rewrite around `first-tree tree io`, the agent-scoped feed of
durable Context Tree IO. Exposure is now a **recorded fact** rather than
something reconstructed from local runtime transcripts.

The previous releases mined Codex/Claude transcripts and statically parsed shell
commands to guess which nodes had been read. That approach reached only ~9%
exact attribution on its own pilot, supported two runtimes, and cost roughly a
quarter of the codebase. The runtime already records the same facts at
tool-execution time, across every runtime, in a table that outlives session
timelines — so the audit consumes that instead.

Deleting the reconstruction layer removed the reason for most of the rest.
Because the analysis unit is now a recorded read rather than an
analyst-reconstructed "task", there are no task boundaries to draw, so the
blinding protocol, the frozen inventory, the digest, and the exclusion taxonomy
all lost their purpose. What remains is a small deterministic layer plus one
judgment.

There is no schema migration from 0.x. Artifacts from earlier versions are not
readable and should be discarded.

## Known recording gaps

The audit prints these in every report, and you should repeat them whenever you
quote a number:

- **Read telemetry is best-effort, and pipeline shell reads are not recorded at
  all.** `cat NODE.md | head -40` produces no event, and that is a common way to
  read a long file. **Exposure is a lower bound, never a rate**, and "no observed
  read" never means "never read".
- **Search reads are directory-granular.** `Grep` / `Glob` record one event for
  the search root, not one per matched node, so any node under a recorded search
  root is excluded from the no-observed-read list.
- **Write events are telemetry-only.** They miss merge commits and worktree edits
  outside the bound path. Complete write activity comes from the Tree
  repository's git history, not from this feed.
- **Node text is a candidate snapshot.** It is reconstructed from the checkout
  HEAD observed at read time, which is not a promise that the working file
  matched that commit.

These gaps live in First Tree's recording layer, not in this skill.

## Install

Package the Skill directory as a ZIP and upload it as a **Team Skill Resource**,
then bind it to the agents that should have it. First Tree materializes it into
each agent's runtime skill root and manages its version; there is no manual copy,
per-runtime install, or rollback ceremony.

```bash
cd skills && zip -r ../context-tree-value-audit.zip context-tree-value-audit
```

The Skill stays explicit-invocation only: Codex `allow_implicit_invocation:
false` and Claude `disable-model-invocation: true` keep it out of ordinary tasks.

## Use

A human invokes `/context-tree-value-audit` (Claude) or
`$context-tree-value-audit` (Codex). Everything after that runs without further
human input; the human reads the report at the end.

```bash
# 1. Facts — recorded events only, no sampling, no judgment
python3 scripts/context_tree_value_audit.py facts \
  --tree-root /path/to/context-tree --since 2026-07-01T00:00:00Z

# 2. Sample — uniform over observed file reads of normal content
python3 scripts/context_tree_value_audit.py sample \
  --tree-root /path/to/context-tree --size 40 --seed 1 --output sample.json

# 3. The model judges each case, then tries to refute every claim.

# 4. Report
python3 scripts/context_tree_value_audit.py report \
  --tree-root /path/to/context-tree \
  --sample sample.json --judgments judgments.json --output REPORT.md
```

`facts` alone is useful and carries no judgment risk. The **no-observed-read
list** is an evidence gap to take to a human, not a deletion proposal.

`report` refuses to publish effect counts unless the sample came from the same
Tree identity, window, and eligible read population, so a stale sample cannot
produce influence numbers against a feed it was never drawn from.

Use `--events-file` to replay a captured `tree io --json` payload instead of
calling the CLI.

## Layout

```text
skills/context-tree-value-audit/
  SKILL.md                          the workflow and judgment rules
  VERSION
  agents/openai.yaml
  references/judging-effects.md     rubric, worked examples, refutation guide
  scripts/context_tree_value_audit.py
tests/
evals/manual-behavior-checklist.md
```

## Validate

```bash
python3 scripts/validate_skill.py
python3 -m compileall -q skills tests scripts
python3 -m unittest discover -s tests -v
```

Then run [`evals/manual-behavior-checklist.md`](evals/manual-behavior-checklist.md)
against a pilot agent with authorized records.

## Safety

Read-only. It reads the agent's own IO feed and the bound Tree; it never writes
Tree content, Chats, git state, or product state. Artifacts stay private to the
invoking agent's workspace at mode `0600` and must never be committed — they
contain Tree content and chat-derived material.

The output is a sampled evidence report. It is not causal proof, an
effectiveness rate, or ROI. Missing evidence is unknown, never proof that a node
went unread or that the Tree went unused.
