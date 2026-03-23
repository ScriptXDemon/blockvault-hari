from __future__ import annotations

import io
import json
import logging


def test_health_request_emits_structured_log_and_request_id(client):
    logger = logging.getLogger("blockvault.api")
    handler = logger.handlers[0]
    original_stream = handler.stream
    buffer = io.StringIO()
    handler.stream = buffer
    try:
        response = client.get("/health", headers={"x-request-id": "req-test-123"})
    finally:
        handler.stream = original_stream

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-test-123"

    payload = json.loads(buffer.getvalue().strip().splitlines()[-1])
    assert payload["event"] == "request.completed"
    assert payload["requestId"] == "req-test-123"
    assert payload["path"] == "/health"
    assert payload["statusCode"] == 200
