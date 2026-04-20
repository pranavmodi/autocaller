"""Voice personas for the autocaller.

Each persona defines a rep name, last name, and voice settings per
provider (OpenAI Realtime voice name, Gemini Live voice name).
The persona is selected per-call via CLI --persona or UI dropdown.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Persona:
    key: str
    rep_name: str
    last_name: str
    openai_voice: str
    gemini_voice: str


PERSONAS = {
    "alex": Persona(
        key="alex",
        rep_name="Alex",
        last_name="Mitchell",
        openai_voice="alloy",
        gemini_voice="Charon",
    ),
    "natalia": Persona(
        key="natalia",
        rep_name="Natalia",
        last_name="Rivera",
        openai_voice="shimmer",
        gemini_voice="Aoede",
    ),
}

DEFAULT_PERSONA = "alex"


def get_persona(key: Optional[str] = None) -> Persona:
    """Resolve a persona by key. Defaults to alex."""
    k = (key or "").strip().lower() or DEFAULT_PERSONA
    return PERSONAS.get(k, PERSONAS[DEFAULT_PERSONA])
