from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field


class Group(SQLModel, table=True):
    __tablename__ = "groups"

    id: Optional[int] = Field(default=None, primary_key=True)
    tg_id: str = Field(unique=True, description="Telegram 群组 ID（字符串）")
    username: Optional[str] = None          # @xxx 用户名
    title: Optional[str] = None             # 群组标题
    account_id: int = Field(foreign_key="accounts.id", description="用于进入该群的账号")

    joined_at: Optional[datetime] = None
    can_send: bool = Field(default=True, description="是否能发言")
    needs_verify: bool = Field(default=False, description="是否需要人机验证")
    created_at: datetime = Field(default_factory=datetime.now)
