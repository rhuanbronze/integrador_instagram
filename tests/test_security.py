import io
import logging
from urllib.parse import quote

import pytest

from app.config import Settings
from app.utils.logging import RedactingFormatter, redact
from app.utils.retry import retry_delay


def test_known_secrets_urls_headers_and_tracebacks_are_redacted():
    secret = "sensitive/token+test"
    raw = f"Authorization: Bearer {secret} URL ?access_token={quote(secret, safe='')}&after=x"
    assert secret not in redact(raw, (secret,))
    assert quote(secret, safe="") not in redact(raw, (secret,))
    assert "after=x" in redact(raw, (secret,))
    assert "arbitrary-secret" not in redact("?access_token=arbitrary-secret&fields=id")
    assert "unknown-key" not in redact("X-API-Key: unknown-key")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter((secret,)))
    logger = logging.getLogger("security-test")
    logger.addHandler(handler)
    try:
        try:
            raise ValueError(secret)
        except ValueError:
            logger.exception("failed token=%s", secret)
        assert secret not in stream.getvalue()
        assert "[REDACTED]" in stream.getvalue()
    finally:
        logger.removeHandler(handler)


def test_settings_repr_and_validation_hide_secrets(settings):
    assert "fake-token-never-real" not in repr(settings)
    data = settings.model_dump()
    data["request_timeout_seconds"] = "bad-secret-input"
    with pytest.raises(ValueError) as error:
        Settings(_env_file=None, **data)
    assert "bad-secret-input" not in str(error.value)


def test_retry_after_http_date_and_invalid_values():
    assert retry_delay(0, "not-a-date") == 2
    assert retry_delay(1, "0") == 4
    assert retry_delay(0, "Mon, 01 Jan 2040 00:00:00 GMT") > 2
