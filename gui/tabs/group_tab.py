"""
group_tab.py
群组管理界面。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QDialog, QFormLayout,
    QLineEdit, QComboBox, QDialogButtonBox, QLabel,
)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QColor

from services.proxy import list_groups, resolve_group_info, add_group, list_accounts


class AddGroupWorker(QThread):
    finished = pyqtSignal(object)  # group object or None
    error    = pyqtSignal(str)

    def __init__(self, account_id, group_input):
        super().__init__()
        self.account_id  = account_id
        self.group_input = group_input

    def run(self):
        info = resolve_group_info(self.account_id, self.group_input)
        if not info:
            self.error.emit("无法获取群组信息，请确认账号已验证且群组 ID/用户名正确")
            return
        try:
            grp = add_group(
                account_id=self.account_id,
                tg_id=info["tg_id"],
                username=info.get("username", ""),
                title=info.get("title", ""),
            )
            self.finished.emit(grp)
        except Exception as e:
            self.error.emit(str(e))


class AddGroupDialog(QDialog):
    def __init__(self, parent=None, accounts=None):
        super().__init__(parent)
        self.setWindowTitle("添加群组")
        self.setMinimumWidth(400)
        layout = QFormLayout(self)

        self.account_combo = QComboBox()
        for acc in (accounts or []):
            self.account_combo.addItem(f"{acc.name or acc.phone} (id={acc.id})", acc.id)

        self.group_input = QLineEdit()
        self.group_input.setPlaceholderText("@username 或群组数字ID")

        layout.addRow("使用账号:", self.account_combo)
        layout.addRow("群组:", self.group_input)

        hint = QLabel("输入群组 @username 或数字 ID，程序会自动获取群组信息")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addRow(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_values(self):
        return {
            "account_id":  self.account_combo.currentData(),
            "group_input": self.group_input.text().strip(),
        }


class GroupTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        btn_row = QHBoxLayout()
        self.btn_add     = QPushButton("添加群组")
        self.btn_delete  = QPushButton("删除选中")
        self.btn_refresh = QPushButton("刷新")
        for btn in [self.btn_add, self.btn_delete, self.btn_refresh]:
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.verify_banner = QLabel("")
        self.verify_banner.setStyleSheet(
            "background: #FFF3CD; color: #856404; padding: 8px; border-radius: 4px;"
        )
        self.verify_banner.setVisible(False)
        layout.addWidget(self.verify_banner)

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
        self.btn_refresh.clicked.connect(self.refresh_table)

    def refresh_table(self):
        groups = list_groups()
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
            self.verify_banner.setText(
                f"以下群组需要人机验证（用手机打开 Telegram 完成验证后点刷新）：{names}"
            )
            self.verify_banner.setVisible(True)
        else:
            self.verify_banner.setVisible(False)

    def _on_add(self):
        accounts = list_accounts()
        dlg = AddGroupDialog(self, accounts=accounts)
        if dlg.exec_() != QDialog.Accepted:
            return
        vals = dlg.get_values()
        if not vals["group_input"] or vals["account_id"] is None:
            QMessageBox.warning(self, "提示", "请填写群组信息并选择账号")
            return
        self.btn_add.setEnabled(False)
        self.status_label.setText("正在获取群组信息...")
        self._add_worker = AddGroupWorker(vals["account_id"], vals["group_input"])
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
        from services.proxy import delete_group
        for gid in ids:
            try:
                delete_group(gid)
            except Exception:
                pass
        self.refresh_table()
