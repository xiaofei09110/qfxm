"""
task_tab.py
定时任务管理界面。时间设置用直观选择器，内部自动转换成 cron 表达式。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QDialog, QFormLayout,
    QLineEdit, QComboBox, QTextEdit, QDialogButtonBox, QLabel,
    QSpinBox, QRadioButton, QButtonGroup, QGroupBox, QCheckBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from services.group_service import (
    create_task, delete_task, toggle_task, list_tasks, list_groups,
)
from services.account_service import list_accounts
import core.scheduler as scheduler


def _build_cron(mode: str, hour: int, minute: int, interval_minutes: int, weekdays: list) -> str:
    """把用户选择转换为 cron 表达式。"""
    if mode == "daily":
        return f"{minute} {hour} * * *"
    elif mode == "interval":
        if interval_minutes < 60:
            return f"*/{interval_minutes} * * * *"
        else:
            hours = interval_minutes // 60
            return f"0 */{hours} * * *"
    elif mode == "weekly":
        days = ",".join(str(d) for d in weekdays) if weekdays else "1"
        return f"{minute} {hour} * * {days}"
    return f"{minute} {hour} * * *"


def _cron_to_human(cron: str) -> str:
    """把 cron 表达式转换为人类可读描述。"""
    try:
        parts = cron.strip().split()
        if len(parts) != 5:
            return cron
        minute, hour, day, month, weekday = parts

        if weekday != "*" and day == "*":
            day_names = {"0":"周日","1":"周一","2":"周二","3":"周三","4":"周四","5":"周五","6":"周六","7":"周日"}
            days = "、".join(day_names.get(d, d) for d in weekday.split(","))
            return f"每周 {days} {hour}:{minute.zfill(2)}"
        if minute.startswith("*/"):
            return f"每 {minute[2:]} 分钟"
        if hour.startswith("*/"):
            return f"每 {hour[2:]} 小时"
        if day == "*" and weekday == "*":
            return f"每天 {hour}:{minute.zfill(2)}"
        return cron
    except Exception:
        return cron


class TaskDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建定时消息任务")
        self.setMinimumWidth(500)
        layout = QFormLayout(self)
        layout.setSpacing(10)

        # 基本信息
        self.name = QLineEdit()
        self.name.setPlaceholderText("给这个任务起个名字，方便识别")
        layout.addRow("任务名称:", self.name)

        self.account_combo = QComboBox()
        for acc in list_accounts():
            label = f"{acc.first_name or ''} {acc.phone or ''} (id={acc.id})".strip()
            self.account_combo.addItem(label, acc.id)
        layout.addRow("发送账号:", self.account_combo)

        self.group_combo = QComboBox()
        for grp in list_groups():
            self.group_combo.addItem(f"{grp.title or grp.tg_id}", grp.id)
        layout.addRow("目标群组:", self.group_combo)

        self.message = QTextEdit()
        self.message.setPlaceholderText("输入要发送的消息内容...")
        self.message.setMinimumHeight(80)
        layout.addRow("消息内容:", self.message)

        # 时间设置区域
        time_group = QGroupBox("发送时间设置")
        time_layout = QVBoxLayout(time_group)

        # 模式选择
        self.mode_daily = QRadioButton("每天固定时间发送")
        self.mode_weekly = QRadioButton("每周指定天发送")
        self.mode_interval = QRadioButton("每隔 X 分钟发送")
        self.mode_daily.setChecked(True)
        self.mode_group = QButtonGroup()
        self.mode_group.addButton(self.mode_daily)
        self.mode_group.addButton(self.mode_weekly)
        self.mode_group.addButton(self.mode_interval)

        mode_row = QHBoxLayout()
        mode_row.addWidget(self.mode_daily)
        mode_row.addWidget(self.mode_weekly)
        mode_row.addWidget(self.mode_interval)
        time_layout.addLayout(mode_row)

        # 时:分 选择器
        hm_row = QHBoxLayout()
        self.hour_spin = QSpinBox()
        self.hour_spin.setRange(0, 23)
        self.hour_spin.setValue(9)
        self.hour_spin.setSuffix(" 时")
        self.minute_spin = QSpinBox()
        self.minute_spin.setRange(0, 59)
        self.minute_spin.setValue(0)
        self.minute_spin.setSuffix(" 分")
        hm_row.addWidget(QLabel("时间:"))
        hm_row.addWidget(self.hour_spin)
        hm_row.addWidget(self.minute_spin)
        hm_row.addStretch()
        time_layout.addLayout(hm_row)

        # 星期选择（每周模式）
        self.weekday_group = QWidget()
        wd_layout = QHBoxLayout(self.weekday_group)
        wd_layout.setContentsMargins(0, 0, 0, 0)
        self.weekday_checks = []
        for i, name in enumerate(["周一","周二","周三","周四","周五","周六","周日"]):
            cb = QCheckBox(name)
            cb.setProperty("wd_value", str(i + 1) if i < 6 else "0")
            self.weekday_checks.append(cb)
            wd_layout.addWidget(cb)
        time_layout.addWidget(self.weekday_group)
        self.weekday_group.setVisible(False)

        # 间隔分钟（间隔模式）
        self.interval_widget = QWidget()
        iv_layout = QHBoxLayout(self.interval_widget)
        iv_layout.setContentsMargins(0, 0, 0, 0)
        iv_layout.addWidget(QLabel("每隔"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setValue(30)
        self.interval_spin.setSuffix(" 分钟")
        iv_layout.addWidget(self.interval_spin)
        iv_layout.addStretch()
        time_layout.addWidget(self.interval_widget)
        self.interval_widget.setVisible(False)

        # 预览
        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("color: #1976D2; font-weight: bold;")
        time_layout.addWidget(self.preview_label)

        layout.addRow(time_group)

        # 时区
        self.timezone = QComboBox()
        self.timezone.addItems(["Asia/Shanghai", "UTC", "America/New_York", "Europe/London"])
        layout.addRow("时区:", self.timezone)

        # 信号
        self.mode_daily.toggled.connect(self._update_mode)
        self.mode_weekly.toggled.connect(self._update_mode)
        self.mode_interval.toggled.connect(self._update_mode)
        self.hour_spin.valueChanged.connect(self._update_preview)
        self.minute_spin.valueChanged.connect(self._update_preview)
        self.interval_spin.valueChanged.connect(self._update_preview)
        for cb in self.weekday_checks:
            cb.stateChanged.connect(self._update_preview)

        self._update_preview()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _update_mode(self):
        is_weekly = self.mode_weekly.isChecked()
        is_interval = self.mode_interval.isChecked()
        self.weekday_group.setVisible(is_weekly)
        self.interval_widget.setVisible(is_interval)
        # 间隔模式不需要时分
        self.hour_spin.setEnabled(not is_interval)
        self.minute_spin.setEnabled(not is_interval)
        self._update_preview()

    def _update_preview(self):
        cron = self._get_cron()
        human = _cron_to_human(cron)
        self.preview_label.setText(f"执行计划：{human}  （cron: {cron}）")

    def _get_cron(self) -> str:
        hour = self.hour_spin.value()
        minute = self.minute_spin.value()
        if self.mode_daily.isChecked():
            mode = "daily"
            weekdays = []
        elif self.mode_weekly.isChecked():
            mode = "weekly"
            weekdays = [cb.property("wd_value") for cb in self.weekday_checks if cb.isChecked()]
            if not weekdays:
                weekdays = ["1"]
        else:
            mode = "interval"
            weekdays = []
        return _build_cron(mode, hour, minute, self.interval_spin.value(), weekdays)

    def get_values(self):
        return {
            "name": self.name.text().strip() or "未命名任务",
            "account_id": self.account_combo.currentData(),
            "group_id": self.group_combo.currentData(),
            "message_text": self.message.toPlainText().strip(),
            "cron_expr": self._get_cron(),
            "timezone": self.timezone.currentText(),
        }


class TaskTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        btn_row = QHBoxLayout()
        self.btn_new = QPushButton("新建任务")
        self.btn_toggle = QPushButton("启用/停用")
        self.btn_delete = QPushButton("删除任务")
        self.btn_refresh = QPushButton("刷新")
        for btn in [self.btn_new, self.btn_toggle, self.btn_delete, self.btn_refresh]:
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "ID", "名称", "账号ID", "群组ID", "执行计划", "状态", "下次执行", "执行/失败"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        self.btn_new.clicked.connect(self._on_new)
        self.btn_toggle.clicked.connect(self._on_toggle)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_refresh.clicked.connect(self.refresh_table)

    def refresh_table(self):
        tasks = list_tasks()
        self.table.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            next_run = scheduler.get_next_run(task.id)
            next_str = next_run.strftime("%m-%d %H:%M") if next_run else "未注册"

            self.table.setItem(row, 0, QTableWidgetItem(str(task.id)))
            self.table.setItem(row, 1, QTableWidgetItem(task.name or ""))
            self.table.setItem(row, 2, QTableWidgetItem(str(task.account_id)))
            self.table.setItem(row, 3, QTableWidgetItem(str(task.group_id)))
            self.table.setItem(row, 4, QTableWidgetItem(_cron_to_human(task.cron_expr)))

            active_item = QTableWidgetItem("启用" if task.is_active else "停用")
            active_item.setForeground(QColor("#4CAF50" if task.is_active else "#9E9E9E"))
            self.table.setItem(row, 5, active_item)

            # 下次执行：若 is_active 但显示"未注册"说明调度器里没有这条 job
            next_item = QTableWidgetItem(next_str)
            if task.is_active and next_str == "未注册":
                next_item.setForeground(QColor("#FF9800"))
            self.table.setItem(row, 6, next_item)

            self.table.setItem(row, 7, QTableWidgetItem(f"{task.run_count}/{task.fail_count}"))

    def _on_new(self):
        if not list_accounts():
            QMessageBox.warning(self, "提示", "请先在「账号管理」导入并验证账号")
            return
        if not list_groups():
            QMessageBox.warning(self, "提示", "请先在「群组管理」添加目标群组")
            return

        dlg = TaskDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        vals = dlg.get_values()
        if not vals["message_text"]:
            QMessageBox.warning(self, "提示", "消息内容不能为空")
            return
        try:
            task = create_task(**vals)
            next_run = scheduler.get_next_run(task.id)
            next_str = next_run.strftime("%m-%d %H:%M") if next_run else "未知"
            self.status_label.setText(
                f"任务已创建：{_cron_to_human(task.cron_expr)}，下次执行：{next_str}"
            )
            self.refresh_table()
        except Exception as e:
            QMessageBox.critical(self, "创建失败", str(e))

    def _on_toggle(self):
        ids = self._get_selected_ids()
        if not ids:
            self.status_label.setText("请先选中任务行")
            return
        tasks = {t.id: t for t in list_tasks()}
        for tid in ids:
            task = tasks.get(tid)
            if task:
                toggle_task(tid, not task.is_active)
        self.refresh_table()

    def _on_delete(self):
        ids = self._get_selected_ids()
        if not ids:
            return
        reply = QMessageBox.question(self, "确认", f"确认删除 {len(ids)} 个任务？")
        if reply == QMessageBox.Yes:
            for tid in ids:
                delete_task(tid)
            self.refresh_table()

    def _get_selected_ids(self):
        rows = set(idx.row() for idx in self.table.selectedIndexes())
        ids = []
        for row in rows:
            item = self.table.item(row, 0)
            if item:
                ids.append(int(item.text()))
        return ids
