# Presenter walkthrough (~15 min)

**Before the session (within a day or two of it):** `make up && make seed && make simulate && make compare`. Traces older than 30 days are deleted from VeloDB, so data generated for an earlier demo is gone, and experiment runs from then no longer open their traces. Both commands together take about 15 minutes and a few dollars of LLM spend. Ten minutes before the session, restart the worker (`docker compose -f deploy/docker-compose.yml --env-file .env restart litefuse-worker`) so no stuck ingestion job blocks the live trace, then run one `make ask` as a warm-up. Keep one terminal open for the live `make ask` and `make verify`.

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

**Tracing** list. Lists open on **Past 1 day**: if the data is older, set the time range to the past 7 days first, here and on Sessions, Users, Scores and Dashboards.
- Filter by tag `provider:claude` vs `provider:openai`. The same agent and trace shape work across providers. Skip this unless `.env` has an OpenAI-compatible key: without one, `make simulate` runs everything on Claude.
- Filter **Level = ERROR** to find the injected tool timeouts. Open one and show how the agent recovered: it retried or apologized.
- Filter tag `scenario:prompt-injection` and open the trace: the agent declines the "admin mode" refund. `make simulate` picks the prompt label at random, so there may be no `prompt:v1` trace to compare against; don't promise one.
- Search for `VO-1003` with the search scope switched from **IDs / Names** to **Full Text** (the dropdown next to the search box). That finds every conversation that mentions the order, served by VeloDB's inverted index.

## 3. Sessions & Users (2 min)

- **Sessions:** open a `sess-refund-out-of-window-…` session and replay the whole conversation. Point out the session-level `resolution` score.
- **Users:** `u-mallory` is the adversarial user. Show per-user trace count, tokens and cost.

## 4. Scores & dashboards (2 min)

- **Scores:** `user-feedback` (thumbs), `resolution` (categorical), and `policy-violation` (boolean, raised when the agent refunded an out-of-window order).
- **Dashboards:** open **Litefuse Cost Dashboard** (traces, observations, cost by model) and **Litefuse Latency Dashboard** (latency percentiles). The **OpenClaw** dashboards are Litefuse samples for another agent; skip them.
- On **Scores**, filter `policy-violation` and open the traces: every flag comes from a `prompt:v1` session.

> "That's observability. We can *see* v1 is refunding things it shouldn't. Now let's prove v2 fixes it
> without breaking anything else."

## 5. Prompt management (1 min)

**Prompts → support-system:** v1 (terse) vs v2 (explicit refund policy and grounding rules). Show the diff. Labels: `v1`, `v2`, `production`. The agent pulls `production` at runtime, so promoting a version is a label move with no deploy.

## 6. Offline evaluation: datasets & experiments (3 min)

**Datasets → support-golden:** 15 cases across order status, refund policy (in-window, day 31, damaged, no order ID), cancellations, warranty, inventory, sizing, and safety (off-topic, prompt injection). Each case has expectations: required tools, facts that must be mentioned, orders that must or must not be refunded, and orders that must be cancelled.

**Runs tab:** tick the newest v1 and v2 runs (15 run items each), then **Actions → Compare**. Ignore runs with 0 items or $0.00 cost: those are failed or older runs whose traces have expired.
- `policy_compliance`: v1 fails on `refund-out-of-window` and `refund-day-31` (it refunds orders past the 30-day window); v2 passes every case. In the 6 Nov run Haiku 4.5 resisted `prompt-injection` under both prompts, so don't promise a v1 failure there.
- `fact_coverage` / `tool_recall`: code evaluators, which are free and deterministic.
- `helpfulness`: an LLM-as-judge score (1–5) with a one-sentence reason per item.
- Per-run averages (the `Ø` values in the score columns), plus cost and latency per run. The run-level `avg_*` columns stay empty in Litefuse 26.2.0.
- Click any cell to open that item's full trace.

If time allows, run it live:
```bash
make experiment LABEL=v2 PROVIDER=openai   # same dataset on another model; needs an OpenAI-compatible key in .env
```

## 7. Online evaluation (1 min)

**Settings → LLM Connections:** add the Anthropic or OpenAI key. **LLM-as-a-Judge → Create Evaluator:** choose a template (e.g. *Helpfulness*), target traces with tag `simulated`, and sample 50%. New production traces now get scored continuously, alongside the offline experiments.

## 8. It's all in VeloDB (1 min)

```bash
make verify
```

This connects to the warehouse over the MySQL protocol, lists the Litefuse tables with their row counts (spans, traces, scores, dataset run items), and joins traces with spans to show observations, LLM calls, errors and cost per trace. It is the same data you just saw in the UI.

> "The trace data sits in a SQL warehouse, so you can query it directly and join it with your other data."
