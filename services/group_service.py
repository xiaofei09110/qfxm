"""
group_service.py
群组管理：添加群组、检测发言权限、关联账号、注册定时任务。
"""
import logging
from datetime import datetime
from typing import List, Optional

from sqlmodel import select

from database import get_session
from models.group import Group
from models.task import Task
from core.client_manager import client_manager
import core.scheduler as scheduler
from services.message_service import execute_task

logger = logging.getLogger(__name__)


def delete_group(group_id: int):
    with get_session() as db:
        group = db.get(Group, group_id)
        if group:
            db.delete(group)
            db.commit()


def add_group(account_id: int, tg_id: str, username: str = "", title: str = "") -> Group:
    with get_session() as db:
        existing = db.exec(select(Group).where(Group.tg_id == tg_id)).first()
        if existing:
            return existing
        group = Group(
            tg_id=tg_id,
            username=username,
            title=title,
            account_id=account_id,
            joined_at=datetime.now(),
        )
        db.add(group)
        db.commit()
        db.refresh(group)
        logger.info("群组已添加: %s (%s)", title, tg_id)
        return group


def resolve_group_info(account_id: int, group_username_or_id: str) -> Optional[dict]:
    """
    通过 Telethon 获取群组的真实 ID 和标题。
    group_username_or_id: @username 或数字 ID 字符串
    未连接时自动尝试重连账号。
    """
    client = client_manager.get_client(account_id)
    if not client:
        logger.info("账号 %d 未连接，尝试自动连接...", account_id)
        with get_session() as db:
            from models.account import Account
            account = db.get(Account, account_id)
            if not account:
                logger.error("账号 %d 不存在", account_id)
                return None
        client, status, _ = client_manager.connect_account(account)
        if status != "active":
            logger.error("账号 %d 连接失败: %s", account_id, status)
            return None
    try:
        chat = client_manager.get_entity(account_id, group_username_or_id)
        return {
            "tg_id": str(chat.id),
            "username": getattr(chat, "username", "") or "",
            "title": getattr(chat, "title", "") or "",
        }
    except Exception as e:
        logger.error("获取群组信息失败: %s", e)
        return None


def list_groups() -> List[Group]:
    with get_session() as db:
        return db.exec(select(Group)).all()


def create_task(
    account_id: int,
    group_id: int,
    message_text: str,
    cron_expr: str,
    name: str = "",
    timezone: str = "Asia/Shanghai",
    media_path: str = None,
) -> Task:
    """
    创建定时消息任务并注册到调度器。
    """
    with get_session() as db:
        task = Task(
            name=name,
            account_id=account_id,
            group_id=group_id,
            message_text=message_text,
            cron_expr=cron_expr,
            timezone=timezone,
            media_path=media_path,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        scheduler.add_task(
            task_id=task.id,
            cron_expr=cron_expr,
            func=execute_task,
            timezone=timezone,
        )
        logger.info("定时任务已创建并注册: id=%d cron=%s", task.id, cron_expr)
        return task


def toggle_task(task_id: int, active: bool):
    with get_session() as db:
        task = db.get(Task, task_id)
        if not task:
            return
        task.is_active = active
        db.add(task)
        db.commit()

    if active:
        with get_session() as db:
            task = db.get(Task, task_id)
            scheduler.add_task(task.id, task.cron_expr, execute_task,
                               timezone=task.timezone)
    else:
        scheduler.remove_task(task_id)


def delete_task(task_id: int):
    scheduler.remove_task(task_id)
    with get_session() as db:
        task = db.get(Task, task_id)
        if task:
            db.delete(task)
            db.commit()


def list_tasks() -> List[Task]:
    with get_session() as db:
        return db.exec(select(Task)).all()


def restore_all_tasks():
    """
    程序启动时调用，将数据库中所有 is_active=True 的任务重新注册到调度器。
    APScheduler 本身会从 SQLite 恢复 job，此函数用于补充可能遗漏的 job。
    """
    with get_session() as db:
        tasks = db.exec(select(Task).where(Task.is_active == True)).all()
        for task in tasks:
            job_id = f"task_{task.id}"
            if not scheduler._scheduler.get_job(job_id):
                scheduler.add_task(task.id, task.cron_expr, execute_task,
                                   timezone=task.timezone)
                logger.info("任务已恢复: id=%d", task.id)
