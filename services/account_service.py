"""
account_service.py
账号业务逻辑：批量导入协议号文件夹、批量验证状态。
"""
import logging
from datetime import datetime
from typing import List, Tuple

from sqlmodel import select

from database import get_session
from models.account import Account
from core.session_importer import (
    import_account_folders, scan_parent_folder,
    import_flat_folder, is_flat_format,
)
from core.client_manager import client_manager

logger = logging.getLogger(__name__)


def import_from_folders(folder_paths: List[str]) -> List[dict]:
    """
    批量导入协议号文件夹列表，写入数据库。
    folder_paths: 每个元素是一个协议号文件夹路径（如 D:\\桌面\\协议号\\916299146095）
    """
    raw_results = import_account_folders(folder_paths)
    outcomes = []

    with get_session() as db:
        for info in raw_results:
            if info.get("error"):
                outcomes.append({"phone": info.get("phone", "?"), "status": "failed", "reason": info["error"]})
                continue

            # 同一手机号不重复导入
            existing = db.exec(select(Account).where(Account.phone == info["phone"])).first()
            if existing:
                outcomes.append({"phone": info["phone"], "status": "skipped", "reason": "已存在"})
                continue

            account = Account(
                name=info["first_name"] or info["phone"],
                phone=info["phone"],
                session_path=info["session_path"],
                session_type=info["session_type"],
                app_id=info["app_id"],
                app_hash=info["app_hash"],
                two_fa=info["two_fa"],
                device_model=info["device_model"],
                app_version=info["app_version"],
                system_lang=info["system_lang"],
                first_name=info["first_name"],
                last_name=info["last_name"],
                user_id=info["user_id"],
                is_premium=info["is_premium"],
                spamblock=info["spamblock"],
                proxy_type=info["proxy_type"],
                proxy_host=info["proxy_host"],
                proxy_port=info["proxy_port"],
                proxy_user=info["proxy_user"],
                proxy_pass=info["proxy_pass"],
            )
            db.add(account)
            db.commit()
            db.refresh(account)
            outcomes.append({"phone": info["phone"], "status": "ok", "account_id": account.id})
            logger.info("账号入库: id=%d phone=%s", account.id, info["phone"])

    return outcomes


def import_from_parent_folder(parent_path: str) -> List[dict]:
    """
    扫描父文件夹，自动识别两种格式：
    - 旧格式：含以数字命名的子文件夹，每个子文件夹一个账号
    - 新平铺格式：.session + .json 文件直接在父文件夹内
    """
    if is_flat_format(parent_path):
        raw = import_flat_folder(parent_path)
    else:
        folders = scan_parent_folder(parent_path)
        if not folders:
            return [{"phone": "", "status": "failed",
                     "reason": f"未找到协议号（无子文件夹也无 .session 文件）: {parent_path}"}]
        raw = import_account_folders(folders)

    outcomes = []
    with get_session() as db:
        for info in raw:
            if info.get("error"):
                outcomes.append({"phone": info.get("phone", "?"), "status": "failed",
                                  "reason": info["error"]})
                continue
            existing = db.exec(select(Account).where(Account.phone == info["phone"])).first()
            if existing:
                outcomes.append({"phone": info["phone"], "status": "skipped", "reason": "已存在"})
                continue
            account = Account(
                name=info["first_name"] or info["phone"],
                phone=info["phone"],
                session_path=info["session_path"],
                session_type=info["session_type"],
                app_id=info["app_id"],
                app_hash=info["app_hash"],
                two_fa=info["two_fa"],
                device_model=info["device_model"],
                app_version=info["app_version"],
                system_lang=info["system_lang"],
                first_name=info["first_name"],
                last_name=info["last_name"],
                user_id=info["user_id"],
                is_premium=info["is_premium"],
                spamblock=info["spamblock"],
                proxy_type=info["proxy_type"],
                proxy_host=info["proxy_host"],
                proxy_port=info["proxy_port"],
                proxy_user=info["proxy_user"],
                proxy_pass=info["proxy_pass"],
            )
            db.add(account)
            db.commit()
            db.refresh(account)
            outcomes.append({"phone": info["phone"], "status": "ok", "account_id": account.id})
    return outcomes


def check_account_status(account_id: int) -> str:
    """连接账号并检测状态，结果写回数据库。"""
    with get_session() as db:
        account = db.get(Account, account_id)
        if not account:
            return "not_found"

        client, status, me = client_manager.connect_account(account)

        account.status = status
        account.last_checked = datetime.now()

        if status == "active" and me:
            account.error_msg = None
            account.phone = str(me.phone or account.phone or "")
            account.first_name = me.first_name or account.first_name
        else:
            account.error_msg = status

        db.add(account)
        db.commit()
        return status


def batch_check_status(account_ids: List[int]) -> List[Tuple[int, str]]:
    results = []
    for aid in account_ids:
        status = check_account_status(aid)
        results.append((aid, status))
    return results


def list_accounts() -> List[Account]:
    with get_session() as db:
        return db.exec(select(Account)).all()


def set_account_owner(account_ids: List[int], owner: str):
    """设置账号归属分组标签。"""
    with get_session() as db:
        for aid in account_ids:
            acc = db.get(Account, aid)
            if acc:
                acc.owner = owner
                db.add(acc)
        db.commit()


def set_accounts_resting(account_ids: List[int], resting: bool = True):
    with get_session() as db:
        for aid in account_ids:
            acc = db.get(Account, aid)
            if acc:
                acc.is_resting = resting
                db.add(acc)
        db.commit()


def delete_account(account_id: int):
    import os
    client_manager.disconnect_account(account_id)
    with get_session() as db:
        account = db.get(Account, account_id)
        if account:
            session_path = account.session_path
            db.delete(account)
            db.commit()
            if session_path and os.path.exists(session_path):
                try:
                    os.remove(session_path)
                    logger.info("已删除 session 文件: %s", session_path)
                except Exception as e:
                    logger.warning("删除 session 文件失败: %s", e)


def update_proxy(account_id: int, proxy_type: str, host: str, port: int,
                 user: str = "", password: str = ""):
    with get_session() as db:
        account = db.get(Account, account_id)
        if not account:
            return
        account.proxy_type = proxy_type
        account.proxy_host = host
        account.proxy_port = port
        account.proxy_user = user or None
        account.proxy_pass = password or None
        db.add(account)
        db.commit()
