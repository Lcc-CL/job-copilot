"""统一 LLM JSON 客户端；所有网络调用必须经过运行模式门禁。"""

from __future__ import annotations

import json
import re
import time
from typing import Callable, Optional, Union

from .llm_runtime import (
    LLMDryRun,
    LLMRuntimeError,
    build_dry_run_preview,
    emit_call_audit,
    get_runtime,
    require_live_configuration,
)

_client = None
_client_signature = None


def _get_client(api_key: str, base_url: str):
    global _client, _client_signature
    signature = (base_url, api_key)
    if _client is None or _client_signature != signature:
        from openai import OpenAI

        _client = OpenAI(api_key=api_key, base_url=base_url)
        _client_signature = signature
    return _client


def _extract_json(text: str) -> dict:
    if not text:
        raise ValueError("LLM returned empty content")
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            return json.loads(match.group(0))
        raise


def _fake_payload(
    fake_response: Optional[Union[dict, Callable[[], dict]]]
) -> dict:
    if fake_response is None:
        return {"result": "deterministic fake result"}
    value = fake_response() if callable(fake_response) else fake_response
    if not isinstance(value, dict):
        raise LLMRuntimeError(
            "Fake LLM response must be a JSON object",
            code="LLM_FAKE_RESPONSE_INVALID",
            status_code=500,
        )
    return dict(value)


def chat_json(
    system: str,
    user: str,
    model: Optional[str] = None,
    max_tokens: int = 2000,
    temperature: float = 0.2,
    *,
    operation: str = "generic",
    fake_response: Optional[Union[dict, Callable[[], dict]]] = None,
) -> dict:
    """按服务端 LLM_MODE 执行；请求参数不能覆盖运行模式。"""
    runtime = get_runtime(operation=operation, model=model)
    started = time.monotonic()
    if not system.strip() or not user.strip():
        emit_call_audit(
            runtime,
            success=False,
            duration_ms=int((time.monotonic() - started) * 1000),
            outcome=runtime.mode,
            error_code="LLM_REQUEST_INVALID",
        )
        raise LLMRuntimeError(
            "LLM request requires non-empty system and user messages",
            code="LLM_REQUEST_INVALID",
            status_code=422,
        )

    if runtime.mode == "dry-run":
        preview = build_dry_run_preview(
            runtime, max_tokens=max_tokens, temperature=temperature
        )
        emit_call_audit(
            runtime,
            success=True,
            duration_ms=int((time.monotonic() - started) * 1000),
            outcome="dry-run",
        )
        raise LLMDryRun(preview)

    if runtime.mode == "fake":
        try:
            result = _fake_payload(fake_response)
            result["_llm_source"] = "fake"
            result["_llm_mode"] = "fake"
            emit_call_audit(
                runtime,
                success=True,
                duration_ms=int((time.monotonic() - started) * 1000),
                outcome="fake",
            )
            return result
        except Exception as exc:
            code = getattr(exc, "code", "LLM_FAKE_FAILED")
            emit_call_audit(
                runtime,
                success=False,
                duration_ms=int((time.monotonic() - started) * 1000),
                outcome="fake",
                error_code=code,
            )
            raise

    try:
        require_live_configuration(runtime)
        response = _get_client(runtime.api_key, runtime.base_url).chat.completions.create(
            model=runtime.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            temperature=temperature,
        )
        result = _extract_json(response.choices[0].message.content)
        result["_llm_source"] = "live"
        result["_llm_mode"] = "live"
        emit_call_audit(
            runtime,
            success=True,
            duration_ms=int((time.monotonic() - started) * 1000),
            outcome="live",
        )
        return result
    except LLMRuntimeError as exc:
        emit_call_audit(
            runtime,
            success=False,
            duration_ms=int((time.monotonic() - started) * 1000),
            outcome="live",
            error_code=exc.code,
        )
        raise
    except Exception as exc:
        emit_call_audit(
            runtime,
            success=False,
            duration_ms=int((time.monotonic() - started) * 1000),
            outcome="live",
            error_code="LLM_PROVIDER_ERROR",
        )
        raise LLMRuntimeError(
            "LLM provider request failed",
            code="LLM_PROVIDER_ERROR",
            status_code=502,
        ) from exc
