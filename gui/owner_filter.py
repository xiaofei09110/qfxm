"""
owner_filter.py — 账号归属分组筛选器（全局共享状态）

GUI 各标签页通过此模块读写当前激活的归属分组过滤条件。
空字符串表示"显示全部"，非空表示只显示/操作该分组的账号。
"""

_current_owner: str = ""


def get_owner_filter() -> str:
    return _current_owner


def set_owner_filter(owner: str):
    global _current_owner
    _current_owner = owner
