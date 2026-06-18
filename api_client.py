"""
api_client.py — 客户端 HTTP 封装
SERVER_URL 非空时，GUI 通过此模块与服务器通信，本地不运行任何 Telegram 逻辑。
"""
import io
import os
import zipfile
from datetime import datetime
from types import SimpleNamespace
from typing import List, Optional, Tuple

import requests

from config import API_KEY, SERVER_URL


def _h():
    return {"X-API-Key": API_KEY}


def _get(path, timeout=30):
    r = requests.get(f"{SERVER_URL}{path}", headers=_h(), timeout=timeout)
    r.raise_for_status()
    return r.json()


def _post(path, json=None, timeout=60, **kw):
    r = requests.post(f"{SERVER_URL}{path}", json=json, headers=_h(), timeout=timeout, **kw)
    r.raise_for_status()
    return r.json()


def _put(path, timeout=30, **kw):
    r = requests.put(f"{SERVER_URL}{path}", headers=_h(), timeout=timeout, **kw)
    r.raise_for_status()
    return r.json()


def _delete(path, timeout=30):
    r = requests.delete(f"{SERVER_URL}{path}", headers=_h(), timeout=timeout)
    r.raise_for_status()
    return r.json()


def _dt(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).split(".")[0])
    except Exception:
        return None


def _account(d: dict) -> SimpleNamespace:
    d["last_checked"] = _dt(d.get("last_checked"))
    d["created_at"]   = _dt(d.get("created_at"))
    return SimpleNamespace(**d)


def _group(d: dict) -> SimpleNamespace:
    d["joined_at"]  = _dt(d.get("joined_at"))
    d["created_at"] = _dt(d.get("created_at"))
    return SimpleNamespace(**d)


def _task(d: dict) -> SimpleNamespace:
    d["last_run"]   = _dt(d.get("last_run"))
    d["created_at"] = _dt(d.get("created_at"))
    return SimpleNamespace(**d)


# ── 账号 ──────────────────────────────────────────────────────────────

def list_accounts() -> List[SimpleNamespace]:
    return [_account(d) for d in _get("/accounts")]


def import_from_parent_folder(parent_path: str) -> List[dict]:
    results = []
    for name in sorted(os.listdir(parent_path)):
        sub = os.path.join(parent_path, name)
        if os.path.isdir(sub) and name.isdigit():
            results.extend(_upload_folder(sub))
    return results


def import_from_folders(folder_paths: List[str]) -> List[dict]:
    results = []
    for fp in folder_paths:
        results.extend(_upload_folder(fp))
    return results


def _upload_folder(folder_path: str) -> List[dict]:
    """打包单个协议号文件夹并上传到服务器。"""
    buf = io.BytesIO()
    folder_name = os.path.basename(folder_path)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in os.listdir(folder_path):
            fpath = os.path.join(folder_path, fname)
            if os.path.isfile(fpath) and not fname.endswith("-journal"):
                zf.write(fpath, os.path.join(folder_name, fname))
    buf.seek(0)
    r = requests.post(
        f"{SERVER_URL}/accounts/upload",
        headers=_h(),
        files={"file": (f"{folder_name}.zip", buf, "application/zip")},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


def check_account_status(account_id: int) -> str:
    try:
        data = _post(f"/accounts/{account_id}/check", timeout=90)
        return data.get("status", "error")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("验证账号 %d 失败: %s", account_id, e)
        return "error"


def batch_check_status(account_ids: List[int]) -> List[Tuple[int, str]]:
    results = []
    for aid in account_ids:
        status = check_account_status(aid)
        results.append((aid, status))
    return results


def verify_account_spambot(account_id: int) -> str:
    data = _post(f"/accounts/{account_id}/verify")
    return data.get("message", "")


def verify_group_join(account_id: int, group_id: int) -> str:
    data = _post(f"/groups/{group_id}/verify", json={"account_id": account_id})
    return data.get("message", "")


def delete_account(account_id: int):
    _delete(f"/accounts/{account_id}")


def batch_update_profiles_remote(
    account_ids: List[int],
    first_name=None, last_name=None, bio=None, photo_path=None
) -> dict:
    server_photo = None
    if photo_path and os.path.isfile(photo_path):
        with open(photo_path, "rb") as f:
            r = requests.post(
                f"{SERVER_URL}/upload/media",
                headers=_h(),
                files={"file": (os.path.basename(photo_path), f)},
                timeout=60,
            )
            r.raise_for_status()
            server_photo = r.json()["path"]

    data = _post("/accounts/profile", json={
        "account_ids": account_ids,
        "first_name": first_name,
        "last_name": last_name,
        "bio": bio,
        "photo_path": server_photo,
    }, timeout=300)
    return data.get("results", {})


# ── 群组 ──────────────────────────────────────────────────────────────

def list_groups() -> List[SimpleNamespace]:
    return [_group(d) for d in _get("/groups")]


def resolve_group_info(account_id: int, group_input: str) -> Optional[dict]:
    try:
        return _post("/groups/resolve", json={
            "account_id": account_id, "group_input": group_input
        }, timeout=30)
    except Exception:
        return None


def add_group(account_id: int, tg_id: str, username: str = "", title: str = "") -> SimpleNamespace:
    data = _post("/groups/save", json={
        "account_id": account_id, "tg_id": tg_id,
        "username": username, "title": title,
    })
    return _group(data)


def delete_group(group_id: int):
    _delete(f"/groups/{group_id}")


# ── 定时任务 ──────────────────────────────────────────────────────────

def list_tasks() -> List[SimpleNamespace]:
    return [_task(d) for d in _get("/tasks")]


def create_task(name="", account_id=None, group_id=None,
                message_text="", cron_expr="",
                timezone="Asia/Shanghai", media_path=None) -> SimpleNamespace:
    data = _post("/tasks", json={
        "name": name, "account_id": account_id, "group_id": group_id,
        "message_text": message_text, "cron_expr": cron_expr,
        "timezone": timezone, "media_path": media_path,
    })
    return _task(data)


def toggle_task(task_id: int, active: bool):
    _put(f"/tasks/{task_id}/toggle", params={"active": active})


def switch_task_account(task_id: int, new_account_id: int, reason: str = "手动更换") -> SimpleNamespace:
    data = _put(f"/tasks/{task_id}/account",
                json={"new_account_id": new_account_id, "reason": reason})
    return _task(data)


def delete_task(task_id: int):
    _delete(f"/tasks/{task_id}")


def get_server_job_count() -> int:
    try:
        return _get("/health", timeout=5)["jobs"]
    except Exception:
        return -1
