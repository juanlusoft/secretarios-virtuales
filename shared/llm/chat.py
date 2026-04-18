import re

from openai import AsyncOpenAI

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class ChatClient:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    async def complete(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
    ) -> str:
        all_messages: list[dict[str, str]] = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=all_messages,  # type: ignore[arg-type]
        )
        content = response.choices[0].message.content or ""
        return _THINK_RE.sub("", content).strip()
