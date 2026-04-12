import os
from .simulator_provider import SimulatorCallProvider
from .twilio_provider import TwilioCallProvider


def get_call_provider():
    provider = os.getenv("CALL_PROVIDER", "twilio").lower()
    if provider == "simulator":
        return SimulatorCallProvider()
    elif provider == "twilio":
        return TwilioCallProvider()
    else:
        raise ValueError(f"Unsupported CALL_PROVIDER: {provider}")


