"""
verification_service.py
两类自动验证：

1. SpamBot 申诉（verify_account）
   账号被 Telegram 全局限制时，自动联系 @SpamBot 点申诉按钮。

2. 群组入群验证（verify_group_join）
   进群后验证机器人发的"点按钮才能发言"验证：
   - 扫描群内近期 bot 消息，找内联按钮并点击
   - 同时扫描与群相关的 bot 私信，点击验证按钮
   - 清除数据库中的 needs_verify 标记，重新激活任务
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

SPAMBOT = "@SpamBot"

# 回复中表示"状态正常"的关键词（SpamBot 英文回复）
_OK_KEYWORDS = [
    "no limitations", "not limited", "good standing",
    "free to use", "isn't limited",
]

# 申诉按钮关键词（匹配 SpamBot 内联按钮文字）
_APPEAL_KEYWORDS = [
    "no", "wasn't", "didn't", "appeal", "this is", "spam free",
    "not spam", "remove",
]


async def _spambot_appeal(client) -> str:
    """
    与 @SpamBot 完整交互一轮，返回描述结果的字符串。
    调用者负责传入已连接的 TelegramClient。
    """
    # Step 1: 发 /start
    try:
        await client.send_message(SPAMBOT, "/start")
    except Exception as e:
        return f"无法联系 @SpamBot：{e}"

    await asyncio.sleep(3)

    # Step 2: 读取回复
    try:
        msgs = await client.get_messages(SPAMBOT, limit=1)
    except Exception as e:
        return f"读取 @SpamBot 回复失败：{e}"

    if not msgs:
        return "@SpamBot 无响应，请稍后重试"

    msg = msgs[0]
    text = (msg.message or "").strip()

    logger.debug("SpamBot 回复: %s", text[:200])

    # Step 3: 判断是否已经正常
    if any(kw in text.lower() for kw in _OK_KEYWORDS):
        return f"✅ 账号状态正常，无限制。\n\nSpamBot 原文：\n{text[:400]}"

    # Step 4: 尝试点击申诉按钮
    clicked_text = None
    if msg.buttons:
        for row in msg.buttons:
            for btn in row:
                if any(kw in btn.text.lower() for kw in _APPEAL_KEYWORDS):
                    try:
                        await btn.click()
                        clicked_text = btn.text
                        logger.info("已点击 SpamBot 按钮: %s", btn.text)
                    except Exception as e:
                        logger.warning("点击按钮失败: %s", e)
                    break
            if clicked_text:
                break

        # 如果没有匹配关键词，点第一个按钮
        if not clicked_text:
            try:
                await msg.buttons[0][0].click()
                clicked_text = msg.buttons[0][0].text
                logger.info("点击了第一个按钮: %s", clicked_text)
            except Exception as e:
                logger.warning("点击第一个按钮失败: %s", e)

    if clicked_text:
        await asyncio.sleep(3)
        try:
            msgs2 = await client.get_messages(SPAMBOT, limit=1)
            if msgs2 and msgs2[0].id != msg.id:
                reply = (msgs2[0].message or "").strip()
                return (
                    f"✅ 申诉请求已提交（点击了「{clicked_text}」）。\n"
                    f"Telegram 通常在数小时内处理，请稍后回来查看账号状态。\n\n"
                    f"SpamBot 回复：\n{reply[:400]}"
                )
        except Exception:
            pass
        return f"✅ 已点击申诉按钮「{clicked_text}」，请等待 Telegram 处理。"

    # 没有按钮可点
    return (
        f"⚠️ @SpamBot 回复如下，但未找到申诉按钮（可能账号限制类型不同）：\n\n{text[:400]}"
    )


def verify_account(account_id: int) -> str:
    """
    同步入口：连接指定账号并执行 SpamBot 申诉。
    返回用户可读的结果字符串。
    """
    from core.client_manager import client_manager, run_async
    from database import get_session
    from models.account import Account

    with get_session() as db:
        account = db.get(Account, account_id)
        if not account:
            return "账号不存在"

    client = client_manager.get_client(account_id)
    if client is None:
        with get_session() as db:
            account = db.get(Account, account_id)
        client, status, _ = client_manager.connect_account(account)
        if status != "active":
            return f"账号连接失败（状态: {status}），请先在「账号管理」验证账号"

    try:
        result = run_async(_spambot_appeal(client), timeout=30)
        logger.info("账号 %d SpamBot 申诉完成: %s", account_id, result[:80])
        return result
    except Exception as e:
        logger.error("账号 %d SpamBot 申诉异常: %s", account_id, e)
        return f"执行出错：{e}"


# ── 群组入群验证 ──────────────────────────────────────────────────────────


# 跳过这些按钮文字（明显不是验证按钮）
_SKIP_BTN_KEYWORDS = [
    "skip", "cancel", "back", "menu", "close", "规则", "rule",
    "help", "about", "info",
]

# 验证按钮常见关键词（优先点）
_VERIFY_BTN_KEYWORDS = [
    "verify", "human", "i am", "confirm", "continue", "join",
    "start", "accept", "agree", "验证", "确认", "我是人",
    "点击", "click", "press",
]


async def _click_buttons_in_message(msg) -> list[str]:
    """点击一条消息里的内联按钮，返回点击结果列表。"""
    actions = []
    if not msg.buttons:
        return actions

    # 先找匹配验证关键词的按钮，没有再点第一个
    target_btn = None
    for row in msg.buttons:
        for btn in row:
            txt = btn.text.lower()
            if any(kw in txt for kw in _SKIP_BTN_KEYWORDS):
                continue
            if any(kw in txt for kw in _VERIFY_BTN_KEYWORDS):
                target_btn = btn
                break
        if target_btn:
            break

    if target_btn is None:
        # 取第一个非跳过按钮
        for row in msg.buttons:
            for btn in row:
                if not any(kw in btn.text.lower() for kw in _SKIP_BTN_KEYWORDS):
                    target_btn = btn
                    break
            if target_btn:
                break

    if target_btn:
        try:
            await target_btn.click()
            actions.append(f"✅ 点击按钮「{target_btn.text}」成功")
            await asyncio.sleep(1.5)
        except Exception as e:
            actions.append(f"⚠️ 点击按钮「{target_btn.text}」失败：{e}")

    return actions


async def _verify_in_group(client, group_peer) -> list[str]:
    """扫描群内近期 bot 消息并点击验证按钮。"""
    actions = []
    try:
        msgs = await client.get_messages(group_peer, limit=30)
    except Exception as e:
        return [f"读取群消息失败：{e}"]

    for msg in msgs:
        sender = getattr(msg, "sender", None)
        is_bot = sender and getattr(sender, "bot", False)
        if not (msg.buttons and is_bot):
            continue
        results = await _click_buttons_in_message(msg)
        if results:
            actions.extend(results)
            break  # 一般只有一条验证消息，点完就停

    return actions or ["群内未发现带按钮的 bot 验证消息"]


async def _verify_in_dms(client) -> list[str]:
    """扫描最近私信，找 bot 发来的验证消息并点击。"""
    actions = []
    try:
        # 只看最近 20 个对话中的 bot 私信
        dialogs = await client.get_dialogs(limit=20)
    except Exception as e:
        return [f"读取对话列表失败：{e}"]

    for dialog in dialogs:
        entity = dialog.entity
        if not (dialog.is_user and getattr(entity, "bot", False)):
            continue
        try:
            msgs = await client.get_messages(entity, limit=3)
        except Exception:
            continue
        for msg in msgs:
            if not msg.buttons:
                continue
            bot_name = getattr(entity, "username", None) or str(entity.id)
            results = await _click_buttons_in_message(msg)
            if results:
                actions.extend([f"[私信 @{bot_name}] {r}" for r in results])

    return actions or ["私信中未发现待验证的 bot 消息"]


async def _do_group_verify(client, group_peer) -> str:
    """完整执行一次群组入群验证：群内 + 私信。"""
    lines = ["── 群内验证消息 ──"]
    lines += await _verify_in_group(client, group_peer)
    await asyncio.sleep(2)
    lines += ["", "── Bot 私信验证 ──"]
    lines += await _verify_in_dms(client)
    return "\n".join(lines)


def verify_group_join(account_id: int, group_id: int) -> str:
    """
    同步入口：用指定账号对指定群执行入群验证点击。
    验证通过后清除 DB 中的 needs_verify 标记并重新激活相关任务。
    """
    from core.client_manager import client_manager, run_async
    from database import get_session
    from models.account import Account
    from models.group import Group
    from models.task import Task
    from sqlmodel import select
    import core.scheduler as scheduler
    from services.message_service import execute_task

    # 取账号
    with get_session() as db:
        account = db.get(Account, account_id)
        group = db.get(Group, group_id)
        if not account:
            return "账号不存在"
        if not group:
            return "群组不存在"

    client = client_manager.get_client(account_id)
    if client is None:
        with get_session() as db:
            account = db.get(Account, account_id)
        client, status, _ = client_manager.connect_account(account)
        if status != "active":
            return f"账号连接失败（状态: {status}），请先验证账号"

    group_peer = group.username if group.username else int(group.tg_id)

    try:
        result = run_async(_do_group_verify(client, group_peer), timeout=30)
    except Exception as e:
        return f"验证执行出错：{e}"

    # 清除 needs_verify 并重新激活该群的任务
    with get_session() as db:
        grp = db.get(Group, group_id)
        if grp:
            grp.needs_verify = False
            db.add(grp)

        tasks = db.exec(
            select(Task).where(Task.group_id == group_id, Task.is_active == False)
        ).all()
        reactivated = []
        for task in tasks:
            if task.last_error and "验证" in task.last_error:
                task.is_active = True
                task.last_error = None
                db.add(task)
                reactivated.append(task.id)

        db.commit()

    if reactivated:
        with get_session() as db:
            for tid in reactivated:
                task = db.get(Task, tid)
                if task:
                    try:
                        scheduler.add_task(task.id, task.cron_expr, execute_task,
                                           timezone=task.timezone)
                    except Exception as e:
                        logger.error("重新注册任务 %d 失败: %s", tid, e)
        result += f"\n\n✅ 已重新激活任务：{reactivated}"
    else:
        result += "\n\n（未找到因验证停用的任务，请手动启用）"

    logger.info("群 %d 入群验证完成: %s", group_id, result[:100])
    return result
