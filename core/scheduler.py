"""
scheduler.py
APScheduler 封装，使用 SQLAlchemyJobStore 持久化任务到 SQLite。
程序重启后所有定时任务自动恢复，不会丢失。
"""
import logging
from datetime import datetime
from typing import Callable

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

from config import DB_PATH

logger = logging.getLogger(__name__)

_jobstores = {
    "default": SQLAlchemyJobStore(url=f"sqlite:///{DB_PATH}")
}

_scheduler = BackgroundScheduler(
    jobstores=_jobstores,
    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
    timezone=pytz.timezone("Asia/Shanghai"),
)


def _on_job_executed(event):
    logger.info("任务执行成功: job_id=%s", event.job_id)


def _on_job_error(event):
    logger.error("任务执行失败: job_id=%s, exception=%s", event.job_id, event.exception)


_scheduler.add_listener(_on_job_executed, EVENT_JOB_EXECUTED)
_scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)


def start():
    if not _scheduler.running:
        _scheduler.start()
        logger.info("调度器已启动，已有 job 数: %d", len(_scheduler.get_jobs()))


def stop():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("调度器已停止")


def add_task(task_id: int, cron_expr: str, func: Callable, timezone: str = "Asia/Shanghai"):
    """
    注册或更新一个定时任务。
    用位置参数 args=(task_id,) 传递参数：
      - APScheduler 的 SQLite 持久化可以序列化整数，不会报 "cannot be serialized"
      - 绕过 APScheduler 3.x 在 Python 3.13 下对 kwargs 校验的 bug
    """
    job_id = f"task_{task_id}"
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(f"cron 表达式格式错误: {cron_expr}，应为 5 个字段")

    minute, hour, day, month, day_of_week = parts
    trigger = CronTrigger(
        minute=minute, hour=hour, day=day, month=month,
        day_of_week=day_of_week, timezone=pytz.timezone(timezone)
    )

    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)
    _scheduler.add_job(func, trigger=trigger, id=job_id, args=(task_id,))
    logger.info("任务已注册: %s cron=%s", job_id, cron_expr)


def remove_task(task_id: int):
    job_id = f"task_{task_id}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)
        logger.info("任务已移除: %s", job_id)


def get_next_run(task_id: int) -> datetime | None:
    job = _scheduler.get_job(f"task_{task_id}")
    return job.next_run_time if job else None


def list_jobs() -> list:
    return _scheduler.get_jobs()
