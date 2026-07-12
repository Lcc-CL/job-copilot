"""读取 config/config.toml 并提供全局配置对象。"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.toml"
DATA_DIR = PROJECT_ROOT / "data"
RESUME_DIR = PROJECT_ROOT / "resume"
REPORTS_DIR = PROJECT_ROOT / "reports"


@dataclass
class Config:
    llm: dict = field(default_factory=dict)
    me: dict = field(default_factory=dict)
    collect: dict = field(default_factory=dict)
    apply: dict = field(default_factory=dict)
    experiment: dict = field(default_factory=dict)


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        raise FileNotFoundError(
            f"未找到 {path}。请先: cp config/config.example.toml config/config.toml 并填写。"
        )
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return Config(
        llm=raw.get("llm", {}),
        me=raw.get("me", {}),
        collect=raw.get("collect", {}),
        apply=raw.get("apply", {}),
        experiment=raw.get("experiment", {}),
    )
