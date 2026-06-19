from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(default="", description="任务备注名")
    account_id: int = Field(foreign_key="accounts.id")
    group_id: int = Field(foreign_key="groups.id")

    message_text: str = Field(description="消息内容")
    media_path: Optional[str] = None        # 本地图片/文件路径（可选）

    # cron 表达式，如 "0 9 * * *" = 每天早上9点
    cron_expr: str = Field(description="cron表达式")
    timezone: str = Field(default="Asia/Shanghai")

    owner: str = Field(default="默认")       # 归属分组，继承自创建时使用的账号，约束自动换号范围

    is_active: bool = Field(default=True)
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = Field(default=0)
    fail_count: int = Field(default=0)
    last_error: Optional[str] = None        # 最近一次失败的原因
    account_history: Optional[str] = None   # JSON: [{time, account_id, old_account_id, reason}]
    created_at: datetime = Field(default_factory=datetime.now)
