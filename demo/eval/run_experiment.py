"""Run the support agent over the golden dataset and score it.

Each run shows up in Litefuse under Datasets → support-golden → Runs, where runs
can be compared side by side (scores, cost, latency, per-item outputs).

    uv run python -m demo.eval.run_experiment --label v1
    uv run python -m demo.eval.run_experiment --label v2
    uv run python -m demo.eval.run_experiment --label v2 --provider openai
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from langfuse import get_client
from rich.console import Console
from rich.table import Table

from demo.agent import SupportAgent
from demo.config import DATASET_NAME
from demo.eval.evaluators import ITEM_EVALUATORS, averages
from demo.llm import get_provider

console = Console()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="v2", help="prompt label to evaluate: v1 | v2 | production")
    ap.add_argument("--provider", help="claude | openai (default: $LLM_PROVIDER)")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    provider = get_provider(args.provider)
    lf = get_client()
    dataset = lf.get_dataset(DATASET_NAME)

    def task(*, item, **_):
        # Fresh agent per item: no conversation history leaks between cases.
        agent = SupportAgent(provider, prompt_label=args.label)
        res = agent.respond(
            item.input["message"],
            user_id=item.input.get("user_id"),
            tags=["experiment"],
            trace_name=None,  # keep the experiment runner's trace name
        )
        return res.as_output() | {"prompt_version": res.prompt_version}

    stamp = datetime.now(timezone.utc).strftime("%m%d-%H%M")
    run_name = f"{provider.name}:{provider.model} prompt={args.label} {stamp}"
    console.print(f"Running [bold]{run_name}[/bold] over {len(dataset.items)} items…")

    result = dataset.run_experiment(
        name="support-agent",
        run_name=run_name,
        description=f"Prompt label {args.label} on {provider.name}/{provider.model}",
        task=task,
        evaluators=ITEM_EVALUATORS,
        run_evaluators=[averages],
        max_concurrency=args.concurrency,
        metadata={"provider": provider.name, "model": provider.model, "prompt_label": args.label},
    )
    lf.flush()

    table = Table(title=run_name)
    table.add_column("case")
    for col in ("tools", "facts", "policy", "judge"):
        table.add_column(col, justify="right")
    names = ["tool_recall", "fact_coverage", "policy_compliance", "helpfulness"]
    for r in result.item_results:
        scores = {e.name: e.value for e in r.evaluations}
        case = (r.item.metadata or {}).get("case", "?")
        cells = []
        for n in names:
            v = scores.get(n)
            if v is None:
                cells.append("–")
            elif n == "policy_compliance" and v < 1:
                cells.append("[red]FAIL[/red]")
            else:
                cells.append(f"{v:.2f}" if n != "helpfulness" else f"{v:.0f}/5")
        table.add_row(case, *cells)
    console.print(table)
    for e in result.run_evaluations:
        console.print(f"  {e.name:<24} {e.value}")
    if result.dataset_run_url:
        console.print(f"\nCompare runs: {result.dataset_run_url}")


if __name__ == "__main__":
    main()
