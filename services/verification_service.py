"""
verification_service.py
通过 Telethon 自动与 @SpamBot 交互，完成账号限制申诉流程。

SpamBot 验证流程：
  1. 发送 /start 给 @SpamBot
  2. 读取回复 —— 判断账号是否受限
  3. 如受限，自动点击申诉按钮（"NO, I DIDN'T DO THAT" 之类）
  4. 返回最终结果文本
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
