"""LLM 运行模式、付费调用门禁与安全审计元数据。"""

from __future__ import annotations

import datetime
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from .config import load_config


VALID_LLM_MODES = {"fake", "dry-run", "live"}
MODE_LABELS = {
    "fake": "测试模式",
    "dry-run": "预演模式",
    "live": "真实调用",
}
OPERATION_MODEL_KEYS = {
    "score": "model_analysis",
    "enrich": "model_analysis",
    "resume_tailor": "model_drafting",
    "greet": "model_drafting",
}
OPERATION_LABELS = {
    "score": "职位匹配评分",
    "enrich": "完整 JD 二次分析",
    "resume_tailor": "定制简历生成",
    "greet": "招呼语生成",
}

_audit_logger = logging.getLogger("job_copilot.llm.audit")


class LLMRuntimeError(RuntimeError):
    """运行模式或真实调用失败，且可安全映射为 HTTP 错误。"""

    def __init__(self, detail: str, *, code: str, status_code: int = 503):
        super().__init__(detail)
        self.detail = detail
        self.code = code
        self.status_code = status_code


class LLMDryRun(LLMRuntimeError):
    """预演已完成；不应将其当作正式 AI 结果持久化。"""

    def __init__(self, preview: dict):
        super().__init__(
            "未调用模型，未生成正式结果",
            code="LLM_DRY_RUN",
            status_code=200,
        )
        self.preview = preview


@dataclass(frozen=True)
class LLMRuntime:
    mode: str
    provider: str
    model: str
    operation: str
    api_key: str
    base_url: str

    @property
    def label(self) -> str:
        return MODE_LABELS[self.mode]

    @property
    def live_ready(self) -> bool:
        return bool(self.api_key and self.base_url)

    @property
    def network_enabled(self) -> bool:
        return self.mode == "live" and self.live_ready

    def public_dict(self) -> dict:
        return {
            "mode": self.mode,
            "label": self.label,
            "provider": self.provider,
            "model": self.model,
            "operation": self.operation,
            "operation_label": OPERATION_LABELS.get(
                self.operation, self.operation
            ),
            "live_ready": self.live_ready,
            "network_enabled": self.network_enabled,
        }


def resolve_mode() -> str:
    raw = os.getenv("LLM_MODE", "").strip().lower()
    if not raw:
        return "dry-run"
    if raw not in VALID_LLM_MODES:
        raise LLMRuntimeError(
            "LLM_MODE must be one of fake, dry-run, or live",
            code="LLM_MODE_INVALID",
        )
    return raw


def _llm_config() -> dict:
    try:
        return load_config().llm
    except FileNotFoundError:
        return {}


def get_runtime(
    operation: str = "generic", model: Optional[str] = None
) -> LLMRuntime:
    cfg = _llm_config()
    model_key = OPERATION_MODEL_KEYS.get(operation, "model_analysis")
    return LLMRuntime(
        mode=resolve_mode(),
        provider=str(cfg.get("provider") or "unconfigured"),
        model=str(model or cfg.get(model_key) or "unconfigured"),
        operation=operation,
        api_key=str(cfg.get("api_key") or "").strip(),
        base_url=str(cfg.get("base_url") or "").strip(),
    )


def runtime_overview() -> dict:
    cfg = _llm_config()
    mode = resolve_mode()
    provider = str(cfg.get("provider") or "unconfigured")
    operations = {
        operation: {
            "label": OPERATION_LABELS[operation],
            "model": str(cfg.get(model_key) or "unconfigured"),
        }
        for operation, model_key in OPERATION_MODEL_KEYS.items()
    }
    api_key = str(cfg.get("api_key") or "").strip()
    base_url = str(cfg.get("base_url") or "").strip()
    return {
        "mode": mode,
        "label": MODE_LABELS[mode],
        "provider": provider,
        "model": operations["resume_tailor"]["model"],
        "operations": operations,
        "live_ready": bool(api_key and base_url),
        "network_enabled": mode == "live" and bool(api_key and base_url),
        "message": (
            "未调用模型，未生成正式结果"
            if mode == "dry-run"
            else "确定性测试结果，不会发出网络请求"
            if mode == "fake"
            else "真实调用会向外部 LLM provider 发出 API 请求"
        ),
    }


def require_live_configuration(runtime: LLMRuntime) -> None:
    if not runtime.api_key:
        raise LLMRuntimeError(
            "LLM live mode requires an API Key",
            code="LLM_API_KEY_MISSING",
        )
    if not runtime.base_url:
        raise LLMRuntimeError(
            "LLM live mode requires a Base URL",
            code="LLM_BASE_URL_MISSING",
        )


def build_dry_run_preview(
    runtime: LLMRuntime,
    *,
    max_tokens: int,
    temperature: float,
) -> dict:
    validation_errors = []
    if runtime.provider == "unconfigured":
        validation_errors.append("provider is not configured")
    if runtime.model == "unconfigured":
        validation_errors.append("model is not configured")
    return {
        "status": "dry-run",
        "created": False,
        "message": "未调用模型，未生成正式结果",
        "runtime": runtime.public_dict(),
        "request": {
            "message_count": 2,
            "response_format": "json_object",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "validated": not validation_errors,
            "validation_errors": validation_errors,
            "network_request_sent": False,
        },
    }


def emit_call_audit(
    runtime: LLMRuntime,
    *,
    success: bool,
    duration_ms: int,
    outcome: str,
    error_code: Optional[str] = None,
) -> None:
    """只记录非敏感元数据；不记录 Key、Authorization、Prompt 或简历。"""
    payload = {
        "mode": runtime.mode,
        "provider": runtime.provider,
        "model": runtime.model,
        "operation": runtime.operation,
        "status": "success" if success else "failure",
        "outcome": outcome,
        "duration_ms": duration_ms,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if error_code:
        payload["error_code"] = error_code
    _audit_logger.info("llm_call_audit %s", json.dumps(payload, ensure_ascii=False))


def persisted_model_name(model: str, source: str) -> str:
    return f"{source}:{model}"


def split_persisted_model(value: Optional[str]) -> tuple[str, Optional[str]]:
    raw = (value or "").strip()
    for source in ("fake", "live"):
        prefix = f"{source}:"
        if raw.startswith(prefix):
            return source, raw[len(prefix):] or None
    return "legacy", raw or None
