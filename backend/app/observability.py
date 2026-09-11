"""Phase 6: structured logging for the deployed environment.

Cloud Run/Cloud Logging's own convention (no extra dependency needed): a
log line written to stdout as a single JSON object is automatically parsed
into Cloud Logging's structured `jsonPayload`, with `severity` promoted to
the entry's real severity - see
https://cloud.google.com/run/docs/logging#writing_structured_logs. This
formatter implements exactly that convention, and nothing more.

Call sites attach correlation IDs via the standard `extra={...}` kwarg
(e.g. `logger.info("...", extra={"evaluation_run_reference_id": str(id)})`)
- every field ends up as its own filterable key in Cloud Logging, so "find
every log line for this PromotionRequest" or "every line for this Cloud
Task" is a real, working query, not something reconstructed from free text.
"""
import json
import logging
import sys

_RESERVED = frozenset(logging.LogRecord(*([None] * 4 + [None, None, None, None])).__dict__.keys()) | {"message", "asctime"}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in entry:
                try:
                    json.dumps(value)
                except TypeError:
                    value = str(value)
                entry[key] = value
        return json.dumps(entry, default=str)


def configure_logging(structured: bool) -> None:
    """`structured=True` in the deployed environment (real Cloud Logging
    JSON parsing); `structured=False` locally (plain, human-readable lines -
    a JSON blob per line is genuinely worse for `uvicorn --reload` dev
    output than the default formatter)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if structured else logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
