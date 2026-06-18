"""
group_tab.py
群组管理界面。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QDialog, QFormLayout,
    QLineEdit, QDialogButtonBox, QLabel,
)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit

from services.proxy import (
    list_groups, resolve_group_info, add_group, list_accounts,
    delete_group, verify_group_join, clear_group_verify,
)


class RefreshWorker(QThread):
    finished = pyqtSignal(list)
    error    = pyqtSignal(str)

    def run(self):
        try:
            self.finished.emit(list_groups())
        except Exception as e:
            self.error.emit(str(e))


class ClearVerifyWorker(QThread):
    finished = pyqtSignal()

    def __init__(self, ids):
        super().__init__()
        self.ids = ids

    def run(self):
        for gid in self.ids:
            try:
                clear_group_verify(gid)
            except Exception:
                pass
        self.finished.emit()


class DeleteGroupWorker(QThread):
    finished = pyqtSignal()

    def __init__(self, ids):
        super().__init__()
        self.ids = ids

    def run(self):
        for gid in self.ids:
            try:
                delete_group(gid)
            except Exception:
                pass
        self.finished.emit()


class AddGroupWorker(QThread):
    finished = pyqtSignal(object)
    error    = pyqtSignal(str)

    def __init__(self, group_input):
        super().__init__()
        self.group_input = group_input

    def run(self):
        # 自动选第一个可用账号来解析群组信息，用户无需关心
        accounts = list_accounts()
        active = [a for a in accounts if a.status == "active"]
        if not active:
            self.error.emit("没有可用账号，请先在「账号管理」验证账号状态")
            return

        account_id = active[0].id
        info = resolve_group_info(account_id, self.group_input)
        if not info:
            self.error.emit("无法获取群组信息，请确认群组 @username 或 ID 正确")
            return
        try:
            grp = add_group(
                account_id=account_id,
                tg_id=info["tg_id"],
                username=info.get("username", ""),
                title=info.get("title", ""),
            )
            self.finished.emit(grp)
        except Exception as e:
            self.error.emit(str(e))


class GroupVerifyWorker(QThread):
    """对需要验证的群组批量执行入群验证点击。"""
    progress = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, items: list):
        """items: list of (account_id, group_id, group_title)"""
        super().__init__()
        self.items = items

    def run(self):
        for account_id, group_id, title in self.items:
            self.progress.emit(f"正在验证：{title}...")
            try:
                result = verify_group_join(account_id, group_id)
            except Exception as e:
                result = f"出错：{e}"
            self.progress.emit(f"【{title}】\n{result}")
        self.finished.emit()


class AddGroupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加群组")
        self.setMinimumWidth(380)
        layout = QFormLayout(self)

        self.group_input = QLineEdit()
        self.group_input.setPlaceholderText("@username 或群组数字ID")
        layout.addRow("群组:", self.group_input)

        hint = QLabel("输入群组 @username 或数字 ID，程序会自动获取群组信息")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addRow(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_group_input(self) -> str:
        return self.group_input.text().strip()


class GroupTab(QWidget):
    def __init__(self):
        super().__init__()
        self._groups = []
        self._build_ui()
        self.refresh_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        btn_row = QHBoxLayout()
        self.btn_add          = QPushButton("添加群组")
        self.btn_delete       = QPushButton("删除选中")
        self.btn_clear_verify = QPushButton("清除验证标记")
        self.btn_refresh      = QPushButton("刷新")
        self.btn_clear_verify.setToolTip("将选中群组的「需要验证」状态手动清除为正常")
        for btn in [self.btn_add, self.btn_delete, self.btn_clear_verify, self.btn_refresh]:
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        banner_row = QHBoxLayout()
        self.verify_banner = QLabel("")
        self.verify_banner.setStyleSheet(
            "background: #FFF3CD; color: #856404; padding: 8px; border-radius: 4px;"
        )
        self.verify_banner.setVisible(False)
        self.btn_auto_verify = QPushButton("自动验证")
        self.btn_auto_verify.setStyleSheet(
            "background: #FF9800; color: white; font-weight: bold; padding: 4px 12px;"
        )
        self.btn_auto_verify.setVisible(False)
        self.btn_auto_verify.clicked.connect(self._on_auto_verify)
        banner_row.addWidget(self.verify_banner, 1)
        banner_row.addWidget(self.btn_auto_verify)
        layout.addLayout(banner_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["ID", "群组ID", "用户名", "标题", "能否发言", "需要验证"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        self.btn_add.clicked.connect(self._on_add)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_clear_verify.clicked.connect(self._on_clear_verify)
        self.btn_refresh.clicked.connect(self.refresh_table)

    def refresh_table(self):
        if hasattr(self, '_refresh_worker') and self._refresh_worker.isRunning():
            return
        worker = RefreshWorker()
        worker.finished.connect(self._populate_table)
        worker.error.connect(lambda e: self.status_label.setText(f"刷新失败: {e}"))
        self._refresh_worker = worker
        worker.start()

    def _populate_table(self, groups):
        self._groups = groups  # 缓存，供自动验证使用
        self.table.setRowCount(len(groups))
        needs_verify = []
        for row, grp in enumerate(groups):
            self.table.setItem(row, 0, QTableWidgetItem(str(grp.id)))
            self.table.setItem(row, 1, QTableWidgetItem(grp.tg_id))
            self.table.setItem(row, 2, QTableWidgetItem(grp.username or ""))
            self.table.setItem(row, 3, QTableWidgetItem(grp.title or ""))

            can_item = QTableWidgetItem("是" if grp.can_send else "否")
            can_item.setForeground(QColor("#4CAF50" if grp.can_send else "#F44336"))
            self.table.setItem(row, 4, can_item)

            v_item = QTableWidgetItem("需要验证" if grp.needs_verify else "正常")
            if grp.needs_verify:
                v_item.setForeground(QColor("#FF9800"))
                needs_verify.append(grp.title or grp.tg_id)
            self.table.setItem(row, 5, v_item)

        if needs_verify:
            names = "、".join(needs_verify[:3])
            extra = f" 等{len(needs_verify)}个" if len(needs_verify) > 3 else ""
            self.verify_banner.setText(
                f"以下群组需要入群验证：{names}{extra}（可点「自动验证」自动处理）"
            )
            self.verify_banner.setVisible(True)
            self.btn_auto_verify.setVisible(True)
        else:
            self.verify_banner.setVisible(False)
            self.btn_auto_verify.setVisible(False)

    def _on_auto_verify(self):
        groups = getattr(self, "_groups", [])
        need = [g for g in groups if g.needs_verify]
        if not need:
            return

        # 拉取账号列表，找第一个 active 账号来执行验证
        accounts = list_accounts()
        active = [a for a in accounts if a.status == "active"]
        if not active:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "没有可用账号，请先验证账号状态")
            return

        account_id = active[0].id
        items = [(account_id, g.id, g.title or g.tg_id) for g in need]

        self.btn_auto_verify.setEnabled(False)
        self.btn_auto_verify.setText("验证中...")

        # 进度弹窗
        self._verify_dlg = QDialog(self)
        self._verify_dlg.setWindowTitle("入群自动验证进度")
        self._verify_dlg.setMinimumSize(540, 400)
        dlg_layout = QVBoxLayout(self._verify_dlg)
        self._verify_log = QTextEdit()
        self._verify_log.setReadOnly(True)
        self._verify_log.setStyleSheet("font-family: monospace; font-size: 12px;")
        dlg_layout.addWidget(self._verify_log)
        self._verify_dlg.show()

        self._verify_worker = GroupVerifyWorker(items)
        self._verify_worker.progress.connect(lambda msg: (
            self._verify_log.append(msg),
            self._verify_log.append("─" * 40),
        ))
        self._verify_worker.finished.connect(self._on_verify_done)
        self._verify_worker.start()

    def _on_verify_done(self):
        self.btn_auto_verify.setEnabled(True)
        self.btn_auto_verify.setText("自动验证")
        self._verify_log.append("\n✅ 所有验证流程已完成，正在刷新群组状态...")
        self.refresh_table()

    def _on_add(self):
        dlg = AddGroupDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        group_input = dlg.get_group_input()
        if not group_input:
            QMessageBox.warning(self, "提示", "请填写群组 @username 或数字 ID")
            return
        self.btn_add.setEnabled(False)
        self.status_label.setText("正在获取群组信息...")
        self._add_worker = AddGroupWorker(group_input)
        self._add_worker.finished.connect(self._on_add_done)
        self._add_worker.error.connect(self._on_add_error)
        self._add_worker.start()

    def _on_add_done(self, grp):
        self.btn_add.setEnabled(True)
        self.status_label.setText(f"群组已添加：{grp.title or grp.tg_id}")
        self.refresh_table()

    def _on_add_error(self, msg):
        self.btn_add.setEnabled(True)
        self.status_label.setText("")
        QMessageBox.critical(self, "添加失败", msg)

    def _on_delete(self):
        rows = set(idx.row() for idx in self.table.selectedIndexes())
        if not rows:
            return
        ids = [int(self.table.item(r, 0).text()) for r in rows if self.table.item(r, 0)]
        reply = QMessageBox.question(self, "确认删除", f"确认删除 {len(ids)} 个群组？")
        if reply != QMessageBox.Yes:
            return
        self.btn_delete.setEnabled(False)
        self.status_label.setText(f"正在删除 {len(ids)} 个群组...")
        self._delete_worker = DeleteGroupWorker(ids)
        self._delete_worker.finished.connect(self._on_delete_done)
        self._delete_worker.start()

    def _on_delete_done(self):
        self.btn_delete.setEnabled(True)
        self.status_label.setText("删除完成")
        self.refresh_table()

    def _on_clear_verify(self):
        rows = set(idx.row() for idx in self.table.selectedIndexes())
        if not rows:
            self.status_label.setText("请先选中群组行")
            return
        ids = [int(self.table.item(r, 0).text()) for r in rows if self.table.item(r, 0)]
        self.btn_clear_verify.setEnabled(False)
        self.status_label.setText(f"正在清除 {len(ids)} 个群组的验证标记...")
        self._clear_verify_worker = ClearVerifyWorker(ids)
        self._clear_verify_worker.finished.connect(self._on_clear_verify_done)
        self._clear_verify_worker.start()

    def _on_clear_verify_done(self):
        self.btn_clear_verify.setEnabled(True)
        self.status_label.setText("验证标记已清除")
        self.refresh_table()
