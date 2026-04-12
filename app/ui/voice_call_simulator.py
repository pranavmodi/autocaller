import os
import threading
from pathlib import Path
from typing import List, Tuple

import sys
# Ensure project root is on sys.path so `import app.*` works when run via Streamlit
PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import sounddevice as sd
import soundfile as sf
import streamlit as st

from app.tts import generate_ai_audio, generate_ai_response_audio
from app.llm import generate_ai_reply
from app.stt import transcribe_audio_file


SAMPLE_RATE = 16000
CHANNELS = 1
MAX_SECONDS = 5.0
FRAME_DURATION_SEC = 0.1  # 100ms
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_DURATION_SEC)
SILENCE_RMS_THRESHOLD = 0.02  # tune as needed
POST_VOICE_SILENCE_SEC = 0.8


def _ensure_session_state():
    defaults = {
        "conversation_log": [],  # list[tuple[str, str]] as (role, content)
        "_loop_thread": None,
        # thread-safe flags (threading.Event)
        "call_event": None,
        "listening_event": None,
        "speaking_event": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
    # initialize events if missing
    if st.session_state["call_event"] is None:
        st.session_state["call_event"] = threading.Event()
    if st.session_state["listening_event"] is None:
        st.session_state["listening_event"] = threading.Event()
    if st.session_state["speaking_event"] is None:
        st.session_state["speaking_event"] = threading.Event()


def _append_log(role: str, content: str):
    st.session_state["conversation_log"].append((role, content))


def record_utterance(call_event: threading.Event, listening_event: threading.Event) -> np.ndarray:
    """
    Record up to MAX_SECONDS; stop early if silence after voice detected.
    Returns mono float32 PCM audio [num_samples].
    """
    listening_event.set()
    frames: List[np.ndarray] = []
    voiced = False
    silent_frames_after_voice = 0
    max_frames = int(MAX_SECONDS / FRAME_DURATION_SEC)

    with sd.InputStream(
        samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32"
    ) as stream:
        for _ in range(max_frames):
            if not call_event.is_set():
                break
            chunk, _ = stream.read(FRAME_SAMPLES)
            chunk = np.squeeze(chunk)
            frames.append(chunk)
            rms = float(np.sqrt(np.mean(np.square(chunk))) + 1e-9)
            if rms > SILENCE_RMS_THRESHOLD:
                voiced = True
                silent_frames_after_voice = 0
            else:
                if voiced:
                    silent_frames_after_voice += 1
                    if silent_frames_after_voice * FRAME_DURATION_SEC >= POST_VOICE_SILENCE_SEC:
                        break
    listening_event.clear()
    if not frames:
        return np.zeros((0,), dtype=np.float32)
    return np.concatenate(frames, axis=0)


def save_wav(data: np.ndarray, path: str):
    sf.write(path, data, SAMPLE_RATE, subtype="PCM_16")


def play_wav(data: np.ndarray, speaking_event: threading.Event):
    speaking_event.set()
    sd.play(data, SAMPLE_RATE)
    sd.wait()
    speaking_event.clear()


def play_file(path: str, speaking_event: threading.Event):
    """
    Attempt to play MP3 via soundfile -> sounddevice if supported; if not, fall back to system open.
    """
    speaking_event.set()
    try:
        audio, sr = sf.read(path, dtype="float32", always_2d=False)
        if sr != SAMPLE_RATE:
            # simple resample with numpy (nearest) to avoid extra deps (quality is ok for POC)
            ratio = SAMPLE_RATE / sr
            new_len = int(len(audio) * ratio)
            idx = (np.arange(new_len) / ratio).astype(np.int32).clip(max=len(audio) - 1)
            audio = audio[idx]
        if audio.ndim > 1:
            audio = audio[:, 0]
        sd.play(audio, SAMPLE_RATE)
        sd.wait()
    except Exception:
        # Fallback to system player
        try:
            if os.name == "posix":
                os.system(f'xdg-open "{path}" >/dev/null 2>&1 &')
            elif os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
        except Exception:
            pass
    speaking_event.clear()


def call_loop(conversation_log: List[Tuple[str, str]], call_event: threading.Event, listening_event: threading.Event, speaking_event: threading.Event):
    try:
        # Greeting
        greet_path = generate_ai_audio("Hello, this is an AI calling you for a test. Thank you.")
        conversation_log.append(("AI", "Hello, this is an AI calling you for a test. Thank you."))
        play_file(greet_path, speaking_event)

        # Conversation loop
        audio_tmp_dir = Path("app") / "audio"
        audio_tmp_dir.mkdir(parents=True, exist_ok=True)

        while call_event.is_set():
            # Record
            audio = record_utterance(call_event, listening_event)
            if not call_event.is_set():
                break
            if audio.size < SAMPLE_RATE * 0.2:  # ignore very short/no audio
                continue
            wav_path = str(audio_tmp_dir / "sim_user.wav")
            save_wav(audio, wav_path)

            # STT
            user_text = ""
            try:
                user_text = transcribe_audio_file(wav_path)
            except Exception as e:
                conversation_log.append(("system", f"STT error: {e}"))
                continue
            if not user_text:
                continue
            conversation_log.append(("You", user_text))

            # LLM
            ai_text = generate_ai_reply(user_text)
            conversation_log.append(("AI", ai_text))

            # TTS & playback
            resp_path = generate_ai_response_audio(ai_text)
            if not call_event.is_set():
                break
            play_file(resp_path, speaking_event)
    finally:
        call_event.clear()
        listening_event.clear()
        speaking_event.clear()


def main():
    st.set_page_config(page_title="Voice AI Call Simulator (Local)")
    _ensure_session_state()

    st.title("Voice AI Call Simulator (Local)")

    # Controls
    cols = st.columns(2)
    with cols[0]:
        if st.button("📞 Start Call", type="primary", disabled=st.session_state["call_event"].is_set()):
            if not st.session_state["call_event"].is_set():
                # set active and start thread
                st.session_state["call_event"].set()
                t = threading.Thread(
                    target=call_loop,
                    args=(
                        st.session_state["conversation_log"],
                        st.session_state["call_event"],
                        st.session_state["listening_event"],
                        st.session_state["speaking_event"],
                    ),
                    daemon=True,
                )
                st.session_state["_loop_thread"] = t
                t.start()
    with cols[1]:
        if st.button("📴 Hang Up", disabled=not st.session_state["call_event"].is_set()):
            st.session_state["call_event"].clear()

    # Status
    status = "Idle"
    if st.session_state["call_event"].is_set():
        if st.session_state["speaking_event"].is_set():
            status = "AI speaking"
        elif st.session_state["listening_event"].is_set():
            status = "Listening..."
        else:
            status = "Call started"
    else:
        # If just ended
        status = "Call ended" if st.session_state.get("_loop_thread") else "Idle"
    st.write(f"Status: {status}")

    # Conversation Log
    st.subheader("Conversation Log")
    for role, content in st.session_state["conversation_log"]:
        if role == "You":
            st.markdown(f"- **You**: {content}")
        elif role == "AI":
            st.markdown(f"- **AI**: {content}")
        else:
            st.markdown(f"- {role}: {content}")


if __name__ == "__main__":
    main()


