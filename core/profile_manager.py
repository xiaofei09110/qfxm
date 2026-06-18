"""
profile_manager.py
批量修改账号头像、名称、简介（Telethon 版本）。
"""
import asyncio
import logging
import os
import random
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.functions.users import GetFullUserRequest

logger = logging.getLogger(__name__)

_OP_DELAY = (5, 15)


async def _safe_delay():
    await asyncio.sleep(random.uniform(*_OP_DELAY))


async def update_name(client: TelegramClient, first_name: str, last_name: str = "") -> bool:
    try:
        await client(UpdateProfileRequest(first_name=first_name, last_name=last_name))
        logger.info("名称已更新: %s %s", first_name, last_name)
        await _safe_delay()
        return True
    except FloodWaitError as e:
        logger.warning("update_name FloodWait %ds", e.seconds)
        await asyncio.sleep(e.seconds + 5)
        return False
    except Exception as e:
        logger.error("update_name 失败: %s", e)
        return False


async def update_bio(client: TelegramClient, bio: str) -> bool:
    try:
        await client(UpdateProfileRequest(about=bio))
        logger.info("简介已更新")
        await _safe_delay()
        return True
    except FloodWaitError as e:
        logger.warning("update_bio FloodWait %ds", e.seconds)
        await asyncio.sleep(e.seconds + 5)
        return False
    except Exception as e:
        logger.error("update_bio 失败: %s", e)
        return False


async def update_photo(client: TelegramClient, photo_path: str) -> bool:
    if not os.path.isfile(photo_path):
        logger.error("头像文件不存在: %s", photo_path)
        return False
    try:
        uploaded = await client.upload_file(photo_path)
        await client(UploadProfilePhotoRequest(file=uploaded))
        logger.info("头像已更新: %s", photo_path)
        await _safe_delay()
        return True
    except FloodWaitError as e:
        logger.warning("update_photo FloodWait %ds", e.seconds)
        await asyncio.sleep(e.seconds + 5)
        return False
    except Exception as e:
        logger.error("update_photo 失败: %s", e)
        return False


async def batch_update_profiles(
    clients: list,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    bio: Optional[str] = None,
    photo_path: Optional[str] = None,
) -> dict:
    results = {}
    for account_id, client in clients:
        res = {}
        if first_name is not None:
            res["name"] = await update_name(client, first_name, last_name or "")
        if bio is not None:
            res["bio"] = await update_bio(client, bio)
        if photo_path is not None:
            res["photo"] = await update_photo(client, photo_path)
        results[account_id] = res
        await asyncio.sleep(random.uniform(3, 8))
    return results
