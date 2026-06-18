"""
client_manager.py
所有 Telethon 操作必须在同一个事件循环里执行。
这里用一个永久后台线程持有唯一的事件循环，
其他线程（QThread、主线程）通过 run_async() 提交协程并等待结果。
"""
import asyncio
import logging
import sqlite3
import threading
from typing import Dict, Optional, Tuple

from telethon import TelegramClient
from telethon.sessions import MemorySession
from telethon.crypto import AuthKey
from telethon.errors import (
    AuthKeyUnregisteredError,
    AuthKeyDuplicatedError,
    UserDeactivatedError,
    FloodWaitError,
    SessionPasswordNeededError,
)

from models.account import Account

logger = logging.getLogger(__name__)


# ── 全局唯一事件循环，运行在独立后台线程 ──────────────────────────
_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
_loop_thread: threading.Thread = None


def _start_loop():
    global _loop_thread
    def _run():
        asyncio.set_event_loop(_loop)
        _loop.run_forever()
    _loop_thread = threading.Thread(target=_run, daemon=True, name="TelegramLoop")
    _loop_thread.start()


def run_async(coro, timeout: int = 60):
    """从任意线程提交协程到专用事件循环，阻塞等待结果。"""
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=timeout)


# ── 辅助函数 ──────────────────────────────────────────────────────

def _load_session(session_path: str) -> MemorySession:
    """读取修改版 Telethon session（含额外 tmp_auth_key 列），绕过列数校验。"""
    conn = sqlite3.connect(session_path)
    row = conn.execute(
        "SELECT dc_id, server_address, port, auth_key FROM sessions"
    ).fetchone()
    conn.close()
    if not row:
        raise ValueError(f"session 文件无数据: {session_path}")
    dc_id, server_address, port, auth_key_bytes = row
    mem = MemorySession()
    mem.set_dc(dc_id, server_address, port)
    mem.auth_key = AuthKey(auth_key_bytes)
    return mem


def _build_proxy(account: Account) -> Optional[tuple]:
    if not account.proxy_host:
        return None
    try:
        import socks
        type_map = {"socks5": socks.SOCKS5, "socks4": socks.SOCKS4, "http": socks.HTTP}
        proxy_type = type_map.get((account.proxy_type or "socks5").lower(), socks.SOCKS5)
        return (proxy_type, account.proxy_host, account.proxy_port,
                True, account.proxy_user, account.proxy_pass)
    except ImportError:
        return None


# ── 客户端管理器 ──────────────────────────────────────────────────

class ClientManager:
    def __init__(self):
        self._clients: Dict[int, TelegramClient] = {}

    def _make_client(self, account: Account) -> TelegramClient:
        session = _load_session(account.session_path)
        return TelegramClient(
            session=session,
            api_id=account.app_id,
            api_hash=account.app_hash,
            device_model=account.device_model or "Desktop",
            app_version=account.app_version or "4.0.0",
            system_version="Windows 10",
            lang_code=account.system_lang or "en",
            system_lang_code=account.system_lang or "en",
            proxy=_build_proxy(account),
            receive_updates=False,
        )

    async def _connect_async(self, account: Account) -> Tuple[Optional[TelegramClient], str, Optional[object]]:
        client = self._make_client(account)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                logger.warning("Session 未授权: %s", account.phone)
                await client.disconnect()
                return None, "invalid", None

            me = await client.get_me()
            logger.info("连接成功: +%s %s", me.phone, me.first_name or "")
            self._clients[account.id] = client
            return client, "active", me

        except AuthKeyUnregisteredError:
            logger.warning("Session 已失效: %s", account.phone)
            return None, "invalid", None
        except AuthKeyDuplicatedError:
            logger.warning("Session 被多地同时使用: %s", account.phone)
            return None, "restricted", None
        except UserDeactivatedError:
            logger.warning("账号已注销: %s", account.phone)
            return None, "banned", None
        except FloodWaitError as e:
            logger.warning("FloodWait %ds: %s", e.seconds, account.phone)
            return None, "flood", None
        except Exception as e:
            logger.error("连接异常 %s: %s", account.phone, e)
            return None, "error", None

    def connect_account(self, account: Account) -> Tuple[Optional[TelegramClient], str, Optional[object]]:
        return run_async(self._connect_async(account))

    def get_client(self, account_id: int) -> Optional[TelegramClient]:
        return self._clients.get(account_id)

    def is_connected(self, account_id: int) -> bool:
        c = self._clients.get(account_id)
        return c is not None and c.is_connected()

    async def _get_entity_async(self, account_id: int, group: str):
        client = self._clients.get(account_id)
        if not client:
            raise ValueError(f"账号 {account_id} 未连接")
        return await client.get_entity(group)

    def get_entity(self, account_id: int, group: str):
        """从任意线程安全地获取群组实体。"""
        return run_async(self._get_entity_async(account_id, group))

    def disconnect_account(self, account_id: int):
        async def _stop():
            c = self._clients.pop(account_id, None)
            if c:
                try:
                    await c.disconnect()
                except Exception:
                    pass
        run_async(_stop())

    def disconnect_all(self):
        async def _stop_all():
            for c in list(self._clients.values()):
                try:
                    await c.disconnect()
                except Exception:
                    pass
            self._clients.clear()
        run_async(_stop_all())


client_manager = ClientManager()
_start_loop()
