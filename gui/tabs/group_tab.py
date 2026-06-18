"""
group_tab.py
群组管理界面：添加群组、查看发言状态、人机验证提示。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QDialog, QFormLayout,
    QLineEdit, QComboBox, QDialogButtonBox, QLabel,
)
from PyQt5.QtGui import QColor

from services.group_service import add_group, list_groups, resolve_group_info
from services.account_service import list_accounts


class AddGroupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加群组")
        self.setMinimumWidth(400)
        layout = QFormLayout(self)

        self.account_combo = QComboBox()
        for acc in list_accounts():
            self.account_combo.addItem(f"{acc.name or acc.phone} (id={acc.id})", acc.id)

        self.group_input = QLineEdit()
        self.group_input.setPlaceholderText("@username 或群组数字ID")

        layout.addRow("使用账号:", self.account_combo)
        layout.addRow("群组:", self.group_input)

        hint = QLabel("输入群组 @username 或数字 ID（负数），程序会自动获取群组信息")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addRow(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_values(self):
        return {
            "account_id": self.account_combo.currentData(),
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
        self.btn_add = QPushButton("添加群组")
        self.btn_refresh = QPushButton("刷新")
        for btn in [self.btn_add, self.btn_refresh]:
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.verify_banner = QLabel("")
        self.verify_banner.setStyleSheet("background: #FFF3CD; color: #856404; padding: 8px; border-radius: 4px;")
        self.verify_banner.setVisible(False)
        layout.addWidget(self.verify_banner)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "群组ID", "用户名", "标题", "能否发言", "需要验证"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        self.btn_add.clicked.connect(self._on_add)
        self.btn_refresh.clicked.connect(self.refresh_table)

    def refresh_table(self):
        groups = list_groups()
        self.table.setRowCount(len(groups))
        needs_verify_groups = []
        for row, grp in enumerate(groups):
            self.table.setItem(row, 0, QTableWidgetItem(str(grp.id)))
            self.table.setItem(row, 1, QTableWidgetItem(grp.tg_id))
            self.table.setItem(row, 2, QTableWidgetItem(grp.username or ""))
            self.table.setItem(row, 3, QTableWidgetItem(grp.title or ""))

            can_send_item = QTableWidgetItem("是" if grp.can_send else "否")
            can_send_item.setForeground(QColor("#4CAF50" if grp.can_send else "#F44336"))
            self.table.setItem(row, 4, can_send_item)

            verify_item = QTableWidgetItem("需要验证" if grp.needs_verify else "正常")
            if grp.needs_verify:
                verify_item.setForeground(QColor("#FF9800"))
                needs_verify_groups.append(grp.title or grp.tg_id)
            self.table.setItem(row, 5, verify_item)

        if needs_verify_groups:
            names = "、".join(needs_verify_groups[:3])
            self.verify_banner.setText(
                f"⚠ 以下群组需要人机验证（用手机打开 Telegram，手动完成验证后点刷新）：{names}"
            )
            self.verify_banner.setVisible(True)
        else:
            self.verify_banner.setVisible(False)

    def _on_add(self):
        dlg = AddGroupDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        vals = dlg.get_values()
        if not vals["group_input"] or vals["account_id"] is None:
            QMessageBox.warning(self, "提示", "请填写群组信息并选择账号")
            return

        info = resolve_group_info(vals["account_id"], vals["group_input"])
        if not info:
            QMessageBox.critical(self, "错误", "无法获取群组信息，请确认账号已连接且群组 ID/用户名正确")
            return

        add_group(
            account_id=vals["account_id"],
            tg_id=info["tg_id"],
            username=info["username"],
            title=info["title"],
        )
        self.refresh_table()
