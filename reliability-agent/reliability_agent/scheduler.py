"""常驻调度：APScheduler cron 定时执行流水线。"""

from __future__ import annotations

import logging

from .config import AppConfig
from .pipeline import execute


def run_scheduler(config: AppConfig, logger: logging.Logger | None = None) -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    logger = logger or logging.getLogger("reliability_agent")
    if not config.schedule.enabled:
        logger.warning("schedule.enabled=false，但仍按命令启动常驻调度")
    try:
        trigger = CronTrigger.from_crontab(config.schedule.cron, timezone=config.timezone)
    except ValueError as exc:
        raise ValueError(f"schedule.cron 无效（应为 5 段 cron）: {config.schedule.cron}") from exc

    scheduler = BlockingScheduler(timezone=config.timezone)

    def job() -> None:
        logger.info("========== 定时任务开始 ==========")
        try:
            report = execute(config, logger=logger)
            logger.info(
                "定时任务完成: run_id=%s, 记录=%s, 变更=%s, Excel=%s, 飞书表格=%s",
                report.run_id,
                report.rows_total,
                report.rows_changed,
                report.excel_path,
                "是" if report.sheet_synced else "否",
            )
        except Exception:
            logger.exception("定时任务失败")

    scheduler.add_job(
        job,
        trigger,
        id="reliability-pipeline",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    logger.info("常驻调度已启动: cron=%s, 时区=%s", config.schedule.cron, config.timezone)

    if config.schedule.run_on_start:
        job()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度已停止")
