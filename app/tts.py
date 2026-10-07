"""ElevenLabs streaming text-to-speech, with an offline mock."""
from __future__ import annotations

import io
import math
import struct
import wave
from typing import AsyncIterator

import httpx

ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"


class ElevenLabsTTS:
    def __init__(self, api_key: str, voice_id: str, model_id: str) -> None:
        self.api_key, self.voice_id, self.model_id = api_key, voice_id, model_id

    async def stream(self, text: str, output_format: str = "mp3_44100_128") -> AsyncIterator[bytes]:
        """Yield audio chunks as ElevenLabs produces them.

        Use ``output_format="ulaw_8000"`` for Twilio Media Streams (8 kHz mu-law).
        """
        url = ELEVEN_URL.format(voice_id=self.voice_id)
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream(
                "POST",
                url,
                params={"output_format": output_format},
                headers={"xi-api-key": self.api_key, "accept": "audio/mpeg"},
                json={"text": text, "model_id": self.model_id},
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(4096):
                    yield chunk


class MockTTS:
    """Produces a short tone (WAV) or mu-law silence so the pipeline runs offline."""

    async def stream(self, text: str, output_format: str = "wav") -> AsyncIterator[bytes]:
        seconds = min(0.06 * len(text.split()) + 0.3, 5.0)
        if output_format.startswith("ulaw"):
            total = int(8000 * seconds)
            for i in range(0, total, 160):  # 20 ms frames
                yield b"\xff" * min(160, total - i)
            return
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            frames = b"".join(
                struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * t / 16000))) for t in range(int(16000 * seconds))
            )
            w.writeframes(frames)
        yield buf.getvalue()


def get_tts(settings) -> ElevenLabsTTS | MockTTS:
    if settings.tts_mock:
        return MockTTS()
    return ElevenLabsTTS(settings.elevenlabs_api_key, settings.elevenlabs_voice_id, settings.elevenlabs_model)
