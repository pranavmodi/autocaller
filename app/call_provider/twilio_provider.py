import os
from typing import Optional
from .base import CallProvider

from ..twilio_call import place_outbound_call


class TwilioCallProvider(CallProvider):
    """
    Wrapper around existing Twilio logic.
    Note: The FastAPI app and webhooks remain the primary interface.
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv("PUBLIC_BASE_URL") or ""

    def start_call(self):
        """
        For parity, optionally trigger a call if TO number is provided via env.
        Otherwise, no-op; use the existing /call endpoint as before.
        """
        to_number = os.getenv("TO_NUMBER")
        if self.base_url and to_number:
            place_outbound_call(to_number=to_number, twiml_url=self.base_url.rstrip("/") + "/voice")
        else:
            # No-op: rely on /call endpoint
            pass

    def receive_audio(self):
        # Handled by Twilio webhooks (/voice, /process_speech)
        return None

    def send_audio(self, audio_bytes: bytes):
        # Twilio uses <Play> via webhooks; nothing to do here.
        return None

    def end_call(self):
        # Twilio call lifecycle is managed by Twilio; nothing to do here.
        return None


