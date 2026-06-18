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


async def _ensure_joined(client, chat_peer) -> str:
    """
    确保账号已加入群组。若未加入则自动 join，join 后等待并点击验证 bot 按钮。
    返回简短状态描述（用于日志）。
    """
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.errors import (
        UserAlreadyParticipantError, ChannelPrivateError,
        InviteHashExpiredError, UserBannedInChannelError as BannedError,
    )

    try:
        entity = await client.get_entity(chat_peer)
    except Exception as e:
        return f"get_entity 失败: {e}"

    try:
        await client(JoinChannelRequest(entity))
        logger.info("已加入群组 %s，等待验证 bot...", chat_peer)
        await asyncio.sleep(4)
        await _click_join_verify_buttons(client, entity)
        return "joined"
    except UserAlreadyParticipantError:
        return "already_member"
    except ChannelPrivateError:
        return "private_group"
    except (InviteHashExpiredError, BannedError) as e:
        return f"无法加入: {e}"
    except Exception as e:
        logger.warning("加入群组 %s 时出错: %s", chat_peer, e)
        return f"join_error: {e}"


async def _click_join_verify_buttons(client, group_entity):
    """加入群后，扫描群内和近期私信里的验证 bot 按钮并自动点击。"""
    # 1. 群内验证消息
    try:
        msgs = await client.get_messages(group_entity, limit=20)
        for msg in msgs:
            sender = getattr(msg, "sender", None)
            if not (msg.buttons and sender and getattr(sender, "bot", False)):
                continue
            try:
                await msg.buttons[0][0].click()
                logger.info("已点击群内验证按钮: %s", msg.buttons[0][0].text)
                await asyncio.sleep(2)
            except Exception as e:
                logger.warning("点击群内验证按钮失败: %s", e)
            break
    except Exception as e:
        logger.warning("扫描群内验证消息失败: %s", e)

    # 2. bot 私信验证（最近 15 个对话里的 bot）
    try:
        dialogs = await client.get_dialogs(limit=15)
        for dialog in dialogs:
            if not (dialog.is_user and getattr(dialog.entity, "bot", False)):
                continue
            msgs = await client.get_messages(dialog.entity, limit=3)
            for msg in msgs:
                if not msg.buttons:
                    continue
                try:
                    await msg.buttons[0][0].click()
                    logger.info("已点击 bot 私信验证按钮 (@%s): %s",
                                getattr(dialog.entity, "username", "?"),
                                msg.buttons[0][0].text)
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning("点击 bot 私信按钮失败: %s", e)
    except Exception as e:
        logger.warning("扫描私信验证消息失败: %s", e)


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

        # 确保账号已加入群组（未加入则自动 join + 点验证按钮）
        join_status = run_async(_ensure_joined(client, chat_peer), timeout=60)
        logger.info("任务 %d 加入群组状态: %s", task_id, join_status)

        # 私有群无法通过公开方式加入，直接停用任务并给出明确原因
        if join_status == "private_group":
            task.fail_count += 1
            task.is_active = False
            task.last_error = "群组为私有群/频道，账号无法通过用户名加入，请提供邀请链接后手动入群，或更换已在群内的账号"
            db.add(task)
            db.commit()
            import core.scheduler as scheduler
            scheduler.remove_task(task_id)
            logger.warning("任务 %d 停用：%s 是私有群", task_id, chat_peer)
            return

        # join 本身就被 ban，也直接停用
        if join_status.startswith("无法加入"):
            task.fail_count += 1
            task.is_active = False
            task.last_error = f"账号无法加入群组：{join_status}"
            db.add(task)
            db.commit()
            import core.scheduler as scheduler
            scheduler.remove_task(task_id)
            logger.warning("任务 %d 停用：%s", task_id, join_status)
            return

        auto_disable = False
        try:
            run_async(safe_send(client, chat_peer, task.message_text, task.media_path), timeout=300)
            task.run_count += 1
            task.last_run = datetime.now()
            task.last_error = None
            if group.needs_verify:
                group.needs_verify = False
                db.add(group)
            logger.info("任务 %d 执行成功，发送至 %s", task_id, chat_peer)
        except NeedsVerificationError:
            group.needs_verify = True
            db.add(group)
            task.fail_count += 1
            task.is_active = False
            task.last_error = (
                "加入后仍无发言权限（群可能设置了需管理员审核，或账号在此群有限制）"
            )
            auto_disable = True
            logger.warning("任务 %d 已自动停用：群 %s 发言被拒", task_id, group.tg_id)
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
