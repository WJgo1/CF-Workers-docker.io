"""命令行入口。

用法：
    python -m reliability_agent --config config.yaml run-once
    python -m reliability_agent --config config.yaml run-once --demo
    python -m reliability_agent --config config.yaml schedule
    python -m reliability_agent --config config.yaml sync-only
    python -m reliability_agent --config config.yaml test-connection
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import AppConfig, ConfigError, load_config
from .logging_setup import setup_logging
from .pipeline import build_client, execute, sync_source
from .storage.state import StateStore


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def _cmd_test_connection(config: AppConfig, logger: logging.Logger) -> int:
    config.require_feishu()
    client = build_client(config, logger)
    client.ping()
    print("飞书鉴权成功（tenant_access_token 已获取）")

    from .feishu.bitable import BitableSource
    from .feishu.sheet import SheetWriter

    source = BitableSource(client, config.source)
    fields = source.list_fields()
    print(f"多维表格字段（{len(fields)} 个）: {', '.join(fields)}")

    if config.output.feishu_sheet.enabled:
        writer = SheetWriter(client, config.output.feishu_sheet.spreadsheet_token)
        sheets = writer.list_sheets()
        titles = ", ".join(str(sheet.get("title", "")) for sheet in sheets)
        print(f"电子表格已有 sheet: {titles}")
    return 0


def _cmd_sync_only(config: AppConfig, logger: logging.Logger) -> int:
    config.require_feishu(check_sheet=False)
    state = StateStore(config.storage.db_path)
    try:
        _, total, changed, table_key = sync_source(config, state, logger)
    finally:
        state.close()
    print(f"同步完成: {table_key}，本地记录 {total} 条，本次变更 {changed} 条")
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(
        prog="reliability-agent",
        description="飞书多维表格 -> 可靠性预计 -> Excel/飞书表格 自动化工具",
    )
    parser.add_argument(
        "command",
        choices=["run-once", "schedule", "sync-only", "test-connection"],
        help="run-once=执行一次；schedule=常驻定时；sync-only=只同步；test-connection=连通性自检",
    )
    parser.add_argument("--config", default="config.yaml", help="配置文件路径，默认 config.yaml")
    parser.add_argument("--demo", action="store_true", help="使用内置模拟数据（仅 run-once）")
    parser.add_argument("--skip-sync", action="store_true", help="使用本地镜像数据，不访问飞书")
    parser.add_argument("--skip-sheet", action="store_true", help="不写回飞书电子表格")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出 DEBUG 日志")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    logger = setup_logging(config, verbose=args.verbose)

    try:
        if args.command == "test-connection":
            return _cmd_test_connection(config, logger)
        if args.command == "sync-only":
            return _cmd_sync_only(config, logger)
        if args.command == "schedule":
            from .scheduler import run_scheduler

            config.require_feishu(check_sheet=config.output.feishu_sheet.enabled)
            run_scheduler(config, logger)
            return 0

        if args.demo and (args.skip_sync or args.skip_sheet):
            logger.warning("Demo 模式已忽略 --skip-sync/--skip-sheet")
        report = execute(
            config,
            demo=args.demo,
            skip_sync=args.skip_sync,
            skip_sheet=args.skip_sheet,
            logger=logger,
        )
        print(f"运行完成: {report.run_id}")
        print(f"  状态: {report.status}")
        print(f"  数据源: {report.table_key}")
        print(f"  记录数: {report.rows_total}（本次变更 {report.rows_changed}）")
        print(f"  Excel: {report.excel_path}")
        print(f"  飞书表格同步: {'是' if report.sheet_synced else '否'}")
        return 0
    except ConfigError as exc:
        logger.error("配置错误: %s", exc)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI 统一兜底
        logger.error("执行失败: %s", exc)
        return 1
