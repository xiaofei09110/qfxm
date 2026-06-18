"""
account_tab.py
账号管理界面。
支持两种导入方式：
  1. 选择父文件夹（如 D:\桌面\协议号\）→ 自动扫描全部协议号
  2. 选择单个/多个协议号文件夹 → 逐个导入
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QFileDialog, QLabel, QHeaderView, QMessageBox,
    QProgressBar, QDialog, QFormLayout, QLineEdit, QDialogButtonBox,
)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QColor

from services.account_service import (
    import_from_parent_folder, import_from_folders,
    batch_check_status, list_accounts, delete_account,
)
from core.client_manager import client_manager
from core.profile_manager import batch_update_profiles


STATUS_COLORS = {
    "active":      "#4CAF50",
    "restricted":  "#FF9800",
    "banned":      "#F44336",
    "flood":       "#9C27B0",
    "invalid":     "#F44336",
    "needs_2fa":   "#FF9800",
    "unknown":     "#9E9E9E",
    "error":       "#F44336",
}

STATUS_LABELS = {
    "active":      "正常",
    "restricted":  "多地登录",
    "banned":      "封号",
    "flood":       "限速",
    "invalid":     "失效",
    "needs_2fa":   "需2FA",
    "unknown":     "未检测",
    "error":       "错误",
}


class CheckWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal()

    def __init__(self, account_ids):
        super().__init__()
        self.account_ids = account_ids

    def run(self):
        results = batch_check_status(self.account_ids)
        for aid, status in results:
            self.progress.emit(aid, status)
        self.finished.emit()


class ProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量修改账号资料")
        self.setMinimumWidth(420)
        layout = QFormLayout(self)

        self.first_name = QLineEdit()
        self.last_name = QLineEdit()
        self.bio = QLineEdit()
        self.photo_path = QLineEdit()
        photo_btn = QPushButton("选择图片")
        photo_btn.clicked.connect(self._pick_photo)

        photo_row = QHBoxLayout()
        photo_row.addWidget(self.photo_path)
        photo_row.addWidget(photo_btn)

        layout.addRow("名字:", self.first_name)
        layout.addRow("姓氏:", self.last_name)
        layout.addRow("个人简介:", self.bio)
        layout.addRow("头像图片:", photo_row)

        tip = QLabel("留空的字段不会修改")
        tip.setStyleSheet("color: gray; font-size: 11px;")
        layout.addRow(tip)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _pick_photo(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择头像", "", "图片 (*.jpg *.png *.jpeg)")
        if path:
            self.photo_path.setText(path)

    def get_values(self):
        return {
            "first_name": self.first_name.text().strip() or None,
            "last_name": self.last_name.text().strip() or None,
            "bio": self.bio.text().strip() or None,
            "photo_path": self.photo_path.text().strip() or None,
        }


class AccountTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 导入区域
        import_label = QLabel("导入协议号：")
        import_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(import_label)

        import_row = QHBoxLayout()
        self.btn_import_folder = QPushButton("选择整个协议号文件夹（推荐）")
        self.btn_import_folder.setToolTip("选择包含所有协议号子文件夹的父目录，如 D:\\桌面\\协议号\\")
        self.btn_import_single = QPushButton("选择单个/多个协议号")
        self.btn_import_single.setToolTip("手动选择一个或多个以手机号命名的文件夹")
        import_row.addWidget(self.btn_import_folder)
        import_row.addWidget(self.btn_import_single)
        import_row.addStretch()
        layout.addLayout(import_row)

        # 操作区域
        btn_row = QHBoxLayout()
        self.btn_check_selected = QPushButton("验证选中账号")
        self.btn_check_all = QPushButton("验证全部账号")
        self.btn_profile = QPushButton("批量改资料")
        self.btn_delete = QPushButton("删除选中")
        self.btn_refresh = QPushButton("刷新列表")
        for btn in [self.btn_check_selected, self.btn_check_all,
                    self.btn_profile, self.btn_delete, self.btn_refresh]:
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # 表格
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "ID", "手机号", "名字", "状态", "SpamBlock", "2FA", "Premium", "最后检测"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        # 信号连接
        self.btn_import_folder.clicked.connect(self._on_import_folder)
        self.btn_import_single.clicked.connect(self._on_import_single)
        self.btn_check_selected.clicked.connect(self._on_check_selected)
        self.btn_check_all.clicked.connect(self._on_check_all)
        self.btn_profile.clicked.connect(self._on_profile)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_refresh.clicked.connect(self.refresh_table)

    def refresh_table(self):
        accounts = list_accounts()
        self.table.setRowCount(len(accounts))
        for row, acc in enumerate(accounts):
            self.table.setItem(row, 0, QTableWidgetItem(str(acc.id)))
            self.table.setItem(row, 1, QTableWidgetItem(acc.phone or ""))
            self.table.setItem(row, 2, QTableWidgetItem(
                f"{acc.first_name or ''} {acc.last_name or ''}".strip()
            ))

            status_text = STATUS_LABELS.get(acc.status, acc.status)
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor(STATUS_COLORS.get(acc.status, "#9E9E9E")))
            self.table.setItem(row, 3, status_item)

            spam = acc.spamblock or "正常"
            spam_item = QTableWidgetItem(spam)
            if acc.spamblock:
                spam_item.setForeground(QColor("#F44336"))
            self.table.setItem(row, 4, spam_item)

            self.table.setItem(row, 5, QTableWidgetItem("有" if acc.two_fa else "无"))
            self.table.setItem(row, 6, QTableWidgetItem("是" if acc.is_premium else "否"))
            checked = acc.last_checked.strftime("%m-%d %H:%M") if acc.last_checked else "—"
            self.table.setItem(row, 7, QTableWidgetItem(checked))

    def _on_import_folder(self):
        """选择整个父文件夹，自动扫描所有协议号。"""
        parent = QFileDialog.getExistingDirectory(self, "选择协议号父文件夹")
        if not parent:
            return
        self.status_label.setText("导入中，请稍候...")
        results = import_from_parent_folder(parent)
        self._show_import_result(results)

    def _on_import_single(self):
        """手动多选单个协议号文件夹。"""
        # PyQt5 没有直接支持多选文件夹，用循环让用户多次选择
        folders = []
        while True:
            folder = QFileDialog.getExistingDirectory(
                self, f"选择协议号文件夹（已选 {len(folders)} 个，取消结束选择）"
            )
            if not folder:
                break
            folders.append(folder)

        if not folders:
            return
        self.status_label.setText("导入中，请稍候...")
        results = import_from_folders(folders)
        self._show_import_result(results)

    def _show_import_result(self, results):
        ok = sum(1 for r in results if r["status"] == "ok")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        failed = sum(1 for r in results if r["status"] == "failed")
        self.status_label.setText(
            f"导入完成：成功 {ok} 个，跳过 {skipped} 个（已存在），失败 {failed} 个"
        )
        if failed:
            fail_msgs = [f"{r.get('phone','?')}: {r.get('reason','')}"
                         for r in results if r["status"] == "failed"]
            QMessageBox.warning(self, "部分导入失败", "\n".join(fail_msgs[:10]))
        self.refresh_table()

    def _start_check(self, ids: list):
        if not ids:
            self.status_label.setText("没有账号，请先导入")
            return
        self.progress_bar.setMaximum(len(ids))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.btn_check_selected.setEnabled(False)
        self.btn_check_all.setEnabled(False)
        self.status_label.setText(f"正在验证 {len(ids)} 个账号...")
        self._worker = CheckWorker(ids)
        self._worker.progress.connect(self._on_check_progress)
        self._worker.finished.connect(self._on_check_done)
        self._worker.start()

    def _on_check_selected(self):
        ids = self._get_selected_ids()
        if not ids:
            self.status_label.setText("请先点击表格中的行选中账号（可 Ctrl 多选）")
            return
        self._start_check(ids)

    def _on_check_all(self):
        ids = [a.id for a in list_accounts()]
        self._start_check(ids)

    def _on_check_progress(self, account_id, status):
        self.progress_bar.setValue(self.progress_bar.value() + 1)

    def _on_check_done(self):
        self.progress_bar.setVisible(False)
        self.btn_check_selected.setEnabled(True)
        self.btn_check_all.setEnabled(True)
        accounts = list_accounts()
        active = sum(1 for a in accounts if a.status == "active")
        self.status_label.setText(
            f"验证完成：{active}/{len(accounts)} 个账号正常"
        )
        self.refresh_table()

    def _on_profile(self):
        selected_ids = self._get_selected_ids()
        if not selected_ids:
            QMessageBox.information(self, "提示", "请先选中要修改的账号行")
            return
        dlg = ProfileDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        vals = dlg.get_values()
        if not any(vals.values()):
            QMessageBox.information(self, "提示", "没有填写任何修改内容")
            return

        clients = [(aid, client_manager.get_client(aid))
                   for aid in selected_ids if client_manager.get_client(aid)]
        if not clients:
            QMessageBox.warning(self, "提示", "选中账号均未连接，请先点「批量验证状态」")
            return

        from core.client_manager import run_async
        results = run_async(batch_update_profiles(clients, **vals))
        success = sum(1 for v in results.values() if v)
        self.status_label.setText(f"资料修改：{success}/{len(clients)} 个成功")

    def _on_delete(self):
        ids = self._get_selected_ids()
        if not ids:
            return
        reply = QMessageBox.question(self, "确认删除", f"确认从数据库删除 {len(ids)} 个账号记录？\n（不会删除 session 文件）")
        if reply == QMessageBox.Yes:
            for aid in ids:
                delete_account(aid)
            self.refresh_table()

    def _get_selected_ids(self):
        rows = set(idx.row() for idx in self.table.selectedIndexes())
        ids = []
        for row in rows:
            item = self.table.item(row, 0)
            if item:
                ids.append(int(item.text()))
        return ids
