from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from shared.audio.whisper import WhisperClient

_MAX_DURATION_S = 7200  # 2 hours


class YouTubeTranscriber:
    def __init__(self, whisper: WhisperClient) -> None:
        self._whisper = whisper

    async def transcribe(self, url: str) -> str:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = await self._download_audio(url, tmpdir)
            audio_bytes = Path(audio_path).read_bytes()
        text = await self._whisper.transcribe(audio_bytes, filename="audio.mp3")
        return text

    async def _download_audio(self, url: str, output_dir: str) -> str:
        out_template = str(Path(output_dir) / "%(id)s.%(ext)s")
        cmd = [
            "yt-dlp",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "5",
            "--max-filesize", "100M",
            "--no-playlist",
            "-o", out_template,
            "--print", "after_move:filepath",
            url,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("yt-dlp tardó demasiado (>5min)")

        if proc.returncode != 0:
            err = stderr.decode(errors="replace")[:500]
            raise RuntimeError(f"yt-dlp error: {err}")

        filepath = stdout.decode().strip().splitlines()[-1]
        if not filepath or not Path(filepath).exists():
            files = list(Path(output_dir).glob("*.mp3"))
            if not files:
                raise RuntimeError("No se pudo encontrar el audio descargado")
            filepath = str(files[0])
        return filepath
