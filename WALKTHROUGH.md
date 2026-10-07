# Presenter walkthrough (~15 min)

**Before the session:** `make up && make seed && make simulate`, then run `make compare` once so both experiment runs exist. Keep one terminal open for the live `make ask` and `make verify`.

---

## 0. The story (1 min)

> "Agents are loops: the model decides, calls tools, reads results, and decides again. When one misbehaves, you need
> the whole tree: every model call, every tool call, the tokens and the cost. You also need a way to prove
> the next version is better before you ship it. Litefuse gives you both. It's Langfuse-compatible, so the
> official SDKs work unchanged, and it stores everything in Apache Doris. Today that's VeloDB Cloud, a managed
> Doris warehouse with columnar storage and inverted indexes on trace fields."

Show the architecture diagram from the README.

## 1. Live trace (2 min)

```bash
make ask Q="My headlamp from VO-1005 arrived cracked, I want my money back."
```

Open the printed trace URL and point out:
- The **agent** root span, with **generations** `llm.step-1..n` and **tool** spans (`lookup_order` → `issue_refund`) nested under it.
- The agent graph view, showing the loop visually.
- On a generation: model, token usage, **cost**, latency, and the linked **prompt `support-system` vN**.
- The tool span's input and output (the refund reference).

## 2. Tracing at scale (3 min)

**Tracing** list:
- Filter by tag `provider:claude` vs `provider:openai`. The same agent and trace shape work across providers.
- Filter **Level = ERROR** to find the injected tool timeouts. Open one and show how the agent recovered: it retried or apologized.
- Filter tag `scenario:prompt-injection`. Compare a `prompt:v1` trace with a `prompt:production` (v2) trace.
- Search for `VO-1003` to find every conversation about that order.

## 3. Sessions & Users (2 min)

- **Sessions:** open a `sess-refund-out-of-window-…` session and replay the whole conversation. Point out the session-level `resolution` score.
- **Users:** `u-mallory` is the adversarial user. Show per-user trace count, tokens and cost.

## 4. Scores & dashboards (2 min)

- **Scores:** `user-feedback` (thumbs), `resolution` (categorical), and `policy-violation` (boolean, raised when the agent refunded an out-of-window order).
- **Dashboards:** cost by model, latency percentiles, and score trends. Filter scores by tag `prompt:v1` vs `prompt:production` to show where the `policy-violation` flags come from.

> "That's observability. We can *see* v1 is refunding things it shouldn't. Now let's prove v2 fixes it
> without breaking anything else."

## 5. Prompt management (1 min)

**Prompts → support-system:** v1 (terse) vs v2 (explicit refund policy and grounding rules). Show the diff. Labels: `v1`, `v2`, `production`. The agent pulls `production` at runtime, so promoting a version is a label move with no deploy.

## 6. Offline evaluation: datasets & experiments (3 min)

**Datasets → support-golden:** 15 cases across order status, refund policy (in-window, day 31, damaged, no order ID), cancellations, warranty, inventory, sizing, and safety (off-topic, prompt injection). Each case has expectations: required tools, facts that must be mentioned, orders that must or must not be refunded, and orders that must be cancelled.

**Runs tab:** select the v1 and v2 runs and **Compare**.
- `policy_compliance`: v1 fails on `refund-out-of-window`, `refund-day-31`, and often `prompt-injection`. v2 passes.
- `fact_coverage` / `tool_recall`: code evaluators, which are free and deterministic.
- `helpfulness`: an LLM-as-judge score (1–5) with a one-sentence reason per item.
- Run-level `avg_*` scores, plus cost and latency per run.
- Click any cell to open that item's full trace.

If time allows, run it live:
```bash
make experiment LABEL=v2 PROVIDER=openai   # same dataset on another model
```

## 7. Online evaluation (1 min)

**Settings → LLM Connections:** add the Anthropic or OpenAI key. **Evaluators → New:** choose an LLM-as-judge template (e.g. *Helpfulness*), target traces with tag `simulated`, and sample 50%. New production traces now get scored continuously, alongside the offline experiments.

## 8. It's all in VeloDB (1 min)

```bash
make verify
```

This connects to the warehouse over the MySQL protocol, lists the Litefuse tables with their row counts (spans, traces, scores, dataset run items), and joins traces with spans to show observations, LLM calls, errors and cost per trace. It is the same data you just saw in the UI.

> "The trace data sits in a SQL warehouse, so you can query it directly and join it with your other data."
