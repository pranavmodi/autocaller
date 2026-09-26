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


def test_email_log_retains_complete_body(monkeypatch):
    engine = _FakeEngine()
    monkeypatch.setattr(comms_log, "_engine", lambda: engine)
    body = "Opening\n\n" + ("full email body " * 100) + "\n\nSignature"

    comms_log.log_email(
        recipient_email="lead@example.com",
        subject="Subject",
        body=body,
        message_type="dynamic_lead_email",
    )

    assert len(body) > 500
    assert engine.connection.params["body"] == body


def test_email_log_source_identity_is_stable_and_includes_firm(monkeypatch):
    engine = _FakeEngine()
    monkeypatch.setattr(comms_log, "_engine", lambda: engine)

    first = comms_log.log_email(
        recipient_email="jobs@example.com",
        subject="Application",
        body="Attached",
        message_type="job_application",
        transport="zoho_cli",
        status="accepted",
        firm_name="Example LLP",
        source_type="job_application",
        source_id="candidate-1",
    )
    second = comms_log.log_email(
        recipient_email="jobs@example.com",
        subject="Application",
        body="Attached",
        message_type="job_application",
        transport="zoho_cli",
        status="sent_verified",
        firm_name="Example LLP",
        source_type="job_application",
        source_id="candidate-1",
    )

    assert first == second == engine.connection.params["id"]
    assert engine.connection.params["firm_name"] == "Example LLP"
    assert engine.connection.params["source_type"] == "job_application"
    assert engine.connection.params["source_id"] == "candidate-1"


def test_listening_brief_version_reaches_email_send_log(monkeypatch):
    calls = []
    monkeypatch.setattr(email_notification_service, "_resolve_sender_address", lambda from_addr: "sender@example.com")
    monkeypatch.setattr("app.services.review_alerts.outgoing_suppression", lambda *args: False)
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
