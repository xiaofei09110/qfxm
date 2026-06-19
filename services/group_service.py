"""
group_service.py
群组管理：添加群组、检测发言权限、关联账号、注册定时任务。
"""
import json
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


def clear_group_verify(group_id: int):
    with get_session() as db:
        group = db.get(Group, group_id)
        if group:
            group.needs_verify = False
            db.add(group)
            db.commit()


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
        init_history = json.dumps([{
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "account_id": account_id,
            "old_account_id": None,
            "reason": "初始创建",
        }], ensure_ascii=False)
        task = Task(
            name=name,
            account_id=account_id,
            group_id=group_id,
            message_text=message_text,
            cron_expr=cron_expr,
            timezone=timezone,
            media_path=media_path,
            account_history=init_history,
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
            if task:  # 防止两次 session 之间被删除
                try:
                    scheduler.add_task(task.id, task.cron_expr, execute_task,
                                       timezone=task.timezone)
                except Exception as e:
                    logger.error("任务 %d 注册调度器失败: %s", task_id, e)
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


def switch_task_account(task_id: int, new_account_id: int, reason: str = "手动更换") -> Task:
    """更换任务绑定的账号，并将换号记录追加到 account_history。"""
    with get_session() as db:
        task = db.get(Task, task_id)
        if not task:
            raise ValueError(f"任务 {task_id} 不存在")

        history = json.loads(task.account_history or "[]")
        history.append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "account_id": new_account_id,
            "old_account_id": task.account_id,
            "reason": reason,
        })

        task.account_id = new_account_id
        task.account_history = json.dumps(history, ensure_ascii=False)
        task.last_error = None  # 换号后清空上次错误
        db.add(task)
        db.commit()
        db.refresh(task)
        return task


def update_task_cron(task_id: int, cron_expr: str) -> Task:
    """修改任务的执行时间（cron），若任务已启用则同步更新调度器。"""
    # 先验证 cron 格式，避免写入 DB 后调度器报错造成数据不一致
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"cron 表达式格式错误：{cron_expr}（应为 5 个字段）")
    try:
        from apscheduler.triggers.cron import CronTrigger
        import pytz
        CronTrigger(*parts, timezone=pytz.timezone("UTC"))
    except Exception as e:
        raise ValueError(f"无效的 cron 表达式：{cron_expr}  ({e})")

    with get_session() as db:
        task = db.get(Task, task_id)
        if not task:
            raise ValueError(f"任务 {task_id} 不存在")
        task.cron_expr = cron_expr
        db.add(task)
        db.commit()
        db.refresh(task)
        if task.is_active:
            try:
                scheduler.add_task(task.id, cron_expr, execute_task, timezone=task.timezone)
            except Exception as e:
                logger.error("任务 %d 更新调度器失败: %s", task_id, e)
        return task


def batch_auto_reassign(owner_filter: str = "") -> dict:
    """
    一键换号：为所有停用任务分配账号，优先选在该群从未用过的账号，将燃尽账号标为养号中。
    owner_filter: 若非空，只从该归属分组的账号中选取。
    返回 {"reassigned": int, "rested": list[int], "no_accounts": bool}
    """
    from models.account import Account

    with get_session() as db:
        all_tasks    = db.exec(select(Task)).all()
        stopped_tasks = [t for t in all_tasks if not t.is_active]
        active_tasks  = [t for t in all_tasks if t.is_active]

        if not stopped_tasks:
            return {"reassigned": 0, "rested": [], "no_accounts": False}

        stopped_account_ids = set(t.account_id for t in stopped_tasks)
        active_account_ids  = set(t.account_id for t in active_tasks)
        to_rest = stopped_account_ids - active_account_ids

        all_accounts = db.exec(select(Account)).all()
        # 可用账号：非养号中、未被停用任务占用、符合归属分组筛选
        available = [
            a for a in all_accounts
            if not a.is_resting
            and a.id not in stopped_account_ids
            and (not owner_filter or a.owner == owner_filter)
        ]

        if not available:
            return {"reassigned": 0, "rested": [], "no_accounts": True}

        # 按群组维度统计历史上用过哪些账号（从 account_history 解析）
        group_tried: dict = {}   # {group_id: set of account_ids tried in this group}
        for t in all_tasks:
            gid = t.group_id
            if gid not in group_tried:
                group_tried[gid] = set()
            group_tried[gid].add(t.account_id)
            try:
                for entry in json.loads(t.account_history or "[]"):
                    aid = entry.get("account_id")
                    if aid:
                        group_tried[gid].add(aid)
            except Exception:
                pass

        task_counts = {}
        for t in active_tasks:
            task_counts[t.account_id] = task_counts.get(t.account_id, 0) + 1

        reassigned = 0
        for task in stopped_tasks:
            gid   = task.group_id
            tried = group_tried.get(gid, set())

            # 优先选此群从未用过的账号，次选任务数最少的
            fresh = [a for a in available if a.id not in tried]
            pool  = fresh if fresh else available
            best  = min(pool, key=lambda a: task_counts.get(a.id, 0))

            history = json.loads(task.account_history or "[]")
            history.append({
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "account_id": best.id,
                "old_account_id": task.account_id,
                "reason": "一键换号（账号燃尽）",
            })
            task.account_id      = best.id
            task.account_history = json.dumps(history, ensure_ascii=False)
            task.last_error      = None
            task.is_active       = True
            db.add(task)

            task_counts[best.id] = task_counts.get(best.id, 0) + 1
            group_tried.setdefault(gid, set()).add(best.id)
            reassigned += 1

        rested_ids = list(to_rest)
        for aid in rested_ids:
            acc = db.get(Account, aid)
            if acc:
                acc.is_resting = True
                db.add(acc)

        db.commit()

    with get_session() as db:
        for t in db.exec(select(Task).where(Task.is_active == True)).all():
            try:
                scheduler.add_task(t.id, t.cron_expr, execute_task, timezone=t.timezone)
            except Exception as e:
                logger.error("一键换号后注册任务 %d 失败: %s", t.id, e)

    return {"reassigned": reassigned, "rested": rested_ids, "no_accounts": False}


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
