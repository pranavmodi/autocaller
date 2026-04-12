import os
from pathlib import Path

from openai import OpenAI
from .config import get_settings


def ensure_parent_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def generate_tts_mp3(
    text: str,
    output_path: str,
    *,
    model: str = "gpt-4o-mini-tts",
    voice: str = "alloy",
    overwrite: bool = True,
) -> str:
    """
    Generate an MP3 file with AI speech and save to output_path.
    Returns the absolute file path written.
    """
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    abs_output_path = str(Path(output_path).resolve())
    if not overwrite and os.path.exists(abs_output_path):
        return abs_output_path

    ensure_parent_dir(abs_output_path)

    # Stream TTS audio directly to file for reliability
    with client.audio.speech.with_streaming_response.create(
        model=model,
        voice=voice,
        input=text,
    ) as response:
        response.stream_to_file(abs_output_path)

    return abs_output_path


def generate_ai_audio(text: str) -> str:
    """
    Generate the greeting MP3 once and cache it at app/audio/ai_greeting.mp3.
    If the file exists, reuse it.
    """
    audio_dir = Path(__file__).resolve().parent / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(audio_dir / "ai_greeting.mp3")
    if os.path.exists(output_path):
        return output_path
    return generate_tts_mp3(text=text, output_path=output_path, overwrite=True)


def generate_ai_response_audio(text: str) -> str:
    """
    Generate the single-turn response MP3 at app/audio/ai_response.mp3.
    Always overwrite so each call uses latest content.
    """
    audio_dir = Path(__file__).resolve().parent / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(audio_dir / "ai_response.mp3")
    return generate_tts_mp3(text=text, output_path=output_path, overwrite=True)


