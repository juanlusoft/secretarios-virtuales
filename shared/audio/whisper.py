import httpx


class WhisperClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def transcribe(self, audio_bytes: bytes, filename: str = "audio.ogg") -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self._base_url}/v1/audio/transcriptions",
                files={"file": (filename, audio_bytes, "audio/ogg")},
                data={"model": "whisper-1"},
            )
        if response.status_code != 200:
            raise RuntimeError(f"Whisper error {response.status_code}: {response.text}")
        payload = response.json()
        text = payload.get("text")
        if not isinstance(text, str):
            raise RuntimeError("Whisper response missing text field")
        return text
