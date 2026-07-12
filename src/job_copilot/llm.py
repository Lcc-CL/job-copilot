"""DeepSeek LLM 客户端封装。

要点：
- OpenAI 兼容接口，base_url=api.deepseek.com（走本机代理可达，已验证）。
- model_analysis=deepseek-v4-pro 是推理模型：会输出 reasoning_content（思维链），
  最终答案在 message.content——**必须给足 max_tokens**，否则 content 为空。
- chat_json 强制 JSON 输出并容错解析（去 markdown 围栏、截取花括号）。
"""

from __future__ import annotations

import json
import re
from typing import Optional

from .config import load_config

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        cfg = load_config()
        _client = OpenAI(api_key=cfg.llm["api_key"], base_url=cfg.llm["base_url"])
    return _client


def _extract_json(text: str) -> dict:
    if not text:
        raise ValueError("LLM 返回空 content")
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def chat_json(system: str, user: str, model: Optional[str] = None,
              max_tokens: int = 2000, temperature: float = 0.2) -> dict:
    """调用 DeepSeek，返回解析后的 JSON dict。"""
    cfg = load_config()
    model = model or cfg.llm["model_analysis"]
    resp = _get_client().chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return _extract_json(resp.choices[0].message.content)
