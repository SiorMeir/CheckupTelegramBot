from __future__ import annotations

import logging
import math
import os
import time as perf_clock
from dataclasses import dataclass

import httpx

from observability import (
    log_event,
    measure_duration_seconds,
    observe_llm_request,
    observe_review_input_estimated_tokens,
)

logger = logging.getLogger(__name__)

DEFAULT_REVIEW_MAX_INPUT_TOKENS = 8000
DEFAULT_LLM_TIMEOUT_SECONDS = 180

LLM_PROVIDERS = {"OPENAI", "LOCAL"}
class LLMConfigError(ValueError):
    pass


class LLMRequestTooLargeError(ValueError):
    pass


class LLMRequestError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    base_url: str
    api_key: str | None
    timeout_seconds: int
    max_input_tokens: int


@dataclass(frozen=True)
class LLMResult:
    provider: str
    model: str
    content: str


def _parse_positive_int(raw: str | None, env_name: str, default: int) -> int:
    if raw is None or not raw.strip():
        return default

    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise LLMConfigError(f"{env_name} must be an integer.") from exc

    if value <= 0:
        raise LLMConfigError(f"{env_name} must be positive.")

    return value


def _normalize_base_url(raw: str) -> str:
    url = raw.strip().rstrip("/")
    if not url:
        raise LLMConfigError("Base URL must not be empty.")
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    return url


def load_llm_config_from_env() -> LLMConfig:
    provider = os.environ.get("LLM_PROVIDER", "").strip().upper()
    if provider not in LLM_PROVIDERS:
        raise LLMConfigError(f"LLM_PROVIDER must be one of: {', '.join(LLM_PROVIDERS)}.")

    model = os.environ.get("LLM_MODEL", "").strip() # optional
    timeout_seconds = _parse_positive_int(
        os.environ.get("LLM_TIMEOUT_SECONDS"),
        "LLM_TIMEOUT_SECONDS",
        DEFAULT_LLM_TIMEOUT_SECONDS,
    )
    max_input_tokens = _parse_positive_int(
        os.environ.get("REVIEW_MAX_INPUT_TOKENS"),
        "REVIEW_MAX_INPUT_TOKENS",
        DEFAULT_REVIEW_MAX_INPUT_TOKENS,
    )

    if provider == "OPENAI":
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise LLMConfigError("OPENAI_API_KEY is required when LLM_PROVIDER=OPENAI.")
        base_url = "https://api.openai.com/v1"
    elif provider == "LOCAL":
        raw_base_url = os.environ.get("LOCAL_BASE_URL", "")
        if not raw_base_url.strip():
            raise LLMConfigError("LOCAL_BASE_URL is required when LLM_PROVIDER=LOCAL.")
        api_key = None
        base_url = _normalize_base_url(raw_base_url)

    return LLMConfig(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        max_input_tokens=max_input_tokens,
    )


def estimate_input_tokens(system_prompt: str, user_content: str) -> int: # each word is about 4 tokens
    total_characters = len(system_prompt) + len(user_content)
    return math.ceil(total_characters / 4)


def ensure_input_token_budget(
    config: LLMConfig,
    system_prompt: str,
    user_content: str,
) -> int:
    estimated_tokens = estimate_input_tokens(system_prompt, user_content)
    log_event(
        logger,
        logging.INFO,
        "llm_request_started",
        provider=config.provider,
        model=config.model,
        timeout_seconds=config.timeout_seconds,
        estimated_input_tokens=estimated_tokens,
    )
    observe_review_input_estimated_tokens(config.provider, config.model, estimated_tokens)
    if estimated_tokens > config.max_input_tokens:
        raise LLMRequestTooLargeError(
            f"Review request exceeds the input token cap ({estimated_tokens} > {config.max_input_tokens})."
        )
    return estimated_tokens


def _extract_message_content(data: dict) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMRequestError("LLM response did not include a chat completion message.") from exc

    if isinstance(content, str):
        text = content.strip()
        if text:
            return text
        raise LLMRequestError("LLM response message was empty.")

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        text = "\n".join(part.strip() for part in parts if part.strip()).strip()
        if text:
            return text

    raise LLMRequestError("LLM response format was not recognized.")


async def generate_review_text(
    config: LLMConfig,
    system_prompt: str,
    user_content: str,
) -> LLMResult:
    started_at = perf_clock.perf_counter()
    headers = {"Content-Type": "application/json"}
    if config.api_key is not None:
        headers["Authorization"] = f"Bearer {config.api_key}"

    payload = {
        "model": config.model,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    url = f"{config.base_url}/chat/completions"

    async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            duration_seconds = measure_duration_seconds(started_at)
            observe_llm_request(
                config.provider,
                config.model,
                "http_status",
                duration_seconds,
            )
            log_event(
                logger,
                logging.ERROR,
                "llm_request_failed",
                provider=config.provider,
                model=config.model,
                failure_type="http_status",
                status_code=exc.response.status_code,
            )
            body = exc.response.text.strip()
            raise LLMRequestError(
                f"LLM provider returned HTTP {exc.response.status_code}: {body or 'no response body'}"
            ) from exc
        except httpx.HTTPError as exc:
            duration_seconds = measure_duration_seconds(started_at)
            observe_llm_request(
                config.provider,
                config.model,
                "transport",
                duration_seconds,
            )
            log_event(
                logger,
                logging.ERROR,
                "llm_request_failed",
                provider=config.provider,
                model=config.model,
                failure_type="transport",
            )
            raise LLMRequestError(f"Failed to reach LLM provider: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        duration_seconds = measure_duration_seconds(started_at)
        observe_llm_request(
            config.provider,
            config.model,
            "invalid_json",
            duration_seconds,
        )
        log_event(
            logger,
            logging.ERROR,
            "llm_request_failed",
            provider=config.provider,
            model=config.model,
            failure_type="invalid_json",
        )
        raise LLMRequestError("LLM provider returned invalid JSON.") from exc

    try:
        content = _extract_message_content(data)
    except LLMRequestError:
        duration_seconds = measure_duration_seconds(started_at)
        observe_llm_request(
            config.provider,
            config.model,
            "invalid_response",
            duration_seconds,
        )
        log_event(
            logger,
            logging.ERROR,
            "llm_request_failed",
            provider=config.provider,
            model=config.model,
            failure_type="invalid_response",
        )
        raise

    duration_seconds = measure_duration_seconds(started_at)
    observe_llm_request(config.provider, config.model, "success", duration_seconds)
    log_event(
        logger,
        logging.INFO,
        "llm_request_complete",
        provider=config.provider,
        model=config.model,
        duration_ms=round(duration_seconds * 1000, 3),
    )
    return LLMResult(
        provider=config.provider,
        model=config.model,
        content=content,
    )
