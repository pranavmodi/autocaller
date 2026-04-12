import os
import sys
import subprocess
from pathlib import Path
from typing import Optional

from .base import CallProvider
from ..stt import transcribe_audio_file
from ..llm import generate_ai_reply
from ..tts import generate_ai_response_audio, generate_ai_audio


def _play_audio_file(path: str) -> None:
    """
    Best-effort local audio playback without extra deps.
    Tries xdg-open (Linux), open (macOS), or prints a hint.
    """
    p = Path(path)
    if not p.exists():
        return
    try:
        if sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "win32":
            os.startfile(str(p))  # type: ignore[attr-defined]
        else:
            print(f"[simulator] Audio at: {p.resolve()}")
    except Exception:
        print(f"[simulator] Audio at: {p.resolve()}")


class SimulatorCallProvider(CallProvider):
    """
    Local simulator for multi-turn voice conversation.
    - Accepts microphone or file path input (file path recommended to avoid extra deps)
    - Uses OpenAI STT for file inputs
    - Uses OpenAI Chat for reply
    - Uses OpenAI TTS for reply audio
    - Plays audio locally
    """

    def __init__(self):
        self.active = False

    def start_call(self):
        self.active = True
        print("[simulator] Starting simulated call.")
        # Optional: play the same greeting used in production
        greet_path = generate_ai_audio("Hello, this is an AI calling you for a test. Thank you.")
        print("[simulator] Playing greeting...")
        _play_audio_file(greet_path)
        self._conversation_loop()

    def _conversation_loop(self):
        print("[simulator] Enter path to a WAV/MP3 file to simulate speech,")
        print("            or type text directly. Press 'q' to end.")
        while self.active:
            user_input = input("[you] File path or text (q to quit): ").strip()
            if user_input.lower() == "q":
                self.end_call()
                break
            user_text: Optional[str] = None
            # If this looks like a file path, try STT
            if user_input and Path(user_input).exists():
                print("[simulator] Transcribing audio...")
                try:
                    user_text = transcribe_audio_file(user_input)
                except Exception as e:
                    print(f"[simulator] STT error: {e}")
                    user_text = None
            else:
                # Treat input as text fallback
                user_text = user_input

            if not user_text:
                print("[simulator] No text captured. Say/type something else or 'q' to quit.")
                continue

            print(f"[you -> ai] {user_text}")
            ai_text = generate_ai_reply(user_text)
            print(f"[ai -> you] {ai_text}")
            resp_path = generate_ai_response_audio(ai_text)
            _play_audio_file(resp_path)

    def receive_audio(self):
        # Not used in this simple simulator; handled interactively in loop.
        return None

    def send_audio(self, audio_bytes: bytes):
        # We generate and play from file directly; nothing to do here.
        return None

    def end_call(self):
        if self.active:
            print("[simulator] Ending simulated call.")
        self.active = False


