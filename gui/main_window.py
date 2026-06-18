"""
main_window.py
PyQt5 主窗口。本地模式显示本地调度器状态；远程模式显示服务器状态。
"""
import importlib
import logging
from PyQt5.QtWidgets import QMainWindow, QTabWidget, QStatusBar, QLabel, QAction, QMessageBox
from PyQt5.QtCore import QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QShortcut

from gui.tabs.account_tab import AccountTab
from gui.tabs.group_tab import GroupTab
from gui.tabs.task_tab import TaskTab
from config import SERVER_URL

logger = logging.getLogger(__name__)


class ServerStatusWorker(QThread):
    finished = pyqtSignal(int)  # job count, -1 for error

    def run(self):
        try:
            from api_client import get_server_job_count
            self.finished.emit(get_server_job_count())
        except Exception:
            self.finished.emit(-1)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QFXM — Telegram 多账号群控")
        self.setMinimumSize(1000, 650)

        self._build_menu()
        self._build_tabs()
        self._build_statusbar()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer)
        self._timer.start(30_000)

        f5 = QShortcut(QKeySequence("F5"), self)
        f5.activated.connect(self._reload_tabs)

    def _build_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = menubar.addMenu("帮助")
        doc_action = QAction("开发文档", self)
        doc_action.triggered.connect(self._open_dev_doc)
        help_menu.addAction(doc_action)

    def _build_tabs(self):
        self.tabs = QTabWidget()
        self.account_tab = AccountTab()
        self.group_tab   = GroupTab()
        self.task_tab    = TaskTab()
        self.tabs.addTab(self.account_tab, "账号管理")
        self.tabs.addTab(self.group_tab,   "群组管理")
        self.tabs.addTab(self.task_tab,    "定时任务")
        self.setCentralWidget(self.tabs)

    def _build_statusbar(self):
        self.statusBar().showMessage("就绪")
        self._refresh_label = QLabel()
        self._refresh_label.setStyleSheet("color: #888; padding-right: 16px;")
        self.statusBar().addPermanentWidget(self._refresh_label)
        self._server_label = QLabel()
        self.statusBar().addPermanentWidget(self._server_label)
        self._update_server_label()
        self._update_refresh_label()

    def _update_server_label(self):
        if SERVER_URL:
            if hasattr(self, '_status_worker') and self._status_worker.isRunning():
                return
            self._status_worker = ServerStatusWorker()
            self._status_worker.finished.connect(self._on_server_status)
            self._status_worker.start()
        else:
            import core.scheduler as scheduler
            if scheduler._scheduler.running:
                jobs = len(scheduler.list_jobs())
                self._server_label.setText(f"本地模式 | 活跃任务: {jobs}")
                self._server_label.setStyleSheet("")
            else:
                self._server_label.setText("本地模式 | 调度器已停止")
                self._server_label.setStyleSheet("color: #F44336;")

    def _on_server_status(self, jobs):
        if jobs >= 0:
            self._server_label.setText(f"服务器模式 | 活跃任务: {jobs}")
            self._server_label.setStyleSheet("color: #4CAF50;")
        else:
            self._server_label.setText("服务器模式 | 连接失败")
            self._server_label.setStyleSheet("color: #F44336;")

    def _update_refresh_label(self):
        from datetime import datetime
        self._refresh_label.setText(f"数据更新: {datetime.now().strftime('%H:%M:%S')}")

    def _on_timer(self):
        self._update_server_label()
        self.task_tab.refresh_table()
        self._update_refresh_label()

    def _reload_tabs(self):
        current_index = self.tabs.currentIndex()
        try:
            import api_client
            import gui.tabs.account_tab as m1
            import gui.tabs.group_tab   as m2
            import gui.tabs.task_tab    as m3
            import services.proxy       as mp
            importlib.reload(api_client)
            importlib.reload(mp)
            importlib.reload(m1)
            importlib.reload(m2)
            importlib.reload(m3)

            self.tabs.clear()
            self.account_tab = m1.AccountTab()
            self.group_tab   = m2.GroupTab()
            self.task_tab    = m3.TaskTab()
            self.tabs.addTab(self.account_tab, "账号管理")
            self.tabs.addTab(self.group_tab,   "群组管理")
            self.tabs.addTab(self.task_tab,    "定时任务")
            self.tabs.setCurrentIndex(current_index)
            self._update_refresh_label()
            self.statusBar().showMessage("界面已重载", 3000)
            logger.info("F5 重载界面成功")
        except Exception as e:
            logger.error("F5 重载失败: %s", e)
            QMessageBox.critical(self, "重载失败", f"代码有错误，重载失败：\n{e}")

    def _open_dev_doc(self):
        import os
        doc_path = os.path.abspath("DEVELOPMENT.md")
        if os.path.exists(doc_path):
            os.startfile(doc_path)

    def closeEvent(self, event):
        if not SERVER_URL:
            import core.scheduler as scheduler
            scheduler.stop()
            from core.client_manager import client_manager
            client_manager.disconnect_all()
        logger.info("程序正常退出")
        event.accept()
