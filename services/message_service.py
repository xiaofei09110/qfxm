"""
message_service.py
消息发送核心逻辑（Telethon 版本）。
"""
import asyncio
import logging
import random
from datetime import datetime

from telethon.errors import (
    ChatWriteForbiddenError,
    SlowModeWaitError,
    UserBannedInChannelError,
    FloodWaitError,
    MessageEmptyError,
    PeerIdInvalidError,
)

from config import SEND_DELAY_MIN, SEND_DELAY_MAX
from database import get_session
from models.task import Task
from models.group import Group

logger = logging.getLogger(__name__)


class NeedsVerificationError(Exception):
    def __init__(self, group_id: int):
        self.group_id = group_id
        super().__init__(f"群 {group_id} 需要人机验证")


async def _send_once(client, chat_id, text: str, media_path: str = None):
    if media_path:
        await client.send_file(chat_id, media_path, caption=text)
    else:
        await client.send_message(chat_id, text)


async def safe_send(client, chat_id, text: str, media_path: str = None):
    try:
        await _send_once(client, chat_id, text, media_path)
        await asyncio.sleep(random.uniform(SEND_DELAY_MIN, SEND_DELAY_MAX))
        return True
    except FloodWaitError as e:
        wait = e.seconds + random.randint(3, 10)
        logger.warning("FloodWait %ds，等待后重试", wait)
        await asyncio.sleep(wait)
        await _send_once(client, chat_id, text, media_path)
        return True
    except SlowModeWaitError as e:
        logger.warning("慢速模式 %ds", e.seconds)
        await asyncio.sleep(e.seconds + 2)
        await _send_once(client, chat_id, text, media_path)
        return True
    except ChatWriteForbiddenError:
        raise NeedsVerificationError(chat_id)
    except UserBannedInChannelError:
        logger.error("账号在群 %s 中已被封禁", chat_id)
        raise
    except (MessageEmptyError, PeerIdInvalidError) as e:
        logger.error("发送失败: %s", e)
        raise


def execute_task(task_id: int):
    """APScheduler 定时调用的同步入口。"""
    from core.client_manager import client_manager, run_async

    with get_session() as db:
        task = db.get(Task, task_id)
        if not task or not task.is_active:
            return

        group = db.get(Group, task.group_id)
        if not group:
            logger.error("任务 %d：群组不存在", task_id)
            return

        client = client_manager.get_client(task.account_id)
        if client is None:
            from models.account import Account
            account = db.get(Account, task.account_id)
            if not account:
                logger.error("任务 %d：账号 %d 不存在", task_id, task.account_id)
                task.fail_count += 1
                db.add(task)
                db.commit()
                return
            client, status, _ = client_manager.connect_account(account)
            if status != "active":
                logger.warning("任务 %d：账号连接失败 status=%s", task_id, status)
                task.fail_count += 1
                db.add(task)
                db.commit()
                return

        # 优先用 username 发送，避免 MemorySession 重启后正整数 ID 被 Telethon 误判为用户 ID
        chat_peer = group.username if group.username else int(group.tg_id)

        auto_disable = False
        try:
            run_async(safe_send(client, chat_peer, task.message_text, task.media_path), timeout=300)
            task.run_count += 1
            task.last_run = datetime.now()
            task.last_error = None
            logger.info("任务 %d 执行成功，发送至 %s", task_id, chat_peer)
        except NeedsVerificationError:
            group.needs_verify = True
            db.add(group)
            task.fail_count += 1
            task.is_active = False
            task.last_error = "群组需要人机验证（用手机打开 Telegram 完成验证）"
            auto_disable = True
            logger.warning("任务 %d 已自动停用：群 %s 需要人机验证", task_id, group.tg_id)
        except Exception as e:
            task.fail_count += 1
            task.is_active = False
            task.last_error = str(e)
            auto_disable = True
            logger.error("任务 %d 失败已自动停用: %s", task_id, e)
        finally:
            db.add(task)
            db.commit()

    if auto_disable:
        import core.scheduler as scheduler
        scheduler.remove_task(task_id)
        logger.info("任务 %d 已从调度器移除", task_id)
