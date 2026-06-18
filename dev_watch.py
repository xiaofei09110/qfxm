"""
dev_watch.py — 本地代码自动提交工具
监听代码改动 → 自动 git commit + push
服务器侧由 qfxm-update.timer 检测到新提交后自动 pull + restart

用法：在 VSCode 终端运行 python dev_watch.py
"""
import os
import sys
import time
import subprocess
import logging
from datetime import datetime
from threading import Timer

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCH_DIR    = os.path.dirname(os.path.abspath(__file__))
DEBOUNCE_SEC = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

IGNORE_PATTERNS = {
    "__pycache__", ".git", "logs", "sessions",
    ".env", "qfxm.db", ".pyc",
}


def _should_ignore(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return any(ig in parts or path.endswith(ig) for ig in IGNORE_PATTERNS)


def _run(cmd: str) -> tuple:
    result = subprocess.run(
        cmd, shell=True, cwd=WATCH_DIR,
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def git_push():
    rc, out, _ = _run("git status --porcelain")
    if rc != 0 or not out:
        return

    logger.info("检测到改动，正在提交...")
    _run("git add -A")
    msg = f"auto: {datetime.now().strftime('%m-%d %H:%M')} 自动同步"
    rc, out, err = _run(f'git commit -m "{msg}"')
    if rc != 0:
        logger.error("git commit 失败: %s", err)
        return
    logger.info("已提交: %s", out.split("\n")[0])

    rc, _, err = _run("git push")
    if rc != 0:
        logger.error("git push 失败: %s", err)
        return
    logger.info("已推送到 GitHub，服务器将在 60 秒内自动检测并部署")


class ChangeHandler(FileSystemEventHandler):
    def __init__(self):
        self._timer: Timer | None = None

    def _schedule(self):
        if self._timer:
            self._timer.cancel()
        self._timer = Timer(DEBOUNCE_SEC, git_push)
        self._timer.daemon = True
        self._timer.start()

    def on_modified(self, event):
        if not event.is_directory and not _should_ignore(event.src_path):
            self._schedule()

    def on_created(self, event):
        if not _should_ignore(event.src_path):
            self._schedule()

    def on_deleted(self, event):
        if not _should_ignore(event.src_path):
            self._schedule()


def main():
    logger.info("=" * 50)
    logger.info("QFXM 自动提交工具 启动")
    logger.info("监听目录: %s", WATCH_DIR)
    logger.info("防抖延迟: %d 秒 | 服务器检测间隔: 60 秒", DEBOUNCE_SEC)
    logger.info("=" * 50)

    handler = ChangeHandler()
    observer = Observer()
    observer.schedule(handler, WATCH_DIR, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("已停止监听")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
