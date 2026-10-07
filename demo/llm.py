"""One chat interface over Claude (Anthropic SDK) and any OpenAI-compatible endpoint.

Every model call is recorded as a Litefuse *generation* observation with model,
parameters, token usage and cost, so traces look the same whichever provider ran.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from langfuse import get_client

from demo.config import env, price_for


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str
    usage: dict[str, int]
    assistant_message: Any = field(repr=False)  # provider-native message to append to history


class Provider:
    name: str
    model: str

    # -- history helpers (provider-native message formats) --
    def user_message(self, text: str) -> Any: ...
    def tool_results(self, results: list[tuple[ToolCall, str, bool]]) -> list[Any]: ...

    def _call(self, system: str, messages: list, tools: list[dict] | None) -> Turn: ...
    def _params(self) -> dict: ...

    def chat(
        self,
        system: str,
        messages: list,
        tools: list[dict] | None = None,
        *,
        name: str = "llm",
        prompt=None,
    ) -> Turn:
        lf = get_client()
        with lf.start_as_current_observation(
            as_type="generation",
            name=name,
            model=self.model,
            model_parameters=self._params(),
            input=[{"role": "system", "content": system}, *messages],
            metadata={"provider": self.name, "tools": [t["name"] for t in tools or []]},
            prompt=prompt,
        ) as gen:
            try:
                turn = self._call(system, messages, tools)
            except Exception as exc:
                gen.update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}")
                raise
            output: dict[str, Any] = {"role": "assistant", "content": turn.text}
            if turn.tool_calls:
                output["tool_calls"] = [{"name": c.name, "arguments": c.args} for c in turn.tool_calls]
            update: dict[str, Any] = {"output": output, "usage_details": turn.usage}
            prices = price_for(self.name, self.model)
            if prices:
                cin = turn.usage.get("input", 0) * prices[0] / 1e6
                cout = turn.usage.get("output", 0) * prices[1] / 1e6
                update["cost_details"] = {"input": cin, "output": cout, "total": cin + cout}
            if turn.stop_reason == "refusal":
                update |= {"level": "WARNING", "status_message": "model refused"}
            gen.update(**update)
            return turn


class ClaudeProvider(Provider):
    name = "claude"

    # Models that accept server-side refusal fallbacks in the `fallbacks: "default"` form.
    # Exact IDs: a prefix match would also catch models that don't (e.g. claude-fable-5).
    _FALLBACK_MODELS = frozenset({"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"})
    # Models without adaptive thinking or effort (they would return a 400).
    _NO_ADAPTIVE_MODELS = ("claude-haiku-4-5",)

    def __init__(self, model: str | None = None):
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model or env("CLAUDE_MODEL", "claude-opus-5")
        self.effort = env("CLAUDE_EFFORT", "medium")

    @property
    def _adaptive(self) -> bool:
        return not self.model.startswith(self._NO_ADAPTIVE_MODELS)

    def _params(self) -> dict:
        if not self._adaptive:
            return {"max_tokens": 16000}
        return {"max_tokens": 16000, "thinking": "adaptive", "effort": self.effort}

    def user_message(self, text: str) -> dict:
        return {"role": "user", "content": text}

    def tool_results(self, results):
        return [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": c.id, "content": out, "is_error": err}
                    for c, out, err in results
                ],
            }
        ]

    def _call(self, system, messages, tools):
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=messages,
        )
        if self._adaptive:
            kwargs |= {"thinking": {"type": "adaptive"}, "output_config": {"effort": self.effort}}
        if tools:
            kwargs["tools"] = [
                {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                for t in tools
            ]
        if self.model in self._FALLBACK_MODELS:
            kwargs |= {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
            resp = self.client.beta.messages.create(**kwargs)
        else:
            resp = self.client.messages.create(**kwargs)

        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = []
        if resp.stop_reason == "tool_use":
            calls = [
                ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"
            ]
        usage = {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}
        if getattr(resp.usage, "cache_read_input_tokens", None):
            usage["cache_read_input_tokens"] = resp.usage.cache_read_input_tokens
        return Turn(
            text=text,
            tool_calls=calls,
            stop_reason=resp.stop_reason or "",
            usage=usage,
            assistant_message={"role": "assistant", "content": self._echoable(resp.content)},
        )

    @staticmethod
    def _echoable(content: list) -> list:
        """Content blocks to send back next turn.

        After a mid-output refusal fallback, thinking / tool_use blocks produced before
        the last `fallback` marker must not be echoed; the marker itself is dropped.
        """
        idx = max((i for i, b in enumerate(content) if b.type == "fallback"), default=-1)
        keep = []
        for i, b in enumerate(content):
            if b.type == "fallback":
                continue
            if i < idx and b.type in ("thinking", "redacted_thinking", "tool_use"):
                continue
            keep.append(b)
        return keep


class OpenAICompatProvider(Provider):
    name = "openai"

    def __init__(self, model: str | None = None):
        import openai

        self.client = openai.OpenAI(
            api_key=env("OPENAI_API_KEY") or "not-needed",
            base_url=env("OPENAI_BASE_URL") or None,
        )
        self.model = model or env("OPENAI_MODEL", "gpt-5-mini")

    def _params(self) -> dict:
        return {"base_url": str(self.client.base_url)}

    def user_message(self, text: str) -> dict:
        return {"role": "user", "content": text}

    def tool_results(self, results):
        return [
            {"role": "tool", "tool_call_id": c.id, "content": ("ERROR: " if err else "") + out}
            for c, out, err in results
        ]

    def _call(self, system, messages, tools):
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=[{"role": "system", "content": system}, *messages],
        )
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["parameters"],
                    },
                }
                for t in tools
            ]
        resp = self.client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            calls.append(ToolCall(tc.id, tc.function.name, args))
        usage = {}
        if resp.usage:
            usage = {"input": resp.usage.prompt_tokens, "output": resp.usage.completion_tokens}
        assistant = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant["tool_calls"] = [tc.model_dump(exclude_none=True) for tc in msg.tool_calls]
        return Turn(
            text=msg.content or "",
            tool_calls=calls,
            stop_reason=choice.finish_reason or "",
            usage=usage,
            assistant_message=assistant,
        )


def get_provider(name: str | None = None, *, judge: bool = False) -> Provider:
    name = (name or env("JUDGE_PROVIDER" if judge else "LLM_PROVIDER", "claude")).lower()
    if name in ("claude", "anthropic"):
        return ClaudeProvider(env("CLAUDE_JUDGE_MODEL") if judge else None)
    if name in ("openai", "openai-compatible"):
        return OpenAICompatProvider(env("OPENAI_JUDGE_MODEL") if judge else None)
    raise ValueError(f"unknown provider {name!r} (use 'claude' or 'openai')")
