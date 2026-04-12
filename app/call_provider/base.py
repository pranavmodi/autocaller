from abc import ABC, abstractmethod


class CallProvider(ABC):
    @abstractmethod
    def start_call(self):
        """Begin a call or simulation."""
        pass

    @abstractmethod
    def receive_audio(self):
        """Receive audio input (simulator may implement; Twilio uses webhooks)."""
        pass

    @abstractmethod
    def send_audio(self, audio_bytes: bytes):
        """Send/Play audio (simulator plays locally; Twilio uses <Play>)."""
        pass

    @abstractmethod
    def end_call(self):
        """End the call."""
        pass


