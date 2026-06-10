from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import time
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server as prometheus_start_http_server,
)


logger = logging.getLogger(__name__)

REGISTRY = CollectorRegistry()


def _now_seconds() -> float:
    return time.time()


def _monotonic_seconds() -> float:
    return time.perf_counter()


def parse_bool_env(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {raw!r}")


def log_event(
    event_logger: logging.Logger,
    level: int,
    event: str,
    **fields: Any,
) -> None:
    parts = [event]
    for key, value in fields.items():
        if value is None:
            continue
        try:
            encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            encoded = json.dumps(str(value), ensure_ascii=False)
        parts.append(f"{key}={encoded}")
    event_logger.log(level, " ".join(parts))


@dataclass(frozen=True)
class MetricsSettings:
    enabled: bool
    host: str
    port: int


def load_metrics_settings_from_env(env: dict[str, str] | None = None) -> MetricsSettings:
    source = {} if env is None else env
    enabled = parse_bool_env(source.get("METRICS_ENABLED"), default=True)
    host = source.get("METRICS_HOST", "0.0.0.0").strip() or "0.0.0.0"
    raw_port = source.get("METRICS_PORT", "9000").strip() or "9000"
    port = int(raw_port)
    if port <= 0:
        raise ValueError("METRICS_PORT must be positive")
    return MetricsSettings(enabled=enabled, host=host, port=port)


def measure_duration_seconds(started_at: float) -> float:
    return max(0.0, _monotonic_seconds() - started_at)


COMMAND_REQUESTS_TOTAL = Counter(
    "checkup_command_requests_total",
    "Total slash command outcomes.",
    ("command", "outcome"),
    registry=REGISTRY,
)
COMMAND_DURATION_SECONDS = Histogram(
    "checkup_command_duration_seconds",
    "Slash command handling latency.",
    ("command",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)
TEXT_MESSAGES_TOTAL = Counter(
    "checkup_text_messages_total",
    "Total text message routing outcomes.",
    ("route", "detected_type", "outcome"),
    registry=REGISTRY,
)
JOURNAL_SAVES_TOTAL = Counter(
    "checkup_journal_saves_total",
    "Journal save outcomes.",
    ("kind", "outcome"),
    registry=REGISTRY,
)
JOURNAL_SAVE_DURATION_SECONDS = Histogram(
    "checkup_journal_save_duration_seconds",
    "Journal save latency.",
    ("kind",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)
JOURNAL_OPERATIONS_TOTAL = Counter(
    "checkup_journal_operations_total",
    "Journal read/export operations.",
    ("operation", "outcome"),
    registry=REGISTRY,
)
JOURNAL_OPERATION_DURATION_SECONDS = Histogram(
    "checkup_journal_operation_duration_seconds",
    "Journal read/export operation latency.",
    ("operation",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)
JOURNAL_INVALID_FILES_TOTAL = Counter(
    "checkup_journal_invalid_files_total",
    "Invalid journal files encountered.",
    ("kind", "reason"),
    registry=REGISTRY,
)
REMINDER_JOBS_TOTAL = Counter(
    "checkup_reminder_jobs_total",
    "Reminder job outcomes.",
    ("kind", "outcome"),
    registry=REGISTRY,
)
REVIEW_REQUESTS_TOTAL = Counter(
    "checkup_review_requests_total",
    "Review command outcomes.",
    ("outcome",),
    registry=REGISTRY,
)
LLM_REQUESTS_TOTAL = Counter(
    "checkup_llm_requests_total",
    "LLM request outcomes.",
    ("provider", "model", "outcome"),
    registry=REGISTRY,
)
LLM_REQUEST_DURATION_SECONDS = Histogram(
    "checkup_llm_request_duration_seconds",
    "LLM request latency.",
    ("provider", "model"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)
REVIEW_INPUT_ESTIMATED_TOKENS = Histogram(
    "checkup_review_input_estimated_tokens",
    "Estimated review input token counts.",
    ("provider", "model"),
    buckets=(128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768),
    registry=REGISTRY,
)
ARCHIVE_BUILDS_TOTAL = Counter(
    "checkup_archive_builds_total",
    "Archive build outcomes.",
    ("outcome",),
    registry=REGISTRY,
)
ARCHIVE_SIZE_BYTES = Histogram(
    "checkup_archive_size_bytes",
    "Archive size distribution.",
    buckets=(1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864),
    registry=REGISTRY,
)
SERVICE_START_TIME_SECONDS = Gauge(
    "checkup_service_start_time_seconds",
    "Unix timestamp when the service started.",
    registry=REGISTRY,
)
REMINDERS_ENABLED = Gauge(
    "checkup_reminders_enabled",
    "Whether reminders are configured and scheduled.",
    registry=REGISTRY,
)

_metrics_server: Any | None = None
_metrics_server_thread: Any | None = None


def start_metrics_http_server(settings: MetricsSettings) -> None:
    global _metrics_server
    global _metrics_server_thread

    if not settings.enabled or _metrics_server is not None:
        return

    server, thread = prometheus_start_http_server(
        settings.port,
        addr=settings.host,
        registry=REGISTRY,
    )
    _metrics_server = server
    _metrics_server_thread = thread


def stop_metrics_http_server() -> None:
    global _metrics_server
    global _metrics_server_thread

    if _metrics_server is None:
        return

    _metrics_server.shutdown()
    _metrics_server.server_close()
    if _metrics_server_thread is not None:
        _metrics_server_thread.join(timeout=1)
    _metrics_server = None
    _metrics_server_thread = None


def render_metrics() -> str:
    return generate_latest(REGISTRY).decode("utf-8")


def metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST


def observe_command(command: str, outcome: str, duration_seconds: float) -> None:
    COMMAND_REQUESTS_TOTAL.labels(command=command, outcome=outcome).inc()
    COMMAND_DURATION_SECONDS.labels(command=command).observe(duration_seconds)


def observe_text_message(route: str, detected_type: str, outcome: str) -> None:
    TEXT_MESSAGES_TOTAL.labels(
        route=route,
        detected_type=detected_type,
        outcome=outcome,
    ).inc()


def observe_journal_save(kind: str, outcome: str, duration_seconds: float | None = None) -> None:
    JOURNAL_SAVES_TOTAL.labels(kind=kind, outcome=outcome).inc()
    if duration_seconds is not None:
        JOURNAL_SAVE_DURATION_SECONDS.labels(kind=kind).observe(duration_seconds)


def observe_journal_operation(operation: str, outcome: str, duration_seconds: float) -> None:
    JOURNAL_OPERATIONS_TOTAL.labels(operation=operation, outcome=outcome).inc()
    JOURNAL_OPERATION_DURATION_SECONDS.labels(operation=operation).observe(duration_seconds)


def observe_journal_invalid_file(kind: str, reason: str) -> None:
    JOURNAL_INVALID_FILES_TOTAL.labels(kind=kind, reason=reason).inc()


def observe_reminder_job(kind: str, outcome: str) -> None:
    REMINDER_JOBS_TOTAL.labels(kind=kind, outcome=outcome).inc()


def observe_review_request(outcome: str) -> None:
    REVIEW_REQUESTS_TOTAL.labels(outcome=outcome).inc()


def observe_llm_request(
    provider: str,
    model: str,
    outcome: str,
    duration_seconds: float | None = None,
) -> None:
    LLM_REQUESTS_TOTAL.labels(provider=provider, model=model, outcome=outcome).inc()
    if duration_seconds is not None:
        LLM_REQUEST_DURATION_SECONDS.labels(provider=provider, model=model).observe(
            duration_seconds
        )


def observe_review_input_estimated_tokens(provider: str, model: str, tokens: int) -> None:
    REVIEW_INPUT_ESTIMATED_TOKENS.labels(provider=provider, model=model).observe(tokens)


def observe_archive_build(outcome: str, archive_size_bytes: int | None = None) -> None:
    ARCHIVE_BUILDS_TOTAL.labels(outcome=outcome).inc()
    if archive_size_bytes is not None:
        ARCHIVE_SIZE_BYTES.observe(archive_size_bytes)


def set_service_start_time_seconds(value: float | None = None) -> None:
    SERVICE_START_TIME_SECONDS.set(_now_seconds() if value is None else value)


def set_reminders_enabled(enabled: bool) -> None:
    REMINDERS_ENABLED.set(1.0 if enabled else 0.0)


def get_counter_value(metric: Counter, **labels: str) -> float:
    return metric.labels(**labels)._value.get()


def get_gauge_value(metric: Gauge) -> float:
    return metric._value.get()


def get_histogram_count(metric: Histogram, **labels: str) -> float:
    for collected_metric in metric.collect():
        for sample in collected_metric.samples:
            if sample.name != f"{metric._name}_count":
                continue
            if sample.labels == labels:
                return float(sample.value)
    return 0.0


def reset_metrics_for_tests() -> None:
    collectors = [
        COMMAND_REQUESTS_TOTAL,
        COMMAND_DURATION_SECONDS,
        TEXT_MESSAGES_TOTAL,
        JOURNAL_SAVES_TOTAL,
        JOURNAL_SAVE_DURATION_SECONDS,
        JOURNAL_OPERATIONS_TOTAL,
        JOURNAL_OPERATION_DURATION_SECONDS,
        JOURNAL_INVALID_FILES_TOTAL,
        REMINDER_JOBS_TOTAL,
        REVIEW_REQUESTS_TOTAL,
        LLM_REQUESTS_TOTAL,
        LLM_REQUEST_DURATION_SECONDS,
        REVIEW_INPUT_ESTIMATED_TOKENS,
        ARCHIVE_BUILDS_TOTAL,
        ARCHIVE_SIZE_BYTES,
    ]
    for collector in collectors:
        if hasattr(collector, "_metrics"):
            collector._metrics.clear()
            continue
        if isinstance(collector, Histogram):
            collector._sum.set(0.0)
            for bucket in collector._buckets:
                bucket.set(0.0)
            continue
    SERVICE_START_TIME_SECONDS.set(0.0)
    REMINDERS_ENABLED.set(0.0)
