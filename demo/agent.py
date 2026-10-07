"""Tool-using customer-support agent, instrumented for Litefuse.

Trace shape per user turn:

    support-agent            (agent)      user_id / session_id / tags / prompt version
      ├─ llm.step-1          (generation) model, tokens, cost, linked prompt version
      ├─ lookup_order        (tool)       args -> result, ERROR level on failure
      ├─ llm.step-2          (generation)
      └─ ...

Try it:  uv run python -m demo.agent "Where is my order VO-1002?"
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field

from langfuse import get_client, propagate_attributes

from demo import prompts
from demo.config import PROMPT_NAME
from demo.llm import Provider, get_provider
from demo.tools import TODAY, TOOL_FUNCS, TOOL_SPECS, ToolError

MAX_STEPS = 6


@dataclass
class AgentResult:
    answer: str
    tools_called: list[str]
    tool_errors: int
    refunds: list[str]
    cancellations: list[str]
    trace_id: str | None
    steps: int
    prompt_version: int | None = None

    def as_output(self) -> dict:
        return {
            "answer": self.answer,
            "tools_called": self.tools_called,
            "refunds": self.refunds,
            "cancellations": self.cancellations,
            "tool_errors": self.tool_errors,
            "steps": self.steps,
        }


@dataclass
class SupportAgent:
    provider: Provider
    prompt_label: str = "production"
    history: list = field(default_factory=list)

    def _system_prompt(self):
        lf = get_client()
        fallback = prompts.V2 if self.prompt_label != "v1" else prompts.V1
        prompt = lf.get_prompt(PROMPT_NAME, label=self.prompt_label, cache_ttl_seconds=300, fallback=fallback)
        return prompt, prompt.compile(today=TODAY.isoformat())

    def respond(
        self,
        user_text: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        trace_name: str | None = "support-agent",
    ) -> AgentResult:
        lf = get_client()
        prompt, system = self._system_prompt()
        version = getattr(prompt, "version", None)
        attrs = dict(
            user_id=user_id,
            session_id=session_id,
            tags=[f"provider:{self.provider.name}", f"prompt:{self.prompt_label}", *(tags or [])],
            metadata={"model": self.provider.model, "prompt_label": self.prompt_label},
            version=f"prompt-v{version}" if version else None,
        )
        if trace_name:
            attrs["trace_name"] = trace_name

        with propagate_attributes(**attrs):
            with lf.start_as_current_observation(
                as_type="agent", name="support-agent", input={"message": user_text}
            ) as agent_obs:
                result = self._loop(user_text, system, prompt)
                result.prompt_version = version
                agent_obs.update(
                    output=result.as_output(),
                    level="WARNING" if result.tool_errors else None,
                )
                lf.set_current_trace_io(input=user_text, output=result.answer)
                result.trace_id = lf.get_current_trace_id()
        return result

    def _loop(self, user_text: str, system: str, prompt) -> AgentResult:
        lf = get_client()
        self.history.append(self.provider.user_message(user_text))
        tools_called: list[str] = []
        refunds: list[str] = []
        cancellations: list[str] = []
        errors = 0

        for step in range(1, MAX_STEPS + 1):
            turn = self.provider.chat(
                system, self.history, TOOL_SPECS, name=f"llm.step-{step}", prompt=prompt
            )
            self.history.append(turn.assistant_message)
            if turn.stop_reason == "refusal":
                answer = "Sorry, I can't help with that request."
                return AgentResult(answer, tools_called, errors, refunds, cancellations, None, step)
            if not turn.tool_calls:
                return AgentResult(turn.text, tools_called, errors, refunds, cancellations, None, step)

            results = []
            for call in turn.tool_calls:
                tools_called.append(call.name)
                with lf.start_as_current_observation(
                    as_type="tool", name=call.name, input=call.args
                ) as tool_obs:
                    try:
                        out = TOOL_FUNCS[call.name](**call.args)
                        payload, is_err = json.dumps(out), False
                        tool_obs.update(output=out)
                        if call.name == "issue_refund":
                            refunds.append(out["order_id"])
                        elif call.name == "cancel_order":
                            cancellations.append(out["order_id"])
                    except (ToolError, TypeError, KeyError) as exc:
                        errors += 1
                        payload, is_err = str(exc), True
                        tool_obs.update(output={"error": str(exc)}, level="ERROR", status_message=str(exc))
                results.append((call, payload, is_err))
            self.history.extend(self.provider.tool_results(results))

        answer = "I've passed this to a human colleague who will follow up shortly."
        return AgentResult(answer, tools_called, errors, refunds, cancellations, None, MAX_STEPS)


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask the support agent one question.")
    ap.add_argument("message", nargs="?", default="Hi, where is my order VO-1002?")
    ap.add_argument("--provider", help="claude | openai (default: $LLM_PROVIDER)")
    ap.add_argument("--label", default="production", help="prompt label: v1 | v2 | production")
    ap.add_argument("--user", default="u-cli")
    args = ap.parse_args()

    agent = SupportAgent(get_provider(args.provider), prompt_label=args.label)
    res = agent.respond(args.message, user_id=args.user, session_id="cli-session")
    print(res.answer)
    print(f"\ntools: {res.tools_called}  refunds: {res.refunds}  cancellations: {res.cancellations}  steps: {res.steps}")
    lf = get_client()
    lf.flush()
    if res.trace_id:
        print(f"trace: {lf.get_trace_url(trace_id=res.trace_id)}")


if __name__ == "__main__":
    main()
