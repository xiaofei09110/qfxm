"""
proxy.py — 本地/远程模式切换
GUI 层统一从此模块导入，不直接引用 service 或 api_client。
SERVER_URL 非空 → 远程模式（调用服务器 API）
SERVER_URL 为空  → 本地模式（调用本地 service）
"""
from config import SERVER_URL

IS_REMOTE: bool = bool(SERVER_URL)

if IS_REMOTE:
    # ── 远程模式 ──────────────────────────────────────────────────────
    from api_client import (
        list_accounts,
        import_from_parent_folder,
        import_from_folders,
        batch_check_status,
        verify_account_spambot,
        delete_account,
        list_groups,
        resolve_group_info,
        add_group,
        delete_group,
        list_tasks,
        create_task,
        toggle_task,
        delete_task,
        switch_task_account,
        batch_update_profiles_remote,
    )

    def batch_update_profiles_gui(selected_ids: list, **vals) -> dict:
        return batch_update_profiles_remote(selected_ids, **vals)

else:
    # ── 本地模式 ──────────────────────────────────────────────────────
    from services.account_service import (       # noqa
        list_accounts,
        import_from_parent_folder,
        import_from_folders,
        batch_check_status,
        delete_account,
    )
    from services.verification_service import verify_account as verify_account_spambot  # noqa
    from services.group_service import (         # noqa
        list_groups,
        add_group,
        delete_group,
        list_tasks,
        create_task,
        toggle_task,
        delete_task,
        switch_task_account,
        resolve_group_info,
    )

    def batch_update_profiles_gui(selected_ids: list, **vals) -> dict:
        from core.client_manager import client_manager, run_async
        from core.profile_manager import batch_update_profiles
        clients = [
            (aid, client_manager.get_client(aid))
            for aid in selected_ids
            if client_manager.get_client(aid)
        ]
        if not clients:
            return {}
        return run_async(batch_update_profiles(clients, **vals))
