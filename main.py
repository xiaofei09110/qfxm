"""
main.py — 程序唯一入口
用法:
  python main.py           # 启动 GUI 桌面应用
  python main.py --no-gui  # 无界面模式（服务器部署）
"""
import os
import sys
import asyncio
import logging
import argparse

# Windows 需要 SelectorEventLoop，否则后台线程里创建事件循环会崩溃
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 必须在 FileHandler 之前创建 logs/ 目录
os.makedirs("logs", exist_ok=True)

# 配置日志（写文件 + 控制台）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/qfxm.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="QFXM Telegram 多账号群控")
    parser.add_argument("--no-gui", action="store_true", help="无界面模式，仅运行调度器")
    args = parser.parse_args()

    # 初始化数据库
    from database import init_db
    init_db()

    # 启动调度器
    import core.scheduler as scheduler
    scheduler.start()

    # 恢复数据库中的历史任务
    from services.group_service import restore_all_tasks
    restore_all_tasks()

    if args.no_gui:
        # 服务器模式：持续运行，等待 Ctrl+C
        logger.info("无界面模式启动，调度器运行中。按 Ctrl+C 退出。")
        try:
            import time
            while True:
                time.sleep(60)
                jobs = scheduler.list_jobs()
                logger.info("心跳检测：当前活跃任务数 %d", len(jobs))
        except KeyboardInterrupt:
            logger.info("收到退出信号")
        finally:
            scheduler.stop()
            from core.client_manager import client_manager
            client_manager.disconnect_all()
    else:
        # GUI 模式
        from PyQt5.QtWidgets import QApplication
        from gui.main_window import MainWindow

        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        app.setApplicationName("QFXM")

        window = MainWindow()
        window.show()

        exit_code = app.exec_()
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
