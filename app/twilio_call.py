from twilio.rest import Client
from .config import get_settings


def place_outbound_call(to_number: str, twiml_url: str) -> str:
    """
    Initiate an outbound call via Twilio to `to_number`, instructing Twilio to fetch TwiML at `twiml_url`.
    Returns the created Call SID.
    """
    settings = get_settings()
    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    call = client.calls.create(
        to=to_number,
        from_=settings.twilio_from_number,
        url=twiml_url,
        method="POST",
    )
    return call.sid


