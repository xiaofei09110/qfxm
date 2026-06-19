"""
account_tab.py
账号管理界面。本地模式和远程模式均通过 services.proxy 统一调用。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QFileDialog, QLabel, QHeaderView, QMessageBox,
    QProgressBar, QDialog, QFormLayout, QLineEdit, QDialogButtonBox,
    QComboBox,
)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QColor

from services.proxy import (
    import_from_parent_folder, import_from_folders,
    batch_check_status, list_accounts, delete_account,
    batch_update_profiles_gui, verify_account_spambot,
    set_accounts_resting, set_account_owner,
)
from gui.owner_filter import get_owner_filter, set_owner_filter

STATUS_COLORS = {
    "active":      "#4CAF50",
    "restricted":  "#FF9800",
    "banned":      "#F44336",
    "flood":       "#9C27B0",
    "invalid":     "#F44336",
    "needs_2fa":   "#FF9800",
    "unknown":     "#9E9E9E",
    "error":       "#F44336",
    "resting":     "#2196F3",
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
    "resting":     "养号中",
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
    error    = pyqtSignal(str)

    def __init__(self, accounts):
        super().__init__()
        self.accounts = accounts

    def run(self):
        failed = []
        for acc in self.accounts:
            try:
                delete_account(acc.id)
            except Exception as e:
                failed.append(str(e))
        if failed:
            self.error.emit(f"部分账号删除失败：{failed[0]}")
        self.finished.emit(len(self.accounts) - len(failed))


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
    error    = pyqtSignal(str)

    def __init__(self, ids):
        super().__init__()
        self.ids = ids

    def run(self):
        for aid in self.ids:
            try:
                delete_account(aid)
            except Exception as e:
                self.error.emit(f"删除账号 {aid} 失败：{e}")
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


class VerifyWorker(QThread):
    """依次对每个账号执行 SpamBot 申诉，逐条汇报结果。"""
    progress = pyqtSignal(str)   # 单条结果（账号 + 结果文本）
    finished = pyqtSignal()

    def __init__(self, account_ids: list):
        super().__init__()
        self.account_ids = account_ids

    def run(self):
        for aid in self.account_ids:
            try:
                result = verify_account_spambot(aid)
            except Exception as e:
                result = f"出错: {e}"
            self.progress.emit(f"账号 {aid}：\n{result}")
        self.finished.emit()


class SetOwnerWorker(QThread):
    finished = pyqtSignal()
    error    = pyqtSignal(str)

    def __init__(self, ids: list, owner: str):
        super().__init__()
        self.ids   = ids
        self.owner = owner

    def run(self):
        try:
            set_account_owner(self.ids, self.owner)
        except Exception as e:
            self.error.emit(str(e))
        self.finished.emit()


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
        self.btn_spambot        = QPushButton("SpamBot 申诉")
        self.btn_spambot.setToolTip("自动与 @SpamBot 交互，为选中账号提交申诉解除限制")
        self.btn_set_resting    = QPushButton("标为养号中")
        self.btn_set_resting.setToolTip("将选中账号标为养号中，不再参与任务分配")
        self.btn_set_resting.setStyleSheet("color: #2196F3;")
        self.btn_unrest         = QPushButton("解除养号")
        self.btn_unrest.setToolTip("将选中养号中的账号恢复正常，可重新参与任务分配")
        self.btn_set_owner      = QPushButton("设置归属")
        self.btn_set_owner.setToolTip("为选中账号设置归属分组标签（用于多人共用服务器时隔离账号）")
        self.btn_delete         = QPushButton("删除选中")
        self.btn_refresh        = QPushButton("刷新列表")
        for btn in [self.btn_check_selected, self.btn_check_all, self.btn_clean,
                    self.btn_profile, self.btn_spambot,
                    self.btn_set_resting, self.btn_unrest,
                    self.btn_set_owner, self.btn_delete, self.btn_refresh]:
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 归属分组筛选行
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("归属分组筛选："))
        self.owner_filter_combo = QComboBox()
        self.owner_filter_combo.setMinimumWidth(160)
        self.owner_filter_combo.setToolTip("筛选显示指定归属的账号，同时限制验证/清理等操作范围")
        filter_row.addWidget(self.owner_filter_combo)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "ID", "手机号", "名字", "归属分组", "状态", "SpamBlock", "2FA", "Premium", "最后检测"
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
        self.btn_spambot.clicked.connect(self._on_spambot)
        self.btn_set_resting.clicked.connect(lambda: self._on_set_resting(True))
        self.btn_unrest.clicked.connect(lambda: self._on_set_resting(False))
        self.btn_set_owner.clicked.connect(self._on_set_owner)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_refresh.clicked.connect(self.refresh_table)
        self.owner_filter_combo.currentIndexChanged.connect(self._on_owner_filter_changed)

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

        # 更新归属分组筛选 combo（保留当前选中项）
        owners = sorted({getattr(a, "owner", "默认") or "默认" for a in accounts})
        current_filter = self.owner_filter_combo.currentText()
        self.owner_filter_combo.blockSignals(True)
        self.owner_filter_combo.clear()
        self.owner_filter_combo.addItem("全部", "")
        for o in owners:
            self.owner_filter_combo.addItem(o, o)
        # 恢复之前的选项
        idx = self.owner_filter_combo.findData(current_filter)
        if idx >= 0:
            self.owner_filter_combo.setCurrentIndex(idx)
        self.owner_filter_combo.blockSignals(False)

        owner_filter = self.owner_filter_combo.currentData() or ""
        visible = [a for a in accounts if not owner_filter or getattr(a, "owner", "默认") == owner_filter]

        self.table.setRowCount(len(visible))
        for row, acc in enumerate(visible):
            self.table.setItem(row, 0, QTableWidgetItem(str(acc.id)))
            self.table.setItem(row, 1, QTableWidgetItem(acc.phone or ""))
            self.table.setItem(row, 2, QTableWidgetItem(
                f"{acc.first_name or ''} {acc.last_name or ''}".strip()
            ))

            owner = getattr(acc, "owner", "默认") or "默认"
            self.table.setItem(row, 3, QTableWidgetItem(owner))

            is_resting = getattr(acc, "is_resting", False)
            if is_resting:
                status_text = "养号中"
                status_color = STATUS_COLORS["resting"]
            else:
                status_text = STATUS_LABELS.get(acc.status, acc.status)
                status_color = STATUS_COLORS.get(acc.status, "#9E9E9E")
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor(status_color))
            self.table.setItem(row, 4, status_item)

            is_spammed = acc.spamblock and acc.spamblock.lower() not in ("free", "none", "ok", "")
            spam_item = QTableWidgetItem("正常" if not is_spammed else acc.spamblock)
            if is_spammed:
                spam_item.setForeground(QColor("#F44336"))
            self.table.setItem(row, 5, spam_item)

            self.table.setItem(row, 6, QTableWidgetItem("有" if acc.two_fa else "无"))
            self.table.setItem(row, 7, QTableWidgetItem("是" if acc.is_premium else "否"))
            checked = acc.last_checked.strftime("%m-%d %H:%M") if acc.last_checked else "—"
            self.table.setItem(row, 8, QTableWidgetItem(checked))

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
        self._clean_worker.error.connect(lambda e: self.status_label.setText(e))
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

    def _on_spambot(self):
        ids = self._get_selected_ids()
        if not ids:
            QMessageBox.information(self, "提示", "请先选中要申诉的账号行（可 Ctrl 多选）")
            return
        reply = QMessageBox.question(
            self, "SpamBot 申诉",
            f"将对 {len(ids)} 个账号自动联系 @SpamBot 提交申诉。\n"
            "每个账号约需 10-30 秒，申诉后 Telegram 会在数小时内处理。\n\n确认开始？"
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_spambot.setEnabled(False)
        self.status_label.setText(f"正在对 {len(ids)} 个账号提交 SpamBot 申诉...")

        # 弹出结果窗口，逐条追加
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit
        self._verify_dlg = QDialog(self)
        self._verify_dlg.setWindowTitle("SpamBot 申诉进度")
        self._verify_dlg.setMinimumSize(520, 380)
        dlg_layout = QVBoxLayout(self._verify_dlg)
        self._verify_log = QTextEdit()
        self._verify_log.setReadOnly(True)
        self._verify_log.setStyleSheet("font-family: monospace; font-size: 12px;")
        dlg_layout.addWidget(self._verify_log)
        self._verify_dlg.show()

        self._verify_worker = VerifyWorker(ids)
        self._verify_worker.progress.connect(self._on_verify_progress)
        self._verify_worker.finished.connect(self._on_verify_done)
        self._verify_worker.start()

    def _on_verify_progress(self, msg: str):
        self._verify_log.append(msg)
        self._verify_log.append("─" * 40)

    def _on_verify_done(self):
        self.btn_spambot.setEnabled(True)
        self.status_label.setText("SpamBot 申诉完成，请等待 Telegram 处理后重新验证账号状态")
        self._verify_log.append("\n✅ 所有账号申诉流程已完成。")

    def _on_set_resting(self, resting: bool):
        ids = self._get_selected_ids()
        if not ids:
            self.status_label.setText("请先选中账号行")
            return
        action = "标为养号中" if resting else "解除养号"
        try:
            set_accounts_resting(ids, resting)
            self.status_label.setText(f"已{action} {len(ids)} 个账号")
            self.refresh_table()
        except Exception as e:
            QMessageBox.critical(self, "操作失败", str(e))

    def _on_set_owner(self):
        ids = self._get_selected_ids()
        if not ids:
            self.status_label.setText("请先选中账号行")
            return
        from PyQt5.QtWidgets import QInputDialog
        # 收集已有分组作为建议
        existing = sorted({getattr(a, "owner", "默认") or "默认" for a in self._accounts})
        owner, ok = QInputDialog.getItem(
            self, "设置归属分组",
            f"为选中的 {len(ids)} 个账号设置归属分组标签：\n（可直接输入新分组名，或从下方选择已有分组）",
            existing, editable=True,
        )
        if not ok or not owner.strip():
            return
        owner = owner.strip()
        self.btn_set_owner.setEnabled(False)
        self.status_label.setText(f"正在设置归属分组「{owner}」...")
        self._set_owner_worker = SetOwnerWorker(ids, owner)
        self._set_owner_worker.finished.connect(lambda: self._on_set_owner_done(owner, len(ids)))
        self._set_owner_worker.error.connect(lambda e: self.status_label.setText(f"设置失败: {e}"))
        self._set_owner_worker.start()

    def _on_set_owner_done(self, owner: str, count: int):
        self.btn_set_owner.setEnabled(True)
        self.status_label.setText(f"已将 {count} 个账号的归属分组设为「{owner}」")
        self.refresh_table()

    def _on_owner_filter_changed(self):
        owner = self.owner_filter_combo.currentData() or ""
        set_owner_filter(owner)
        self._populate_table(self._accounts)

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
        self._delete_worker.error.connect(lambda e: self.status_label.setText(e))
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
