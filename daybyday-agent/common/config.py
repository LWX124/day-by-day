"""应用配置加载。

数据目录：~/Library/Application Support/DayByDay/
配置文件：config.toml（见 design.md §6.5 Provider 配置）。

本模块只读配置与路径，不做业务逻辑。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# macOS 应用数据目录
APP_SUPPORT = Path.home() / "Library" / "Application Support" / "DayByDay"
DATA_DIR = APP_SUPPORT
DB_PATH = DATA_DIR / "db.sqlite3"
LOG_DIR = DATA_DIR / "logs"
CONFIG_PATH = DATA_DIR / "config.toml"


@dataclass
class ProviderConfig:
    kind: str
    base_url: str
    model: str
    api_key_env: str


@dataclass
class LLMConfig:
    default: str | None = None
    fallback: list[str] = field(default_factory=list)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    routing: dict[str, str] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        """是否有任一 provider 配置了**已就绪**的 key（env 实际有值）。

        无则触发降级模式（ADR-0003）。只看 api_key_env 字段非空还不够——
        "清空所有 key"验收要求 env 没值时返回 False。
        """
        return any(
            p.api_key_env and os.environ.get(p.api_key_env)
            for p in self.providers.values()
        )


@dataclass
class Config:
    data_dir: Path = DATA_DIR
    db_path: Path = DB_PATH
    log_dir: Path = LOG_DIR
    llm: LLMConfig = field(default_factory=LLMConfig)


def load_config(path: Path | None = None) -> Config:
    """从 config.toml 加载。文件不存在返回默认配置（降级模式）。"""
    cfg = Config()
    p = path or CONFIG_PATH
    if not p.exists():
        return cfg
    with p.open("rb") as f:
        raw = tomllib.load(f)
    llm_raw = raw.get("llm", {})
    cfg.llm.default = llm_raw.get("default")
    cfg.llm.fallback = list(llm_raw.get("fallback", []))
    for name, prov in llm_raw.get("providers", {}).items():
        cfg.llm.providers[name] = ProviderConfig(
            kind=prov["kind"],
            base_url=prov["base_url"],
            model=prov["model"],
            api_key_env=prov["api_key_env"],
        )
    cfg.llm.routing = dict(llm_raw.get("routing", {}))
    return cfg


def ensure_dirs() -> None:
    """确保数据/日志目录存在。后端启动时调用。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
