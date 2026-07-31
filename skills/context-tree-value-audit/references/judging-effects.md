# Judging an Effect

This reference is for step 3 of the audit: deciding whether one recorded read
changed what the agent did next, and then trying to prove yourself wrong.

## The only question

> **If the agent had not read this node, would the later choice have been
> different?**

Everything below is scaffolding for answering that honestly.

## Material you have

Each sampled case gives you a read (node path, chat, timestamp) and a
**candidate snapshot** of the node's text, taken from the checkout HEAD observed
at read time. That is not a promise of what the agent saw — if it was reading
uncommitted Tree edits, the real text is unrecoverable. Each case says which of
`head_commit_snapshot`, `current_working_copy`, or `unavailable` it is.

**When the snapshot may not be what was read, do not claim an effect that turns
on specific wording.** Use `null`.

You supply the rest by reading that Chat around the read time: what the agent
said, what it did, and what the human asked for.

Read the window **before** the read too. Most false positives come from
skipping that.

## The four types

| Type | The shape it takes |
| --- | --- |
| `confirmed` | The agent was hesitating between staying the course and changing; the node removed the hesitation and it stayed. |
| `constrained` | The agent had options open; the node ruled one out or narrowed the boundary. |
| `redirected` | The agent was heading toward A; after the read it went to B. |
| `conflicted` | The node and the situation disagreed, and the agent had to surface or resolve that. |

`confirmed` is the weakest of the four and the easiest to over-claim. "The agent
did something consistent with the node" is not `confirmed` — consistency is not
influence. Ask whether there was any real uncertainty for the node to remove. If
the agent would obviously have done the same thing anyway, the answer is `null`.

## When the answer is `null`

Use `null` — no effect — whenever:

- you cannot point at a specific later choice, only at a general vibe;
- the agent read the node and then did something unrelated;
- the read happened after the choice was already made;
- you would have to argue for it.

`null` is a normal, common, healthy outcome. A sample where every read produced
an effect is evidence that the judgment is broken, not that the Tree is
excellent.

## The adversarial pass

For every effect you claimed, run a **separate** pass whose only job is:

> **Explain that same choice without the Tree.**

Do not reuse the reasoning that produced the claim. Come at the material fresh,
from the refuter's side.

The explanations to hunt for, in order of how often they turn out to be the real
cause:

1. **The human already said it.** Scan the Chat before the read. If the person
   asked for the outcome, the node did not cause it — the instruction did. This
   is by far the most common refutation.
2. **The agent had already committed.** If it announced the approach before the
   read, a later read cannot have redirected it.
3. **The code forced it.** If the surrounding code, framework, or existing
   pattern only permits one answer, the node is decoration.
4. **A different node or document did the work.** If several sources say the
   same thing, this specific read is not load-bearing.
5. **The node is generic.** If the passage would fit any project, it cannot
   explain a project-specific choice.

If any of these holds, set `refuted: true` and write the explanation down. A
refuted case is not a failure of the audit — it is the audit working.

## Worked examples

**Refuted — the human said it.**
The human asks "add login to the admin panel, use OAuth." The agent reads
`system/auth.md` (which requires OAuth), then says "switched from password login
to OAuth." Tempting `redirected`. **Refuted:** the instruction already specified
OAuth. The node is consistent with the outcome but did not cause it.

**Upheld — redirected.**
The human asks only "add login to the admin panel." The agent starts sketching a
username/password table, reads `system/auth.md`, then says "this needs to go
through the shared OAuth provider, dropping the local password table." No
instruction named OAuth; the approach changed after the read. **Upheld:
`redirected`.**

**Upheld — constrained.**
The agent lists three storage options, reads a node that forbids a second state
source, and drops one option with that reason. No one told it to. **Upheld:
`constrained`.**

**Null — consistency, not influence.**
The agent reads a node about naming conventions and then writes code that
follows those conventions, which it was already following everywhere else.
Nothing changed. **`null`.**

**Null — read after the fact.**
The agent implements the change, then reads the node while writing its summary.
The read cannot have influenced a choice that preceded it. **`null`.**

## What the refutation rate means

The report divides refuted claims by total claims.

- **Low** — the surviving effects were attacked and held. The numbers mean
  something.
- **High (over half)** — the reporter withholds the influence numbers entirely
  and says so. That is correct behavior. A number that cannot survive its own
  refuter is worse than no number, because someone will quote it.

If you find the rate is high, do not re-judge the cases more leniently to bring
it down. The rate is the finding.
