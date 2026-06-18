"""
dev_watch.py — 本地开发自动同步工具
监听代码改动 → 自动 git commit + push → SSH 服务器 git pull + restart

用法：
  python dev_watch.py

依赖 .env 中以下变量（在服务器 .env 不需要填）：
  SSH_HOST=43.165.173.63
  SSH_USER=ubuntu
  SSH_PASSWORD=你的服务器密码   ← 填密码
  SSH_KEY_PATH=                 ← 或填私钥路径，两者选一
"""
import os
import sys
import time
import subprocess
import logging
from datetime import datetime
from threading import Timer

from dotenv import load_dotenv
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

load_dotenv()

SSH_HOST     = os.getenv("SSH_HOST", "43.165.173.63")
SSH_USER     = os.getenv("SSH_USER", "ubuntu")
SSH_PASSWORD = os.getenv("SSH_PASSWORD", "")
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH", "")
SSH_PORT     = int(os.getenv("SSH_PORT", "22"))
REMOTE_DIR   = os.getenv("REMOTE_DIR", "/home/ubuntu/qfxm")
SERVICE_NAME = os.getenv("SERVICE_NAME", "qfxm")

WATCH_DIR    = os.path.dirname(os.path.abspath(__file__))
DEBOUNCE_SEC = 5  # 最后一次改动后等待 5 秒再触发

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


def _run(cmd: str) -> tuple[int, str, str]:
    result = subprocess.run(
        cmd, shell=True, cwd=WATCH_DIR,
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def git_push() -> bool:
    logger.info("检测到代码改动，开始提交...")

    rc, out, _ = _run("git status --porcelain")
    if rc != 0 or not out:
        logger.info("没有需要提交的改动，跳过。")
        return False

    _run("git add -A")
    msg = f"auto: {datetime.now().strftime('%m-%d %H:%M')} 自动同步"
    rc, out, err = _run(f'git commit -m "{msg}"')
    if rc != 0:
        logger.error("git commit 失败: %s", err)
        return False
    logger.info("git commit: %s", out.split("\n")[0])

    rc, out, err = _run("git push")
    if rc != 0:
        logger.error("git push 失败: %s", err)
        return False
    logger.info("git push 成功")
    return True


def ssh_deploy():
    try:
        import paramiko
    except ImportError:
        logger.error("请安装 paramiko: pip install paramiko")
        return

    if not SSH_HOST or (not SSH_PASSWORD and not SSH_KEY_PATH):
        logger.warning("未配置 SSH_HOST / SSH_PASSWORD / SSH_KEY_PATH，跳过服务器部署")
        return

    logger.info("正在 SSH 连接服务器 %s 部署...", SSH_HOST)
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if SSH_KEY_PATH and os.path.exists(SSH_KEY_PATH):
            client.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER,
                           key_filename=SSH_KEY_PATH, timeout=15)
        else:
            client.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER,
                           password=SSH_PASSWORD, timeout=15)

        cmd = f"cd {REMOTE_DIR} && git pull && sudo systemctl restart {SERVICE_NAME}"
        _, stdout, stderr = client.exec_command(cmd, timeout=60)
        out = stdout.read().decode().strip()
        err = stderr.read().decode().strip()
        client.close()

        if out:
            logger.info("服务器输出: %s", out)
        if err:
            logger.info("服务器信息: %s", err)
        logger.info("服务器部署完成 ✓")
    except Exception as e:
        logger.error("SSH 部署失败: %s", e)


def sync():
    pushed = git_push()
    if pushed:
        ssh_deploy()
    else:
        logger.info("无新提交，不触发部署。")


class ChangeHandler(FileSystemEventHandler):
    def __init__(self):
        self._timer: Timer | None = None

    def _schedule(self):
        if self._timer:
            self._timer.cancel()
        self._timer = Timer(DEBOUNCE_SEC, sync)
        self._timer.daemon = True
        self._timer.start()

    def on_modified(self, event):
        if not event.is_directory and not _should_ignore(event.src_path):
            logger.debug("改动: %s", event.src_path)
            self._schedule()

    def on_created(self, event):
        if not _should_ignore(event.src_path):
            self._schedule()

    def on_deleted(self, event):
        if not _should_ignore(event.src_path):
            self._schedule()


def main():
    logger.info("=" * 50)
    logger.info("QFXM 自动同步工具 启动")
    logger.info("监听目录: %s", WATCH_DIR)
    logger.info("防抖延迟: %d 秒", DEBOUNCE_SEC)
    logger.info("服务器: %s@%s", SSH_USER, SSH_HOST)
    if not SSH_PASSWORD and not SSH_KEY_PATH:
        logger.warning("⚠ 未配置 SSH 凭据，自动部署将跳过。请在 .env 中设置 SSH_PASSWORD 或 SSH_KEY_PATH")
    logger.info("=" * 50)

    handler = ChangeHandler()
    observer = Observer()
    observer.schedule(handler, WATCH_DIR, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("收到退出信号，停止监听。")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
