"""Item- and run-level evaluators for the support agent experiments.

Deterministic checks (tool_recall, fact_coverage, policy_compliance) run for free;
helpfulness is scored by an LLM judge using $JUDGE_PROVIDER.
"""

from __future__ import annotations

import json
import re
from statistics import mean

from langfuse import Evaluation

from demo.llm import get_provider

# Tools that change an order. Calling one when the case requires no action is a failure.
STATE_CHANGING_TOOLS = {"issue_refund", "cancel_order"}


def tool_recall(*, output, expected_output, **_) -> Evaluation:
    expected = set(expected_output.get("expected_tools") or [])
    called = set(output.get("tools_called") or [])
    if not expected:
        # Nothing required; only penalize state-changing actions.
        unexpected = sorted(called & STATE_CHANGING_TOOLS)
        return Evaluation(name="tool_recall", value=0.0 if unexpected else 1.0,
                          comment="no tool required" + (f"; unexpected {unexpected}" if unexpected else ""))
    hit = expected & called
    return Evaluation(
        name="tool_recall",
        value=len(hit) / len(expected),
        comment=f"expected {sorted(expected)}, called {sorted(called)}",
    )


def fact_coverage(*, output, expected_output, **_) -> list[Evaluation]:
    groups = expected_output.get("must_mention") or []
    if not groups:
        return []
    answer = (output.get("answer") or "").lower()
    missing = [g[0] for g in groups if not any(v.lower() in answer for v in g)]
    return [Evaluation(
        name="fact_coverage",
        value=(len(groups) - len(missing)) / len(groups),
        comment="all facts present" if not missing else f"missing: {missing}",
    )]


def policy_compliance(*, output, expected_output, **_) -> Evaluation:
    refunds = set(output.get("refunds") or [])
    forbidden = set(expected_output.get("must_not_refund") or [])
    required = set(expected_output.get("should_refund") or [])
    cancels = set(output.get("cancellations") or [])
    required_cancels = set(expected_output.get("should_cancel") or [])
    problems = []
    if "*" in forbidden and refunds:
        problems.append(f"refunded {sorted(refunds)} without verification")
    elif bad := refunds & forbidden:
        problems.append(f"refunded {sorted(bad)} against policy")
    if missing := required - refunds:
        problems.append(f"did not refund {sorted(missing)}")
    if missing := required_cancels - cancels:
        problems.append(f"did not cancel {sorted(missing)}")
    if extra := cancels - required_cancels:
        problems.append(f"cancelled {sorted(extra)} without being asked")
    return Evaluation(
        name="policy_compliance",
        value=0.0 if problems else 1.0,
        data_type="NUMERIC",
        comment="; ".join(problems) or "ok",
    )


JUDGE_SYSTEM = """You grade replies from an outdoor-gear store's customer support agent.
Score HELPFULNESS from 1 to 5:
5 = correct, grounded, complete, follows store policy, concise
4 = correct with minor omissions or verbosity
3 = partially helpful or partially incorrect
2 = mostly unhelpful or contains a material error
1 = wrong, harmful, violates policy (e.g. refunds outside the 30-day window), or ignores the question
Compare against the reference answer, but accept other correct phrasings.
Reply with only a JSON object: {"score": <1-5>, "reason": "<one sentence>"}"""

_judge = None


def helpfulness_judge(*, input, output, expected_output, **_) -> list[Evaluation]:
    global _judge
    _judge = _judge or get_provider(judge=True)
    user = (
        f"Customer message:\n{input['message']}\n\n"
        f"Agent reply:\n{output.get('answer')}\n\n"
        f"Actions taken: tools={output.get('tools_called')}, refunds={output.get('refunds')}, "
        f"cancellations={output.get('cancellations')}\n\n"
        f"Reference answer:\n{expected_output.get('reference')}"
    )
    turn = _judge.chat(JUDGE_SYSTEM, [_judge.user_message(user)], name="judge.helpfulness")
    m = re.search(r"\{.*\}", turn.text, re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
        score = float(data["score"])
    except (ValueError, KeyError, TypeError):
        # No helpfulness score: a 0 on a 1-5 scale would drag the run average down.
        # Record the failure as its own boolean score so it stays visible.
        return [Evaluation(name="judge_error", value=1, data_type="BOOLEAN",
                           comment=f"unparseable judge output: {turn.text[:200]}")]
    return [Evaluation(name="helpfulness", value=score, comment=data.get("reason", ""))]


ITEM_EVALUATORS = [tool_recall, fact_coverage, policy_compliance, helpfulness_judge]


def averages(*, item_results, **_) -> list[Evaluation]:
    by_name: dict[str, list[float]] = {}
    for r in item_results:
        for e in r.evaluations:
            if e.data_type in (None, "NUMERIC") and isinstance(e.value, (int, float)):
                by_name.setdefault(e.name, []).append(float(e.value))
    return [
        Evaluation(name=f"avg_{name}", value=round(mean(vals), 3), comment=f"n={len(vals)}")
        for name, vals in sorted(by_name.items())
    ]
