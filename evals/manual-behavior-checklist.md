# Manual Behavior Checklist

Run this against a pilot agent with authorized records before admitting a
revision. Never commit generated artifacts.

Record: date, tester, repo commit, agent name/UUID, bound Tree, window used,
sample size and seed, and the refutation rate.

## 1. Routing and scope

- The Skill loads only after an explicit `/context-tree-value-audit` or
  `$context-tree-value-audit` invocation; ordinary tasks do not load it.
- `policy.allow_implicit_invocation` is `false` and the Claude projection keeps
  `disable-model-invocation: true`.
- The run touches only this agent's own feed. There is no option, prompt, or
  workaround that widens it to another agent.
- Artifacts land in a private workspace directory at mode `0600` and are not
  committed.

## 2. Facts are complete and honest

- `facts` runs with no sample and no judgment.
- Exposure is reported as counts. **No percentage of total work appears
  anywhere**, because unrecorded reads make any such rate false.
- Both recording gaps are printed: pipeline reads unrecorded, search reads
  directory-granular.
- The never-read list excludes nodes under a recorded search root. Verify with a
  `Grep` of a tree directory: no node beneath it may be listed as never-read.
- The never-read list excludes `AGENTS.md`, `members/`, and `raw-context/`.
- A node read via `Read` in the window does not appear in the never-read list.

## 3. Sampling is uniform and reproducible

- The same `--seed` yields the same cases; a different seed yields different
  ones.
- Only file-level reads of normal content are eligible.
- The analyst does not hand-pick or re-roll cases to find interpretable ones.
- Case material carries node content as of the read when the recorded commit
  resolves, and says so honestly when it falls back to the working copy or
  cannot resolve the node at all.

## 4. Judgment and the adversarial pass

- Every sampled case has exactly one judgment; a missing one fails the report.
- `"effect": null` is used freely when no specific later choice is visible.
- **Every claimed effect carries an explicit `refuted` boolean.** Omitting it
  fails the report — verify this by deleting one and rerunning.
- `refuted: true` without a `refutation` string fails.
- The refutation pass actually looks for a pre-read human instruction. Construct
  a case where the human asked for the outcome before the read and confirm it is
  refuted rather than counted.
- Unknown effect types, confidence tiers, and numeric weights are rejected.

## 5. Report conservation and the reliability floor

- Effect counts equal the upheld claims; refuted claims are excluded from the
  distribution.
- With more than half the claims refuted, the report **withholds the influence
  numbers**, says the run is unreliable, and still prints the exposure section.
  Verify with a seeded judgment file.
- With a healthy rate, the effect distribution and per-effect summaries appear.
- The report never prints a global effectiveness rate, causal claim, or ROI.
- The report states that missing evidence is unknown, not proof of non-use.

## 6. No mutation

Compare before and after:

- bound Tree HEAD, files, and `git status --short` unchanged;
- Chats, agent configuration, schedules, and product state unchanged;
- the only writes are private files under the artifact directory.

## Sign-off

Record pass/fail per section. A failure in routing, scope, the never-read search
guard, the mandatory adversarial pass, or the reliability floor blocks the
revision.
