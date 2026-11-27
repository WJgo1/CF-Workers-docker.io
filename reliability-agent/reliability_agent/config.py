"""配置加载：config.yaml + .env，相对路径按配置文件所在目录解析。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """配置缺失或格式错误。"""


def _load_dotenv(path: Path) -> None:
    """极简 .env 解析，避免额外依赖；已存在的环境变量优先。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"配置项 {key} 必须是字典")
    return value


def _resolve(base_dir: Path, value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return str(path.resolve())


@dataclass
class FeishuConfig:
    base_url: str = "https://open.feishu.cn"
    app_id: str = ""
    app_secret: str = ""
    timeout_seconds: int = 30
    max_retries: int = 3
    retry_backoff_seconds: float = 2.0


@dataclass
class IncrementalConfig:
    mode: str = "hash"  # hash | field
    updated_field: str = ""
    full_refresh_every: int = 7
    overlap_seconds: int = 3600


@dataclass
class SourceConfig:
    type: str = "bitable"
    app_token: str = ""
    table_id: str = ""
    view_id: str | None = None
    page_size: int = 500
    date_fields: list[str] = field(default_factory=list)
    column_map: dict[str, str] = field(default_factory=dict)
    incremental: IncrementalConfig = field(default_factory=IncrementalConfig)


@dataclass
class AnalysisConfig:
    plugin: str = "reliability_agent.analysis.plugins.weibull_example:analyze"
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExcelOutputConfig:
    dir: str = "./output"
    filename_template: str = "reliability_{run_id}.xlsx"
    keep_days: int = 90
    max_preview_rows: int = 20000


@dataclass
class SheetOutputConfig:
    enabled: bool = False
    spreadsheet_token: str = ""
    sheet_name: str = "可靠性分析结果"
    clear_before_write: bool = True
    chunk_rows: int = 500


@dataclass
class OutputConfig:
    excel: ExcelOutputConfig = field(default_factory=ExcelOutputConfig)
    feishu_sheet: SheetOutputConfig = field(default_factory=SheetOutputConfig)


@dataclass
class ScheduleConfig:
    enabled: bool = True
    cron: str = "0 8 * * *"
    run_on_start: bool = False


@dataclass
class StorageConfig:
    db_path: str = "./data/state.db"
    mirror_dir: str = "./data/mirror"


@dataclass
class AppConfig:
    config_path: Path
    base_dir: Path
    timezone: str = "Asia/Shanghai"
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    source: SourceConfig = field(default_factory=SourceConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)

    def require_feishu(self, *, check_sheet: bool = True) -> None:
        missing: list[str] = []
        if not self.feishu.app_id:
            missing.append("FEISHU_APP_ID（或 feishu.app_id）")
        if not self.feishu.app_secret:
            missing.append("FEISHU_APP_SECRET（或 feishu.app_secret）")
        if not self.source.app_token:
            missing.append("source.app_token")
        if not self.source.table_id:
            missing.append("source.table_id")
        if (
            check_sheet
            and self.output.feishu_sheet.enabled
            and not self.output.feishu_sheet.spreadsheet_token
        ):
            missing.append("output.feishu_sheet.spreadsheet_token")
        if missing:
            raise ConfigError("缺少必填配置: " + "、".join(missing))


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ConfigError(f"找不到配置文件: {config_path}")
    base_dir = config_path.parent

    _load_dotenv(base_dir / ".env")
    _load_dotenv(Path.cwd() / ".env")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError("配置文件根节点必须是字典")

    app_raw = _section(raw, "app")
    feishu_raw = _section(raw, "feishu")
    req_raw = _section(feishu_raw, "request")
    feishu = FeishuConfig(
        base_url=str(feishu_raw.get("base_url", "https://open.feishu.cn")).rstrip("/"),
        app_id=str(os.environ.get("FEISHU_APP_ID") or feishu_raw.get("app_id") or ""),
        app_secret=str(os.environ.get("FEISHU_APP_SECRET") or feishu_raw.get("app_secret") or ""),
        timeout_seconds=int(req_raw.get("timeout_seconds", 30)),
        max_retries=int(req_raw.get("max_retries", 3)),
        retry_backoff_seconds=float(req_raw.get("retry_backoff_seconds", 2.0)),
    )

    src_raw = _section(raw, "source")
    inc_raw = _section(src_raw, "incremental")
    mode = str(inc_raw.get("mode", "hash")).lower()
    if mode not in {"hash", "field"}:
        raise ConfigError("source.incremental.mode 只能是 hash 或 field")
    if mode == "field" and not inc_raw.get("updated_field"):
        raise ConfigError("source.incremental.mode=field 时必须配置 updated_field")
    source = SourceConfig(
        type=str(src_raw.get("type", "bitable")),
        app_token=str(src_raw.get("app_token") or ""),
        table_id=str(src_raw.get("table_id") or ""),
        view_id=str(src_raw["view_id"]) if src_raw.get("view_id") else None,
        page_size=int(src_raw.get("page_size", 500)),
        date_fields=[str(item) for item in (src_raw.get("date_fields") or [])],
        column_map={str(k): str(v) for k, v in (src_raw.get("column_map") or {}).items()},
        incremental=IncrementalConfig(
            mode=mode,
            updated_field=str(inc_raw.get("updated_field") or ""),
            full_refresh_every=int(inc_raw.get("full_refresh_every", 7)),
            overlap_seconds=int(inc_raw.get("overlap_seconds", 3600)),
        ),
    )

    ana_raw = _section(raw, "analysis")
    analysis = AnalysisConfig(
        plugin=str(ana_raw.get("plugin") or AnalysisConfig.plugin),
        options=dict(ana_raw.get("options") or {}),
    )

    out_raw = _section(raw, "output")
    excel_raw = _section(out_raw, "excel")
    sheet_raw = _section(out_raw, "feishu_sheet")
    output = OutputConfig(
        excel=ExcelOutputConfig(
            dir=_resolve(base_dir, str(excel_raw.get("dir", "./output"))),
            filename_template=str(excel_raw.get("filename_template", "reliability_{run_id}.xlsx")),
            keep_days=int(excel_raw.get("keep_days", 90)),
            max_preview_rows=int(excel_raw.get("max_preview_rows", 20000)),
        ),
        feishu_sheet=SheetOutputConfig(
            enabled=bool(sheet_raw.get("enabled", False)),
            spreadsheet_token=str(sheet_raw.get("spreadsheet_token") or ""),
            sheet_name=str(sheet_raw.get("sheet_name", "可靠性分析结果")),
            clear_before_write=bool(sheet_raw.get("clear_before_write", True)),
            chunk_rows=int(sheet_raw.get("chunk_rows", 500)),
        ),
    )

    sched_raw = _section(raw, "schedule")
    schedule = ScheduleConfig(
        enabled=bool(sched_raw.get("enabled", True)),
        cron=str(sched_raw.get("cron", "0 8 * * *")),
        run_on_start=bool(sched_raw.get("run_on_start", False)),
    )

    st_raw = _section(raw, "storage")
    storage = StorageConfig(
        db_path=_resolve(base_dir, str(st_raw.get("db_path", "./data/state.db"))),
        mirror_dir=_resolve(base_dir, str(st_raw.get("mirror_dir", "./data/mirror"))),
    )

    return AppConfig(
        config_path=config_path,
        base_dir=base_dir,
        timezone=str(app_raw.get("timezone", "Asia/Shanghai")),
        feishu=feishu,
        source=source,
        analysis=analysis,
        output=output,
        schedule=schedule,
        storage=storage,
    )
