"""
main_window.py
PyQt5 主窗口，包含三个 Tab：账号管理、群组管理、定时任务。
"""
import logging
from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QLabel, QAction, QMenuBar,
)
from PyQt5.QtCore import Qt, QTimer

from gui.tabs.account_tab import AccountTab
from gui.tabs.group_tab import GroupTab
from gui.tabs.task_tab import TaskTab
import core.scheduler as scheduler

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QFXM — Telegram 多账号群控")
        self.setMinimumSize(1000, 650)

        self._build_menu()
        self._build_tabs()
        self._build_statusbar()

        # 每30秒刷新任务Tab（更新下次执行时间显示）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer)
        self._timer.start(30_000)

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
        self.group_tab = GroupTab()
        self.task_tab = TaskTab()

        self.tabs.addTab(self.account_tab, "账号管理")
        self.tabs.addTab(self.group_tab, "群组管理")
        self.tabs.addTab(self.task_tab, "定时任务")
        self.setCentralWidget(self.tabs)

    def _build_statusbar(self):
        self.statusBar().showMessage("就绪")
        self._scheduler_label = QLabel("调度器: 运行中")
        self.statusBar().addPermanentWidget(self._scheduler_label)

    def _on_timer(self):
        if scheduler._scheduler.running:
            jobs = len(scheduler.list_jobs())
            self._scheduler_label.setText(f"调度器: 运行中 | 活跃任务: {jobs}")
        else:
            self._scheduler_label.setText("调度器: 已停止")
        # 刷新任务列表的下次执行时间
        self.task_tab.refresh_table()

    def _open_dev_doc(self):
        import os, subprocess
        doc_path = os.path.abspath("DEVELOPMENT.md")
        if os.path.exists(doc_path):
            os.startfile(doc_path)

    def closeEvent(self, event):
        scheduler.stop()
        from core.client_manager import client_manager
        client_manager.disconnect_all()
        logger.info("程序正常退出")
        event.accept()
