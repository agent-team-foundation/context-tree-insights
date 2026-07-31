---
name: context-tree-value-audit
description: Audit whether Context Tree reads changed what an agent did, when a human explicitly invokes /context-tree-value-audit or $context-tree-value-audit. Reads the agent's own durable Context Tree IO feed, reports node-level exposure and never-read nodes, then judges a random read sample with a mandatory adversarial pass. Do not use for ordinary task reads, stored-tree quality audits, Tree writes, or another agent.
disable-model-invocation: true
---

# Context Tree Value Audit

## Capability

Answer two questions about one agent's own Context Tree usage:

1. **Exposure** — which nodes did it actually open, which nodes were never
   opened, and is the Tree being written to? *Complete, from recorded facts.*
2. **Influence** — for a random sample of reads, did the read change what the
   agent did next? *Sampled, and every claim must survive an attempt to refute
   it.*

Exposure comes from `context_tree_io_events`, which the runtime records at
tool-execution time and which outlives session timelines. Influence is the only
judgment in the run, and it is deliberately adversarial: the model that claims
an effect must then try to explain the same choice **without** the Tree.

## Gate the run

Proceed only when a human explicitly invokes `/context-tree-value-audit`
(Claude) or `$context-tree-value-audit` (Codex) and asks for this audit. Do not
trigger from an ordinary task, a normal Tree read, or a stored-tree quality
audit.

The run is read-only. Do not modify Chats, Tree content, git state, agent
configuration, or product state. Write only inside a private artifact directory
in this agent's workspace, and never commit those artifacts.

The audit covers **this agent only**. The feed is self-scoped by the server; do
not attempt to widen it.

## Step 1 — Facts (no sampling, no judgment)

```bash
python3 "$CTVA_SKILL_DIR/scripts/context_tree_value_audit.py" facts \
  --tree-root "/absolute/path/to/bound/context-tree" \
  --since 2026-07-01T00:00:00Z \
  --output "$CTVA_ARTIFACT_DIR/facts.md"
```

`--since` / `--until` / `--chat` are optional filters. Add `--json` for the
structured form when you want to inspect counts directly.

This step alone is worth reporting. It gives node-level read distribution, write
activity, and the **never-read node list** — the most directly actionable
output, because a node nobody consults is diluting the signal of the ones that
matter.

The never-read list is deliberately conservative: a node inside a recorded
search root is never listed, even though the search may not have opened it.
Over-reporting here would recommend deleting a node that was in fact consulted.

## Step 2 — Sample

```bash
python3 "$CTVA_SKILL_DIR/scripts/context_tree_value_audit.py" sample \
  --tree-root "/absolute/path/to/bound/context-tree" \
  --since 2026-07-01T00:00:00Z \
  --size 40 --seed 1 \
  --output "$CTVA_ARTIFACT_DIR/sample.json"
```

Sampling is uniform over recorded file-level reads of normal content. **Do not
hand-pick cases.** Choosing the reads whose surrounding conversation is easiest
to interpret biases the result toward whatever is legible, not toward what is
true.

Each case carries the read (node path, time, chat) and the node's content **as
of that read**, recovered from the recorded commit where possible.

## Step 3 — Judge each case, then try to refute it

For every case, read the surrounding work in that Chat around the read time —
what the agent said and did after it — and answer one question:

> **If the agent had not read this node, would the later choice have been
> different?**

Record one judgment object per case:

```json
{
  "read_id": "…",
  "effect": { "type": "redirected", "summary": "Dropped the password-login plan and used the OAuth provider the node requires." },
  "refuted": false
}
```

Use `"effect": null` when nothing defensible is visible. **Uncertainty is not an
effect** — if you cannot point at a specific later choice, the answer is `null`.

Effect types:

- `confirmed` — removed real hesitation and justified keeping the plan;
- `constrained` — ruled an option out or narrowed the acceptable boundary;
- `redirected` — changed the intended approach;
- `conflicted` — surfaced a conflict that still needed resolving.

### The adversarial pass is mandatory

For **every** case where you claimed an effect, run a second, separate pass with
one job:

> **Find an explanation for that same choice that does not need the Tree.**

Look hardest for the most common one: **the human already said it.** If the
human asked for OAuth in the same Chat, an agent "switching to OAuth" after
reading an auth node is explained by the instruction, not the node. Also check
whether the agent had already committed to the choice before the read, and
whether the choice follows from the code it was editing.

If such an explanation exists, set `"refuted": true` and record it:

```json
{ "read_id": "…", "effect": { … }, "refuted": true, "refutation": "The human asked for OAuth explicitly two messages before the read." }
```

Do this pass **without reusing the reasoning that produced the claim**. Judge the
material again from the refuter's side. A claim you cannot attack is worth
something; a claim you never attacked is worth nothing.

`refuted` is required on every claimed effect — the reporter rejects a judgment
file that skips it.

## Step 4 — Report

```bash
python3 "$CTVA_SKILL_DIR/scripts/context_tree_value_audit.py" report \
  --tree-root "/absolute/path/to/bound/context-tree" \
  --since 2026-07-01T00:00:00Z \
  --sample "$CTVA_ARTIFACT_DIR/sample.json" \
  --judgments "$CTVA_ARTIFACT_DIR/judgments.json" \
  --output "$CTVA_ARTIFACT_DIR/REPORT.md"
```

The report shows exposure, the never-read list, write activity, the effect
distribution, and the **refutation rate**.

**When more than half of the claimed effects are refuted, the reporter withholds
the influence numbers** and says the run is unreliable. That is the intended
behavior, not a failure: a number nobody can defend is worse than no number.
Report the exposure section and investigate the judgment step.

## What to tell the human

Give them the report path and, in prose:

- the exposure counts and the never-read list, which are **facts**;
- the refutation rate, which says how much the influence numbers are worth;
- the two known recording gaps, so nobody reads adoption as a rate:
  - pipeline shell reads (`cat NODE.md | head -40`) are **not recorded**, so
    exposure is a lower bound;
  - `Grep` / `Glob` record the search *directory*, not the matched nodes.

Never present the output as causal proof, an effectiveness rate, or ROI. Missing
evidence is unknown — it is never proof that the Tree went unused.
