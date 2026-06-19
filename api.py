"""
api.py — 服务端 FastAPI 接口
启动方式：python main.py --no-gui --api
客户端 PyQt5 通过 HTTP 调用此接口完成所有操作。
"""
import io
import os
import shutil
import tempfile
import zipfile
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import API_KEY
from services.account_service import (
    batch_check_status,
    check_account_status,
    delete_account,
    import_from_folders,
    list_accounts,
)
from services.group_service import (
    add_group,
    create_task,
    delete_task,
    list_groups,
    list_tasks,
    resolve_group_info,
    toggle_task,
)
import core.scheduler as scheduler

app = FastAPI(title="QFXM API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _auth(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ── 健康检测 ──────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "jobs": len(scheduler.list_jobs())}



# ── 账号 ──────────────────────────────────────────────────────────────

@app.get("/accounts")
def get_accounts(_=Depends(_auth)):
    return jsonable_encoder(list_accounts())


@app.post("/accounts/upload")
async def upload_account(file: UploadFile = File(...), _=Depends(_auth)):
    """
    客户端把协议号文件夹打成 zip 上传，服务端解压并导入。
    zip 内结构：手机号文件夹/（phone.session + phone.json + 2fa.txt）
    """
    content = await file.read()
    tmpdir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            zf.extractall(tmpdir)
        folders = [
            os.path.join(tmpdir, name)
            for name in os.listdir(tmpdir)
            if os.path.isdir(os.path.join(tmpdir, name)) and name.isdigit()
        ]
        if not folders:
            raise HTTPException(400, "zip 内未找到账号文件夹（应以手机号命名）")
        results = import_from_folders(folders)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return results


@app.post("/accounts/{account_id}/check")
def check_one(account_id: int, _=Depends(_auth)):
    """验证单个账号状态（服务端连接 Telegram）。"""
    status = check_account_status(account_id)
    return {"id": account_id, "status": status}


@app.delete("/accounts/{account_id}")
def remove_account(account_id: int, _=Depends(_auth)):
    delete_account(account_id)
    return {"ok": True}


class RestingRequest(BaseModel):
    account_ids: List[int]
    resting: bool = True


@app.post("/accounts/resting")
def set_resting_ep(req: RestingRequest, _=Depends(_auth)):
    from services.account_service import set_accounts_resting
    set_accounts_resting(req.account_ids, req.resting)
    return {"ok": True}


@app.post("/tasks/auto_reassign")
def auto_reassign_ep(_=Depends(_auth)):
    from services.group_service import batch_auto_reassign
    return batch_auto_reassign()


@app.post("/accounts/{account_id}/verify")
def spambot_verify_ep(account_id: int, _=Depends(_auth)):
    """让账号自动与 @SpamBot 交互完成申诉流程。"""
    from services.verification_service import verify_account
    result = verify_account(account_id)
    return {"message": result}


class GroupVerifyRequest(BaseModel):
    account_id: int


@app.post("/groups/{group_id}/verify")
def group_verify_ep(group_id: int, req: GroupVerifyRequest, _=Depends(_auth)):
    """用指定账号自动完成群组入群验证（点击 bot 验证按钮）。"""
    from services.verification_service import verify_group_join
    result = verify_group_join(req.account_id, group_id)
    return {"message": result}


class ProfileRequest(BaseModel):
    account_ids: List[int]
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    bio: Optional[str] = None
    photo_path: Optional[str] = None   # 服务端本地路径


@app.post("/accounts/profile")
def update_profiles(req: ProfileRequest, _=Depends(_auth)):
    from core.client_manager import client_manager, run_async
    from core.profile_manager import batch_update_profiles

    clients = [
        (aid, client_manager.get_client(aid))
        for aid in req.account_ids
        if client_manager.get_client(aid)
    ]
    if not clients:
        raise HTTPException(400, "选中账号均未连接，请先验证账号")

    results = run_async(
        batch_update_profiles(
            clients,
            first_name=req.first_name,
            last_name=req.last_name,
            bio=req.bio,
            photo_path=req.photo_path,
        ),
        timeout=300,
    )
    return {"results": {str(k): v for k, v in results.items()}}


@app.post("/upload/media")
async def upload_media(file: UploadFile = File(...), _=Depends(_auth)):
    """上传头像等媒体文件到服务端，返回服务端路径供后续 profile 接口使用。"""
    media_dir = "media"
    os.makedirs(media_dir, exist_ok=True)
    dest = os.path.join(media_dir, file.filename)
    with open(dest, "wb") as f:
        f.write(await file.read())
    return {"path": os.path.abspath(dest)}


# ── 群组 ──────────────────────────────────────────────────────────────

@app.get("/groups")
def get_groups(_=Depends(_auth)):
    return jsonable_encoder(list_groups())


class ResolveGroupRequest(BaseModel):
    account_id: int
    group_input: str


@app.post("/groups/resolve")
def resolve_group(req: ResolveGroupRequest, _=Depends(_auth)):
    """解析群组 @username 或数字 ID，返回真实 ID 和标题。"""
    info = resolve_group_info(req.account_id, req.group_input)
    if not info:
        raise HTTPException(400, "无法解析群组信息，请确认账号已连接且群组 ID 正确")
    return info


class SaveGroupRequest(BaseModel):
    account_id: int
    tg_id: str
    username: str = ""
    title: str = ""


@app.post("/groups/save")
def save_group(req: SaveGroupRequest, _=Depends(_auth)):
    group = add_group(
        account_id=req.account_id,
        tg_id=req.tg_id,
        username=req.username,
        title=req.title,
    )
    return jsonable_encoder(group)


@app.put("/groups/{group_id}/clear_verify", dependencies=[Depends(_auth)])
def clear_verify_ep(group_id: int):
    """手动清除群组的 needs_verify 标记。"""
    from database import get_session
    from models.group import Group
    with get_session() as db:
        group = db.get(Group, group_id)
        if not group:
            raise HTTPException(404, "群组不存在")
        group.needs_verify = False
        db.add(group)
        db.commit()
    return {"ok": True}


@app.delete("/groups/{group_id}", dependencies=[Depends(_auth)])
def remove_group(group_id: int):
    from services.group_service import delete_group
    delete_group(group_id)
    return {"status": "ok"}


# ── 定时任务 ──────────────────────────────────────────────────────────

@app.get("/tasks")
def get_tasks(_=Depends(_auth)):
    tasks = list_tasks()
    result = []
    for t in tasks:
        d = jsonable_encoder(t)
        next_run = scheduler.get_next_run(t.id)
        d["next_run_str"] = next_run.strftime("%m-%d %H:%M") if next_run else None
        result.append(d)
    return result


class CreateTaskRequest(BaseModel):
    name: str = ""
    account_id: int
    group_id: int
    message_text: str
    cron_expr: str
    timezone: str = "Asia/Shanghai"
    media_path: Optional[str] = None


@app.post("/tasks")
def create_task_ep(req: CreateTaskRequest, _=Depends(_auth)):
    task = create_task(**req.dict())
    d = jsonable_encoder(task)
    next_run = scheduler.get_next_run(task.id)
    d["next_run_str"] = next_run.strftime("%m-%d %H:%M") if next_run else None
    return d


@app.put("/tasks/{task_id}/toggle")
def toggle(task_id: int, active: bool, _=Depends(_auth)):
    toggle_task(task_id, active)
    return {"ok": True}


class SwitchAccountRequest(BaseModel):
    new_account_id: int
    reason: str = "手动更换"


@app.put("/tasks/{task_id}/account")
def switch_account_ep(task_id: int, req: SwitchAccountRequest, _=Depends(_auth)):
    from services.group_service import switch_task_account
    task = switch_task_account(task_id, req.new_account_id, req.reason)
    d = jsonable_encoder(task)
    next_run = scheduler.get_next_run(task.id)
    d["next_run_str"] = next_run.strftime("%m-%d %H:%M") if next_run else None
    return d


class UpdateCronRequest(BaseModel):
    cron_expr: str


@app.put("/tasks/{task_id}/cron")
def update_cron_ep(task_id: int, req: UpdateCronRequest, _=Depends(_auth)):
    from services.group_service import update_task_cron
    task = update_task_cron(task_id, req.cron_expr)
    d = jsonable_encoder(task)
    next_run = scheduler.get_next_run(task.id)
    d["next_run_str"] = next_run.strftime("%m-%d %H:%M") if next_run else None
    return d


@app.delete("/tasks/{task_id}")
def remove_task(task_id: int, _=Depends(_auth)):
    delete_task(task_id)
    return {"ok": True}
