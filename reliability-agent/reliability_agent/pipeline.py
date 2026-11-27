"""流水线编排：同步 -> 分析 -> Excel -> 飞书表格。"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from .analysis.base import AnalysisContext, AnalysisResult
from .analysis.loader import load_analyzer
from .config import AppConfig, ConfigError
from .demo import generate_demo_dataframe
from .export.excel import export_excel, prune_old_excel
from .feishu.bitable import BitableSource, normalize_record
from .feishu.client import FeishuClient, FeishuError
from .feishu.sheet import SheetWriter, build_sheet_matrix
from .storage.state import StateStore


@dataclass
class RunReport:
    run_id: str
    status: str
    table_key: str = ""
    rows_total: int = 0
    rows_changed: int = 0
    excel_path: str | None = None
    sheet_synced: bool = False
    message: str = ""


def build_client(config: AppConfig, logger: logging.Logger | None = None) -> FeishuClient:
    return FeishuClient(config.feishu, logger)


def resolve_plugin_spec(config: AppConfig) -> str:
    spec = config.analysis.plugin.strip()
    if ":" not in spec:
        return spec
    target, func_name = spec.rsplit(":", 1)
    if target.endswith(".py") and not Path(target).is_absolute():
        candidate = (config.base_dir / target).resolve()
        if candidate.is_file():
            return f"{candidate}:{func_name}"
    return spec


def sync_source(
    config: AppConfig,
    state: StateStore,
    logger: logging.Logger,
) -> tuple[pd.DataFrame, int, int, str]:
    """增量同步多维表格到本地镜像，返回 (全量数据, 总记录数, 本次变更数, table_key)。"""
    config.require_feishu(check_sheet=False)
    client = build_client(config, logger)
    source = BitableSource(client, config.source)
    table_key = source.table_key
    incremental = config.source.incremental

    previous = state.get_sync_state(table_key)
    run_index = int(previous["run_count"]) + 1 if previous else 1
    full_refresh = incremental.mode == "hash" or run_index == 1
    if not full_refresh and incremental.full_refresh_every > 0:
        full_refresh = run_index % incremental.full_refresh_every == 1

    since_ms: int | None = None
    if (
        not full_refresh
        and incremental.mode == "field"
        and incremental.updated_field
        and previous
        and previous.get("last_success_ms")
    ):
        since_ms = int(previous["last_success_ms"]) - incremental.overlap_seconds * 1000

    def _read(since: int | None) -> list[dict]:
        return [
            normalize_record(raw, updated_field=incremental.updated_field)
            for raw in source.iter_records(
                since_ms=since, updated_field=incremental.updated_field
            )
        ]

    logger.info(
        "开始同步: %s（%s，第 %s 次）",
        table_key,
        "全量" if full_refresh else "增量",
        run_index,
    )
    try:
        items = _read(since_ms)
    except FeishuError as exc:
        if since_ms is None:
            raise
        logger.warning("增量过滤读取失败（%s），回退为全量读取", exc)
        items = _read(None)
        full_refresh = True

    diff = state.upsert_records(table_key, items)
    deleted = state.delete_missing(table_key, {item["record_id"] for item in items}) if full_refresh else 0
    total = state.count_records(table_key)
    state.mark_sync(table_key, total_records=total, last_success_ms=int(time.time() * 1000))

    df = state.load_dataframe(table_key)
    if config.source.column_map:
        mapping = {k: v for k, v in config.source.column_map.items() if k in df.columns}
        if mapping:
            df = df.rename(columns=mapping)

    _dump_snapshot(config, df, table_key, logger)
    logger.info(
        "同步完成: 源表 %s 条，本地 %s 条，本次变更 %s 条，删除 %s 条",
        len(items),
        total,
        diff.changed,
        deleted,
    )
    return df, total, diff.changed + deleted, table_key


def _dump_snapshot(config: AppConfig, df: pd.DataFrame, table_key: str, logger: logging.Logger) -> None:
    if not config.storage.mirror_dir:
        return
    try:
        directory = Path(config.storage.mirror_dir)
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = table_key.replace("/", "_").replace(":", "_").replace("\\", "_")
        df.to_csv(directory / f"{safe_name}.csv", index=False, encoding="utf-8-sig")
    except OSError as exc:
        logger.warning("写入本地数据快照失败: %s", exc)


def execute(
    config: AppConfig,
    *,
    demo: bool = False,
    skip_sync: bool = False,
    skip_sheet: bool = False,
    logger: logging.Logger | None = None,
) -> RunReport:
    logger = logger or logging.getLogger("reliability_agent")
    started = datetime.now()
    run_id = started.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(2)
    state = StateStore(Path(config.storage.db_path))
    report = RunReport(run_id=run_id, status="running")
    state.start_run(run_id=run_id, mode="demo" if demo else "feishu", started_at=started.isoformat(timespec="seconds"))

    table_key = "demo" if demo else f"{config.source.app_token}/{config.source.table_id}"
    report.table_key = table_key
    try:
        if demo:
            df = generate_demo_dataframe()
            if df.empty:
                raise RuntimeError("Demo 数据生成失败")
            rows_total = len(df)
            rows_changed = len(df)
            logger.info("Demo 模式：生成模拟数据 %s 条", rows_total)
        else:
            config.require_feishu(check_sheet=not skip_sheet)
            if skip_sync:
                table_key = f"{config.source.app_token}/{config.source.table_id}"
                df = state.load_dataframe(table_key)
                if df.empty:
                    raise RuntimeError("本地镜像为空，无法跳过同步；请先执行 sync-only 或去掉 --skip-sync")
                rows_total = len(df)
                rows_changed = 0
                logger.info("跳过同步，使用本地镜像数据 %s 条", rows_total)
                if config.source.column_map:
                    mapping = {k: v for k, v in config.source.column_map.items() if k in df.columns}
                    df = df.rename(columns=mapping)
            else:
                df, rows_total, rows_changed, table_key = sync_source(config, state, logger)

        report.table_key = table_key
        report.rows_total = rows_total
        report.rows_changed = rows_changed

        plugin_spec = resolve_plugin_spec(config)
        analyzer = load_analyzer(plugin_spec)
        logger.info("执行分析插件: %s", plugin_spec)
        analysis_started = time.perf_counter()
        ctx = AnalysisContext(
            run_id=run_id,
            options=dict(config.analysis.options),
            output_dir=Path(config.output.excel.dir),
        )
        result = analyzer(df, ctx)
        if not isinstance(result, AnalysisResult):
            raise TypeError("分析插件必须返回 AnalysisResult 对象")
        elapsed = time.perf_counter() - analysis_started
        logger.info("分析完成，耗时 %.2fs，输出 %s 行结果", elapsed, len(result.summary))

        excel_cfg = config.output.excel
        try:
            filename = excel_cfg.filename_template.format(run_id=run_id)
        except (KeyError, IndexError, ValueError) as exc:
            raise ConfigError(f"output.excel.filename_template 无效: {exc}") from exc
        excel_path = Path(excel_cfg.dir) / filename

        overview: dict[str, object] = {
            "运行 ID": run_id,
            "运行时间": started.strftime("%Y-%m-%d %H:%M:%S"),
            "数据源": table_key,
            "总记录数": rows_total,
            "本次变更记录数": rows_changed,
            "分析插件": plugin_spec,
            "分析耗时(秒)": round(elapsed, 2),
        }
        overview.update(result.metrics or {})

        export_excel(
            excel_path,
            dataframe=df,
            result=result,
            overview=overview,
            date_fields=config.source.date_fields,
            max_preview_rows=excel_cfg.max_preview_rows,
            runs_df=state.recent_runs(20),
        )
        report.excel_path = str(excel_path)
        logger.info("Excel 已生成: %s", excel_path)

        sheet_synced = False
        sheet_cfg = config.output.feishu_sheet
        if demo and not skip_sheet:
            logger.warning("Demo 模式不回写飞书表格，已自动跳过")
            skip_sheet = True
        if not skip_sheet and sheet_cfg.enabled:
            client = build_client(config, logger)
            writer = SheetWriter(client, sheet_cfg.spreadsheet_token)
            meta = {
                "运行 ID": run_id,
                "运行时间": started.strftime("%Y-%m-%d %H:%M:%S"),
                "数据源": table_key,
                "总记录数": rows_total,
                "本次变更记录数": rows_changed,
                "分析插件": plugin_spec,
            }
            matrix = build_sheet_matrix(result, meta)
            writer.push_matrix(
                sheet_cfg.sheet_name,
                matrix,
                clear_before_write=sheet_cfg.clear_before_write,
                chunk_rows=sheet_cfg.chunk_rows,
            )
            sheet_synced = True
            logger.info("飞书电子表格回写完成: %s", sheet_cfg.spreadsheet_token)

        prefix = excel_cfg.filename_template.split("{")[0]
        removed = prune_old_excel(Path(excel_cfg.dir), prefix=prefix, keep_days=excel_cfg.keep_days)
        if removed:
            logger.info("清理超过 %s 天的历史 Excel %s 个", excel_cfg.keep_days, removed)

        report.status = "success"
        report.sheet_synced = sheet_synced
        state.finish_run(
            run_id,
            status="success",
            finished_at=datetime.now().isoformat(timespec="seconds"),
            table_key=table_key,
            rows_total=rows_total,
            rows_changed=rows_changed,
            excel_path=str(excel_path),
            sheet_synced=sheet_synced,
        )
        return report

    except Exception as exc:
        logger.exception("流水线执行失败: %s", exc)
        report.status = "failed"
        report.message = str(exc)
        state.finish_run(
            run_id,
            status="failed",
            finished_at=datetime.now().isoformat(timespec="seconds"),
            table_key=table_key,
            rows_total=report.rows_total,
            rows_changed=report.rows_changed,
            excel_path=report.excel_path,
            message=str(exc),
        )
        raise
    finally:
        state.close()
