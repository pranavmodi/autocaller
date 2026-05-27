#!/usr/bin/env bash
set -euo pipefail

.venv/bin/python -m pytest \
  --cov=app.models \
  --cov=app.services.phone_normalize \
  --cov=app.services.firm_blocklist \
  --cov=app.services.autorespond_signals \
  --cov=app.services.carrier_failure_service \
  --cov=app.services.transfer_service \
  --cov=app.services.twilio_sms_service \
  --cov=app.services.notification_service \
  --cov=app.services.carrier \
  --cov=app.services.voice.factory \
  --cov-report=term-missing \
  --cov-fail-under=90
