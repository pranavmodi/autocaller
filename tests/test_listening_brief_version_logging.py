from app.services import comms_log, email_notification_service


class _FakeConnection:
    def __init__(self):
        self.params = None

    def execute(self, statement, params):  # noqa: ANN001
        self.params = params


class _FakeBegin:
    def __init__(self, connection: _FakeConnection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False


class _FakeEngine:
    def __init__(self):
        self.connection = _FakeConnection()

    def begin(self):
        return _FakeBegin(self.connection)


def test_listening_brief_version_is_inserted_on_email_log(monkeypatch):
    engine = _FakeEngine()
    monkeypatch.setattr(comms_log, "_engine", lambda: engine)

    comms_log.log_email(
        recipient_email="lead@example.com",
        subject="Subject",
        body="Body",
        message_type="dynamic_lead_email",
        brief_version=2,
    )

    assert engine.connection.params["brief_version"] == 2


def test_listening_brief_version_reaches_email_send_log(monkeypatch):
    calls = []
    monkeypatch.setattr(email_notification_service, "_resolve_sender_address", lambda from_addr: "sender@example.com")
    monkeypatch.setattr(email_notification_service, "_choose_email_transport", lambda transport: "zoho_api")
    monkeypatch.setattr(email_notification_service, "_send_via_zoho_api", lambda **kwargs: "msg-1")
    monkeypatch.setattr(email_notification_service, "log_email", lambda **kwargs: calls.append(kwargs))

    msg_id = email_notification_service._send_email(
        "Subject",
        "Body",
        to="lead@example.com",
        message_type="dynamic_lead_email",
        transport="zoho_api",
        brief_version=2,
    )

    assert msg_id == "msg-1"
    assert calls[0]["brief_version"] == 2
