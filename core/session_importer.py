"""
session_importer.py
导入协议号文件夹。
每个协议号是一个以手机号命名的文件夹，内含：
  - {phone}.session        — Pyrogram session 文件
  - {phone}.json           — 账号元数据（app_id/hash、2FA、设备信息等）
  - 2fa.txt                — 2FA 密码（备用）
  - tdata/                 — TDesktop 数据（本项目暂不使用）
"""
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from config import SESSIONS_DIR

logger = logging.getLogger(__name__)


def _read_json_meta(folder: str) -> Optional[dict]:
    """读取文件夹内的 .json 元数据文件。"""
    for f in os.listdir(folder):
        if f.endswith(".json"):
            path = os.path.join(folder, f)
            try:
                with open(path, encoding="utf-8") as fp:
                    return json.load(fp)
            except Exception as e:
                logger.warning("读取 JSON 失败 %s: %s", path, e)
    return None


def _read_2fa(folder: str, json_meta: Optional[dict]) -> Optional[str]:
    """优先从 JSON 的 twoFA 字段读取，其次读 2fa.txt。"""
    if json_meta and json_meta.get("twoFA"):
        return str(json_meta["twoFA"])
    txt = os.path.join(folder, "2fa.txt")
    if os.path.isfile(txt):
        content = open(txt, encoding="utf-8").read().strip()
        return content if content else None
    return None


def _find_session_file(folder: str, phone: str) -> Optional[str]:
    """在文件夹内找 .session 文件。"""
    candidate = os.path.join(folder, f"{phone}.session")
    if os.path.isfile(candidate):
        return candidate
    # 兜底：找任意 .session 文件
    for f in os.listdir(folder):
        if f.endswith(".session") and not f.endswith("-journal"):
            return os.path.join(folder, f)
    return None


def import_account_folder(folder_path: str) -> dict:
    """
    导入单个协议号文件夹。
    返回包含所有必要信息的 dict，供 account_service 写入数据库。
    出错时返回 {"error": "原因"}。
    """
    folder_path = os.path.abspath(folder_path)
    if not os.path.isdir(folder_path):
        return {"error": f"不是文件夹: {folder_path}"}

    phone = Path(folder_path).name  # 文件夹名即手机号

    meta = _read_json_meta(folder_path)
    if not meta:
        return {"error": f"找不到 JSON 元数据: {folder_path}"}

    session_src = _find_session_file(folder_path, phone)
    if not session_src:
        return {"error": f"找不到 .session 文件: {folder_path}"}

    # 把 session 文件复制到统一存储目录
    dest_session = os.path.join(SESSIONS_DIR, f"{phone}.session")
    if not os.path.exists(dest_session):
        shutil.copy2(session_src, dest_session)

    # 解析代理（如果 JSON 里有）
    proxy = meta.get("proxy") or {}

    return {
        "phone": str(meta.get("phone", phone)),
        "session_path": os.path.abspath(dest_session),
        "session_type": "telethon",
        "app_id": int(meta.get("app_id", 2040)),
        "app_hash": str(meta.get("app_hash", "b18441a1ff607e10a989891a5462e627")),
        "two_fa": _read_2fa(folder_path, meta),
        "device_model": meta.get("device") or meta.get("device_model"),
        "app_version": meta.get("app_version"),
        "system_lang": meta.get("system_lang_pack"),
        "first_name": meta.get("first_name"),
        "last_name": meta.get("last_name"),
        "user_id": meta.get("user_id") or meta.get("id"),
        "is_premium": bool(meta.get("is_premium", False)),
        "spamblock": meta.get("spamblock"),
        "proxy_type": proxy.get("type") if proxy else None,
        "proxy_host": proxy.get("host") if proxy else None,
        "proxy_port": proxy.get("port") if proxy else None,
        "proxy_user": proxy.get("user") if proxy else None,
        "proxy_pass": proxy.get("pass") if proxy else None,
        "error": "",
    }


def import_account_folders(folder_paths: list) -> list:
    """批量导入多个协议号文件夹，返回结果列表。"""
    results = []
    for path in folder_paths:
        result = import_account_folder(path)
        results.append(result)
        if result.get("error"):
            logger.error("导入失败 %s: %s", path, result["error"])
        else:
            logger.info("导入成功: %s", result["phone"])
    return results


def scan_parent_folder(parent_path: str) -> list:
    """
    扫描父文件夹（如 D:\桌面\协议号\），
    自动找出其中所有以数字命名的子文件夹（即各个协议号）。
    返回子文件夹绝对路径列表。
    """
    parent_path = os.path.abspath(parent_path)
    if not os.path.isdir(parent_path):
        return []
    result = []
    for name in os.listdir(parent_path):
        sub = os.path.join(parent_path, name)
        if os.path.isdir(sub) and name.isdigit():
            result.append(sub)
    return sorted(result)
