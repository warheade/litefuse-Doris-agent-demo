# Litefuse + VeloDB: agent observability & evaluation demo

A customer-support agent for a fictional outdoor-gear store ("Velo Outdoor") is traced
and evaluated with **[Litefuse](https://github.com/litefuse/litefuse)**, the Langfuse-compatible
LLM engineering platform whose analytics backend is **Apache Doris**, here running on
**VeloDB Cloud**.

```
 ┌──────────────── your laptop (Docker) ────────────────┐        ┌──── VeloDB Cloud ────┐
 │  demo agent ──OTel/HTTP──▶ litefuse-web :3000         │        │                      │
 │  (Claude or OpenAI-      │  litefuse-worker ──────────┼─Stream─▶  spans_* / traces_*  │
 │   compatible, langfuse   │  postgres · redis · minio  │  Load  │  scores / datasets   │
 │   Python SDK)            │  (metadata, queue, blobs)  │◀─MySQL─┤  (Doris 4 engine)    │
 └───────────────────────────────────────────────────────┘        └──────────────────────┘
```

* The official `langfuse` Python SDK talks to Litefuse unchanged. Only `LANGFUSE_HOST` changes.
* Traces, observations and scores are written to VeloDB with Stream Load and queried back over the MySQL protocol.
* The agent runs on **Claude** (Anthropic SDK) or **any OpenAI-compatible endpoint** (OpenAI, Qwen/DashScope, DeepSeek, vLLM, Ollama). Both produce identical traces.

## What the demo shows

| Area | What you'll see |
|---|---|
| Tracing | Agent → generation → tool span trees, token usage + cost per call, failed tool calls at ERROR level |
| Sessions / Users | Multi-turn conversations grouped by `session_id`; per-user cost and activity |
| Prompt management | `support-system` v1 vs v2, with each generation linked to the prompt version that produced it |
| Scores | Simulated user thumbs up/down, session `resolution`, and `policy-violation` flags |
| Datasets & experiments | `support-golden` (15 cases); runs for prompt v1 vs v2 scored by 3 code evaluators + an LLM judge, compared side by side |
| VeloDB | `make verify` queries the warehouse directly to show that the data lives there |

## Prerequisites

1. **Docker**: [OrbStack](https://orbstack.dev) or Docker Desktop.
2. **A VeloDB Cloud warehouse.** In the console, open *Connection* and note:
   * the **HTTP endpoint** (used for Stream Load), with the scheme and port the page shows, e.g. `http://<host>:8080`. It is not part of the JDBC URL.
   * the **MySQL port** (usually `9030`), the user and the password
   * Allow-list your public IP for both ports.
3. **An LLM key:** `ANTHROPIC_API_KEY`, and/or an OpenAI-compatible key, base URL and model.
4. **[uv](https://docs.astral.sh/uv/)** for the Python side.

## Quickstart

```bash
cp .env.example .env         # fill in VeloDB + LLM settings
make up                      # Litefuse on http://localhost:3000; the schema is created in VeloDB
make seed                    # prompt v1/v2 + golden dataset
make simulate                # ~25 multi-turn sessions, mixed providers & prompt versions
make compare                 # dataset experiments: prompt v1 then v2
make verify                  # read it all back straight from VeloDB
```

Log in at <http://localhost:3000> with `demo@velodb.io` / `velodb-demo` (set in `.env`).
The org, project and API keys are created on first boot, so no clicking is needed.

Other commands:

```bash
make ask Q="Can I return my jacket? Order VO-1003"          # one question, prints trace URL
make ask Q="Where is VO-1002?" PROVIDER=openai
make experiment LABEL=v2 PROVIDER=openai                     # same dataset, other model
make simulate SESSIONS=60
make logs / make down / make reset
```

The presenter script is in **[WALKTHROUGH.md](WALKTHROUGH.md)**.

## Project layout

```
deploy/docker-compose.yml   Litefuse 26.2.0 minus the bundled Doris; DORIS_* → VeloDB
demo/llm.py                 Claude / OpenAI-compatible providers; each call is a Litefuse generation
demo/tools.py               mock store backend (orders, KB, inventory, refunds, cancellations) + tool schemas
demo/agent.py               tool-use loop: agent span → generation + tool spans, user/session/tags
demo/prompts.py             registers support-system v1 (naive) and v2 (explicit refund policy)
demo/simulate.py            multi-turn traffic + user-feedback / resolution / policy scores
demo/eval/dataset.py        support-golden dataset (15 items with expectations)
demo/eval/evaluators.py     tool_recall, fact_coverage, policy_compliance, helpfulness (LLM judge)
demo/eval/run_experiment.py dataset.run_experiment(...) + summary table
demo/verify_velodb.py       direct MySQL-protocol queries against VeloDB
```

## Configuration notes

* **Models.** Without a `CLAUDE_MODEL` setting the code uses `claude-opus-5` with adaptive thinking at `CLAUDE_EFFORT=medium`. `.env.example` sets `claude-haiku-4-5`, the model behind the measured results in DESIGN.md, because it shows the clearest prompt v1 vs v2 contrast; Haiku 4.5 runs without adaptive thinking or effort. On `claude-opus-5`, `claude-opus-5-5`, `claude-sonnet-5-5` and `claude-fable-5-1` the agent enables server-side refusal fallbacks (`fallbacks: "default"`), so a safety-classifier decline is retried on a fallback model instead of failing the turn. The judge model is set separately (`CLAUDE_JUDGE_MODEL`, `OPENAI_JUDGE_MODEL`).
* **Cost.** The demo sends `cost_details` for Claude models from a small price table in `demo/config.py`. For OpenAI-compatible models, set `OPENAI_PRICE_INPUT_PER_MTOK` / `OPENAI_PRICE_OUTPUT_PER_MTOK`, or define the model under Litefuse *Settings → Models*.
* **Errors.** `TOOL_FAIL_RATE` (default 0.08) injects tool timeouts so that traces contain realistic ERROR spans.

## Troubleshooting

* **Web container restarts and the logs mention Doris.** Check that the VeloDB MySQL port is reachable: `mysql -h <host> -P 9030 -u admin -p`. Also check that your IP is on the warehouse allow-list.
* **Stream Load fails (HTTP 307 / connection refused to a private IP).** Use the warehouse's **public HTTP endpoint** for `DORIS_FE_HTTP_URL`. A private endpoint only works when Docker runs in the same VPC.
* **Worker logs `Doris query failed: Connection lost` about once a day.** The warehouse closed an open MySQL connection. Litefuse reconnects on the next query, so no action is needed unless it happens during a demo. Litefuse 26.2.0 has no setting for its pool's idle behaviour.
* **Traces don't appear.** Ingestion is async (worker → VeloDB). Wait a few seconds, then check `make logs`.
* **`make verify` lists no split tables.** Litefuse creates the per-project `spans_<project>` / `traces_scalar_<project>` tables on first ingest. Run `make simulate` first.
