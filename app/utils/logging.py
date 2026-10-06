"""Redact both known secret values and sensitive query/header parameters."""

import logging
import re
from urllib.parse import quote, quote_plus

SENSITIVE = (
    r"access_token|appsecret_proof|app_secret|client_secret|mysql_password|admin_api_key|x-api-key"
)


def redact(value: object, secrets: tuple[str, ...] = ()) -> str:
    result = str(value)
    for secret in sorted(filter(None, secrets), key=len, reverse=True):
        for variant in {secret, quote(secret, safe=""), quote_plus(secret)}:
            result = result.replace(variant, "[REDACTED]")
    result = re.sub(
        rf"(?i)((?:{SENSITIVE})[\"']?\s*[=:]\s*[\"']?)[^&\s\"',}}]+",
        r"\1[REDACTED]",
        result,
    )
    return re.sub(r"(?i)(bearer\s+)[^\s\"']+", r"\1[REDACTED]", result)


class RedactingFormatter(logging.Formatter):
    def __init__(self, secrets: tuple[str, ...]):
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")
        self.secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record), self.secrets)


def configure_logging(level: str, secrets: tuple[str, ...]) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter(secrets))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # URLs from third-party libraries must pass through the same formatter.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    # Do not log incoming URL query strings, including accidental credential input.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("httpx", "httpcore", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(logging.WARNING)
