from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field


class Account(SQLModel, table=True):
    __tablename__ = "accounts"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(default="", description="账号备注名")
    phone: Optional[str] = Field(default=None, unique=True, description="手机号")
    session_path: str = Field(unique=True, description="session文件绝对路径")
    session_type: str = Field(default="telethon", description="telethon")

    # 每个协议号有自己的 API 凭据（从 JSON 读取）
    app_id: int = Field(default=2040)
    app_hash: str = Field(default="b18441a1ff607e10a989891a5462e627")
    two_fa: Optional[str] = None       # 2FA 密码（从 json/2fa.txt 读取）

    # 设备信息（用于伪装，从 JSON 读取）
    device_model: Optional[str] = None
    app_version: Optional[str] = None
    system_lang: Optional[str] = None

    # 账号信息
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    user_id: Optional[int] = None
    is_premium: bool = Field(default=False)
    spamblock: Optional[str] = None    # None = 正常

    # 状态: unknown / active / restricted / banned / flood / invalid
    status: str = Field(default="unknown")
    last_checked: Optional[datetime] = None
    error_msg: Optional[str] = None
    is_resting: bool = Field(default=False)  # 养号中，暂不参与任务分配
    owner: str = Field(default="默认")       # 归属分组标签，用于多人共用服务器时隔离账号

    # 代理（可选）
    proxy_type: Optional[str] = None
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = None
    proxy_user: Optional[str] = None
    proxy_pass: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.now)
