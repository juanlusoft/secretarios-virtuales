from __future__ import annotations

import json
import re
from dataclasses import dataclass

from openai import AsyncOpenAI

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


class ChatClient:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    async def complete(
        self,
        messages: list[dict],
        system: str | None = None,
    ) -> str:
        all_messages: list[dict] = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=all_messages,  # type: ignore[arg-type]
        )
        content = response.choices[0].message.content or ""
        return _THINK_RE.sub("", content).strip()

    async def complete_with_tools(
        self,
        messages: list[dict],
        system: str | None,
        tools: list[dict],
    ) -> tuple[str | None, list[ToolCall]]:
        """Single LLM call with tool support.

        Returns (text, []) when the model gives a final answer.
        Returns (None, tool_calls) when the model wants to call tools.
        """
        all_messages: list[dict] = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=all_messages,  # type: ignore[arg-type]
            tools=tools,  # type: ignore[arg-type]
            tool_choice="auto",
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    args=json.loads(tc.function.arguments),
                )
                for tc in msg.tool_calls
            ]
            return None, calls

        content = msg.content or ""
        return _THINK_RE.sub("", content).strip(), []
