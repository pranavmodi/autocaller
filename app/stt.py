from typing import Optional
from pathlib import Path
from openai import OpenAI
from .config import get_settings


def transcribe_audio(audio_url: str) -> str:
    """
    Placeholder for STT via audio download + Whisper, if needed.
    In this POC, we prefer Twilio-provided SpeechResult and generally won't need this.
    """
    # Not used in this STEP 3 POC; return empty string to indicate no transcription.
    return ""


def transcribe_audio_file(file_path: str) -> str:
    """
    Transcribe a local audio file using OpenAI Speech-to-Text.
    """
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(file_path)
    # Use a stable STT model; adjust as needed based on account availability
    with open(p, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="gpt-4o-transcribe",
            file=f,
        )
    text = getattr(transcript, "text", "") or ""
    return text.strip()


