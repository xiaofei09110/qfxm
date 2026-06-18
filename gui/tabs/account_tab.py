"""
account_tab.py
账号管理界面。本地模式和远程模式均通过 services.proxy 统一调用。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QFileDialog, QLabel, QHeaderView, QMessageBox,
    QProgressBar, QDialog, QFormLayout, QLineEdit, QDialogButtonBox,
)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QColor

from services.proxy import (
    import_from_parent_folder, import_from_folders,
    batch_check_status, list_accounts, delete_account,
    batch_update_profiles_gui,
)

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


class ImportWorker(QThread):
    progress = pyqtSignal(int, int, str)  # current, total, phone
    finished = pyqtSignal(list)

    def __init__(self, mode, path):
        super().__init__()
        self.mode = mode  # "folder" or "folders"
        self.path = path  # str or list[str]

    def run(self):
        import os
        from api_client import _upload_folder

        if self.mode == "folder":
            folders = [
                os.path.join(self.path, name)
                for name in sorted(os.listdir(self.path))
                if os.path.isdir(os.path.join(self.path, name)) and name.isdigit()
            ]
        else:
            folders = self.path

        total = len(folders)
        results = []
        for i, folder in enumerate(folders, 1):
            phone = os.path.basename(folder)
            self.progress.emit(i, total, phone)
            try:
                results.extend(_upload_folder(folder))
            except Exception as e:
                results.append({"status": "failed", "phone": phone, "reason": str(e)})
        self.finished.emit(results)


class CheckWorker(QThread):
    progress = pyqtSignal(int, int, str)  # current, total, status
    finished = pyqtSignal()

    def __init__(self, account_ids):
        super().__init__()
        self.account_ids = account_ids

    def run(self):
        from api_client import check_account_status
        total = len(self.account_ids)
        for i, aid in enumerate(self.account_ids, 1):
            try:
                status = check_account_status(aid)
            except Exception:
                status = "error"
            self.progress.emit(i, total, status)
        self.finished.emit()


class CleanWorker(QThread):
    finished = pyqtSignal(int)

    def __init__(self, accounts):
        super().__init__()
        self.accounts = accounts

    def run(self):
        for acc in self.accounts:
            delete_account(acc.id)
        self.finished.emit(len(self.accounts))


class RefreshWorker(QThread):
    finished = pyqtSignal(list)
    error    = pyqtSignal(str)

    def run(self):
        try:
            self.finished.emit(list_accounts())
        except Exception as e:
            self.error.emit(str(e))


class DeleteWorker(QThread):
    finished = pyqtSignal()

    def __init__(self, ids):
        super().__init__()
        self.ids = ids

    def run(self):
        for aid in self.ids:
            delete_account(aid)
        self.finished.emit()


class ProfileWorker(QThread):
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)

    def __init__(self, selected_ids, vals):
        super().__init__()
        self.selected_ids = selected_ids
        self.vals = vals

    def run(self):
        try:
            results = batch_update_profiles_gui(self.selected_ids, **self.vals)
            self.finished.emit(results or {})
        except Exception as e:
            self.error.emit(str(e))


class ProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量修改账号资料")
        self.setMinimumWidth(420)
        layout = QFormLayout(self)

        self.first_name = QLineEdit()
        self.last_name  = QLineEdit()
        self.bio        = QLineEdit()
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
            "last_name":  self.last_name.text().strip()  or None,
            "bio":        self.bio.text().strip()         or None,
            "photo_path": self.photo_path.text().strip()  or None,
        }


class AccountTab(QWidget):
    def __init__(self):
        super().__init__()
        self._accounts = []
        self._build_ui()
        self.refresh_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        import_label = QLabel("导入协议号：")
        import_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(import_label)

        import_row = QHBoxLayout()
        self.btn_import_folder = QPushButton("选择整个协议号文件夹（推荐）")
        self.btn_import_folder.setToolTip("选择包含所有协议号子文件夹的父目录")
        self.btn_import_single = QPushButton("选择单个/多个协议号")
        import_row.addWidget(self.btn_import_folder)
        import_row.addWidget(self.btn_import_single)
        import_row.addStretch()
        layout.addLayout(import_row)

        btn_row = QHBoxLayout()
        self.btn_check_selected = QPushButton("验证选中账号")
        self.btn_check_all      = QPushButton("验证全部账号")
        self.btn_clean          = QPushButton("清理失效账号")
        self.btn_profile        = QPushButton("批量改资料")
        self.btn_delete         = QPushButton("删除选中")
        self.btn_refresh        = QPushButton("刷新列表")
        for btn in [self.btn_check_selected, self.btn_check_all, self.btn_clean,
                    self.btn_profile, self.btn_delete, self.btn_refresh]:
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "ID", "手机号", "名字", "状态", "SpamBlock", "2FA", "Premium", "最后检测"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        self.btn_import_folder.clicked.connect(self._on_import_folder)
        self.btn_import_single.clicked.connect(self._on_import_single)
        self.btn_check_selected.clicked.connect(self._on_check_selected)
        self.btn_check_all.clicked.connect(self._on_check_all)
        self.btn_clean.clicked.connect(self._on_clean)
        self.btn_profile.clicked.connect(self._on_profile)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_refresh.clicked.connect(self.refresh_table)

    def refresh_table(self):
        if hasattr(self, '_refresh_worker') and self._refresh_worker.isRunning():
            return
        worker = RefreshWorker()
        worker.finished.connect(self._populate_table)
        worker.error.connect(lambda e: self.status_label.setText(f"刷新失败: {e}"))
        self._refresh_worker = worker
        worker.start()

    def _populate_table(self, accounts):
        self._accounts = accounts
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

            is_spammed = acc.spamblock and acc.spamblock.lower() not in ("free", "none", "ok", "")
            spam_item = QTableWidgetItem("正常" if not is_spammed else acc.spamblock)
            if is_spammed:
                spam_item.setForeground(QColor("#F44336"))
            self.table.setItem(row, 4, spam_item)

            self.table.setItem(row, 5, QTableWidgetItem("有" if acc.two_fa else "无"))
            self.table.setItem(row, 6, QTableWidgetItem("是" if acc.is_premium else "否"))
            checked = acc.last_checked.strftime("%m-%d %H:%M") if acc.last_checked else "—"
            self.table.setItem(row, 7, QTableWidgetItem(checked))

    def _set_import_buttons(self, enabled: bool):
        self.btn_import_folder.setEnabled(enabled)
        self.btn_import_single.setEnabled(enabled)

    def _start_import(self, mode, path):
        self._set_import_buttons(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label.setText("准备上传...")
        self._import_worker = ImportWorker(mode, path)
        self._import_worker.progress.connect(self._on_import_progress)
        self._import_worker.finished.connect(self._on_import_done)
        self._import_worker.start()

    def _on_import_progress(self, current, total, phone):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_label.setText(f"正在上传 {current}/{total}：{phone}")

    def _on_import_folder(self):
        parent = QFileDialog.getExistingDirectory(self, "选择协议号父文件夹")
        if not parent:
            return
        self._start_import("folder", parent)

    def _on_import_single(self):
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
        self._start_import("folders", folders)

    def _on_import_done(self, results):
        self.progress_bar.setVisible(False)
        self._set_import_buttons(True)
        self._show_import_result(results)

    def _show_import_result(self, results):
        ok      = sum(1 for r in results if r.get("status") == "ok")
        skipped = sum(1 for r in results if r.get("status") == "skipped")
        failed  = sum(1 for r in results if r.get("status") == "failed")
        self.status_label.setText(
            f"导入完成：成功 {ok} 个，跳过 {skipped} 个（已存在），失败 {failed} 个"
        )
        if failed:
            fail_msgs = [f"{r.get('phone','?')}: {r.get('reason','')}"
                         for r in results if r.get("status") == "failed"]
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
        ids = [a.id for a in self._accounts]
        if not ids:
            self.status_label.setText("列表为空，请先等待刷新完成或点「刷新列表」")
            return
        self._start_check(ids)

    def _on_check_progress(self, current, total, status):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_label.setText(f"正在验证 {current}/{total}...")

    def _on_check_done(self):
        self.progress_bar.setVisible(False)
        self.btn_check_selected.setEnabled(True)
        self.btn_check_all.setEnabled(True)
        self.status_label.setText("验证完成，正在刷新数据...")
        worker = RefreshWorker()
        worker.finished.connect(self._on_check_refresh_done)
        self._check_refresh_worker = worker
        worker.start()

    def _on_check_refresh_done(self, accounts):
        self._populate_table(accounts)
        active = sum(1 for a in accounts if a.status == "active")
        self.status_label.setText(f"验证完成：{active}/{len(accounts)} 个账号正常")

    def _on_clean(self):
        """一键删除失效/封号/多地登录账号，同时删除服务器 session 文件。"""
        CLEAN_STATUSES = {"invalid", "banned", "restricted"}
        STATUS_DESC = {"invalid": "失效", "banned": "封号", "restricted": "多地登录"}
        accounts = self._accounts
        to_delete = [a for a in accounts if a.status in CLEAN_STATUSES]
        if not to_delete:
            QMessageBox.information(self, "提示", "没有需要清理的账号（失效/封号/多地登录）")
            return
        counts = {}
        for a in to_delete:
            counts[a.status] = counts.get(a.status, 0) + 1
        detail = "、".join(f"{STATUS_DESC.get(s, s)} {n} 个" for s, n in counts.items())
        reply = QMessageBox.question(
            self, "确认清理",
            f"将删除 {len(to_delete)} 个账号（{detail}），同时删除服务器上的 session 文件。\n"
            f"保留其余 {len(accounts)-len(to_delete)} 个正常账号。\n\n确认继续？"
        )
        if reply != QMessageBox.Yes:
            return
        self.btn_clean.setEnabled(False)
        self.status_label.setText(f"正在清理 {len(to_delete)} 个账号...")
        self._clean_worker = CleanWorker(to_delete)
        self._clean_worker.finished.connect(lambda n: self._on_clean_done(n, detail))
        self._clean_worker.start()

    def _on_clean_done(self, count, detail):
        self.btn_clean.setEnabled(True)
        self.status_label.setText(f"已清理 {count} 个账号（{detail}）")
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
        self.btn_profile.setEnabled(False)
        self.status_label.setText("正在修改资料，请稍候...")
        self._profile_worker = ProfileWorker(selected_ids, vals)
        self._profile_worker.finished.connect(lambda r: self._on_profile_done(r, len(selected_ids)))
        self._profile_worker.error.connect(lambda e: (
            QMessageBox.critical(self, "修改失败", e),
            self.btn_profile.setEnabled(True),
        ))
        self._profile_worker.start()

    def _on_profile_done(self, results, total):
        self.btn_profile.setEnabled(True)
        if not results:
            QMessageBox.warning(self, "提示", "选中账号均未连接，请先点「验证账号」")
            return
        success = sum(1 for v in results.values() if v)
        self.status_label.setText(f"资料修改：{success}/{total} 个成功")

    def _on_delete(self):
        ids = self._get_selected_ids()
        if not ids:
            return
        reply = QMessageBox.question(
            self, "确认删除", f"确认从数据库删除 {len(ids)} 个账号记录？\n（不会删除 session 文件）"
        )
        if reply != QMessageBox.Yes:
            return
        self.btn_delete.setEnabled(False)
        self.status_label.setText(f"正在删除 {len(ids)} 个账号...")
        self._delete_worker = DeleteWorker(ids)
        self._delete_worker.finished.connect(self._on_delete_done)
        self._delete_worker.start()

    def _on_delete_done(self):
        self.btn_delete.setEnabled(True)
        self.status_label.setText("删除完成")
        self.refresh_table()

    def _get_selected_ids(self):
        rows = set(idx.row() for idx in self.table.selectedIndexes())
        ids = []
        for row in rows:
            item = self.table.item(row, 0)
            if item:
                ids.append(int(item.text()))
        return ids
