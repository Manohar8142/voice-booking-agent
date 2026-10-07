"""Runtime settings, read from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:  # python-dotenv is optional at runtime
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # LLM (any OpenAI-compatible chat-completions endpoint: OpenAI, Groq, ...)
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"))

    # ElevenLabs streaming TTS
    elevenlabs_api_key: str = field(default_factory=lambda: os.getenv("ELEVENLABS_API_KEY", ""))
    elevenlabs_voice_id: str = field(default_factory=lambda: os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"))
    elevenlabs_model: str = field(default_factory=lambda: os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5"))

    # Twilio
    twilio_auth_token: str = field(default_factory=lambda: os.getenv("TWILIO_AUTH_TOKEN", ""))
    public_base_url: str = field(default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "http://localhost:8000"))
    human_agent_number: str = field(default_factory=lambda: os.getenv("HUMAN_AGENT_NUMBER", ""))

    # Policy: bookings above this total need a human to approve them
    handoff_amount_threshold: float = field(default_factory=lambda: _float("HANDOFF_AMOUNT_THRESHOLD", 500.0))

    @property
    def llm_mock(self) -> bool:
        return not self.llm_api_key

    @property
    def tts_mock(self) -> bool:
        return not self.elevenlabs_api_key


def get_settings() -> Settings:
    return Settings()
