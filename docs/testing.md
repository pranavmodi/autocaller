# Testing

Install development test dependencies:

```bash
.venv/bin/pip install -r requirements-dev.txt
```

Run the test suite:

```bash
.venv/bin/python -m pytest
```

Run the current 90% unit-coverage gate:

```bash
bash scripts/test-unit-coverage.sh
```

This gate covers the core unit-tested surface: models plus pure service logic
for phone normalization, firm blocklists, autorespond signals, carrier-failure
handling, transfer routing, SMS/notification handling, carrier resolution, and
voice-provider resolution.

Run full-app coverage separately:

```bash
.venv/bin/python -m pytest --cov --cov-report=term-missing
```

Full-app coverage includes API routes, CLI commands, providers, daemon startup,
and orchestration modules. It is intentionally tracked separately because those
areas need integration-style tests and dependency fakes before they can be held
to the same 90% gate.
