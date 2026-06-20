"""
task_tab.py
定时任务管理界面。本地/远程模式均通过 services.proxy 调用。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QDialog, QFormLayout,
    QLineEdit, QComboBox, QTextEdit, QDialogButtonBox, QLabel,
    QSpinBox, QRadioButton, QButtonGroup, QGroupBox, QCheckBox,
    QScrollArea,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor

import json

from services.proxy import (
    create_task, delete_task, toggle_task, list_tasks, list_groups,
    list_accounts, switch_task_account, update_task_cron, batch_auto_reassign,
)
from gui.owner_filter import get_owner_filter
from config import SERVER_URL


def _build_cron(mode: str, hour: int, minute: int, interval_minutes: int, weekdays: list) -> str:
    if mode == "daily":
        return f"{minute} {hour} * * *"
    elif mode == "interval":
        if interval_minutes < 60:
            return f"*/{interval_minutes} * * * *"
        else:
            return f"0 */{interval_minutes // 60} * * *"
    elif mode == "weekly":
        days = ",".join(str(d) for d in weekdays) if weekdays else "1"
        return f"{minute} {hour} * * {days}"
    return f"{minute} {hour} * * *"


def _cron_to_human(cron: str) -> str:
    try:
        parts = cron.strip().split()
        if len(parts) != 5:
            return cron
        minute, hour, day, month, weekday = parts
        if weekday != "*" and day == "*":
            day_names = {
                "0": "周日", "1": "周一", "2": "周二", "3": "周三",
                "4": "周四", "5": "周五", "6": "周六", "7": "周日"
            }
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


class TaskWorker(QThread):
    finished = pyqtSignal(object)
    error    = pyqtSignal(str)

    def __init__(self, action, **kwargs):
        super().__init__()
        self.action = action
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.action(**self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class RefreshWorker(QThread):
    finished = pyqtSignal(list)
    error    = pyqtSignal(str)

    def run(self):
        try:
            self.finished.emit(list_tasks())
        except Exception as e:
            self.error.emit(str(e))


class BatchCreateWorker(QThread):
    progress = pyqtSignal(int, int)   # current, total
    finished = pyqtSignal(int, int)   # success, fail

    def __init__(self, tasks_params):
        super().__init__()
        self.tasks_params = tasks_params

    def run(self):
        success = fail = 0
        total = len(self.tasks_params)
        for i, params in enumerate(self.tasks_params, 1):
            try:
                create_task(**params)
                success += 1
            except Exception:
                fail += 1
            self.progress.emit(i, total)
        self.finished.emit(success, fail)


class BatchRescheduleWorker(QThread):
    progress = pyqtSignal(int, int)   # current, total
    finished = pyqtSignal(int, int)   # success, fail

    def __init__(self, task_ids: list, cron_expr: str):
        super().__init__()
        self.task_ids = task_ids
        self.cron_expr = cron_expr

    def run(self):
        success = fail = 0
        total = len(self.task_ids)
        for i, tid in enumerate(self.task_ids, 1):
            try:
                update_task_cron(tid, self.cron_expr)
                success += 1
            except Exception:
                fail += 1
            self.progress.emit(i, total)
        self.finished.emit(success, fail)


class BatchRescheduleDialog(QDialog):
    """为选中任务批量设置新的执行时间。"""

    def __init__(self, task_ids: list, tasks_map: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量修改发送时间")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        names = [tasks_map[tid].name or f"任务{tid}" for tid in task_ids if tid in tasks_map]
        summary = QLabel(f"将修改以下 {len(task_ids)} 个任务的执行计划：\n" + "、".join(names[:5])
                         + ("..." if len(names) > 5 else ""))
        summary.setWordWrap(True)
        summary.setStyleSheet("color: #555;")
        layout.addWidget(summary)

        time_group = QGroupBox("新发送时间")
        tl = QVBoxLayout(time_group)

        self.mode_daily    = QRadioButton("每天固定时间")
        self.mode_weekly   = QRadioButton("每周指定天")
        self.mode_interval = QRadioButton("每隔 X 分钟")
        self.mode_daily.setChecked(True)
        self._mode_group = QButtonGroup()
        for btn in [self.mode_daily, self.mode_weekly, self.mode_interval]:
            self._mode_group.addButton(btn)
        mode_row = QHBoxLayout()
        for btn in [self.mode_daily, self.mode_weekly, self.mode_interval]:
            mode_row.addWidget(btn)
        tl.addLayout(mode_row)

        hm_row = QHBoxLayout()
        self.hour_spin   = QSpinBox(); self.hour_spin.setRange(0, 23);  self.hour_spin.setValue(9);  self.hour_spin.setSuffix(" 时")
        self.minute_spin = QSpinBox(); self.minute_spin.setRange(0, 59); self.minute_spin.setValue(0); self.minute_spin.setSuffix(" 分")
        hm_row.addWidget(QLabel("时间:")); hm_row.addWidget(self.hour_spin); hm_row.addWidget(self.minute_spin); hm_row.addStretch()
        tl.addLayout(hm_row)

        self._wd_widget = QWidget()
        wd_layout = QHBoxLayout(self._wd_widget); wd_layout.setContentsMargins(0, 0, 0, 0)
        self.weekday_checks = []
        for i, n in enumerate(["周一", "周二", "周三", "周四", "周五", "周六", "周日"]):
            cb = QCheckBox(n); cb.setProperty("wd_value", str(i + 1) if i < 6 else "0")
            self.weekday_checks.append(cb); wd_layout.addWidget(cb)
        tl.addWidget(self._wd_widget); self._wd_widget.setVisible(False)

        self._iv_widget = QWidget()
        iv_layout = QHBoxLayout(self._iv_widget); iv_layout.setContentsMargins(0, 0, 0, 0)
        iv_layout.addWidget(QLabel("每隔"))
        self.interval_spin = QSpinBox(); self.interval_spin.setRange(1, 1440); self.interval_spin.setValue(10); self.interval_spin.setSuffix(" 分钟")
        iv_layout.addWidget(self.interval_spin); iv_layout.addStretch()
        tl.addWidget(self._iv_widget); self._iv_widget.setVisible(False)

        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("color: #1976D2; font-weight: bold;")
        tl.addWidget(self.preview_label)
        layout.addWidget(time_group)

        self.mode_daily.toggled.connect(self._update_mode)
        self.mode_weekly.toggled.connect(self._update_mode)
        self.mode_interval.toggled.connect(self._update_mode)
        self.hour_spin.valueChanged.connect(self._update_preview)
        self.minute_spin.valueChanged.connect(self._update_preview)
        self.interval_spin.valueChanged.connect(self._update_preview)
        for cb in self.weekday_checks:
            cb.stateChanged.connect(self._update_preview)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(f"确认修改 {len(task_ids)} 个任务")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_preview()

    def _update_mode(self):
        is_weekly = self.mode_weekly.isChecked()
        is_interval = self.mode_interval.isChecked()
        self._wd_widget.setVisible(is_weekly)
        self._iv_widget.setVisible(is_interval)
        self.hour_spin.setEnabled(not is_interval)
        self.minute_spin.setEnabled(not is_interval)
        self._update_preview()

    def _update_preview(self):
        cron = self.get_cron()
        self.preview_label.setText(f"执行计划：{_cron_to_human(cron)}  （cron: {cron}）")

    def get_cron(self) -> str:
        hour = self.hour_spin.value()
        minute = self.minute_spin.value()
        if self.mode_daily.isChecked():
            mode, weekdays = "daily", []
        elif self.mode_weekly.isChecked():
            mode = "weekly"
            weekdays = [cb.property("wd_value") for cb in self.weekday_checks if cb.isChecked()]
            if not weekdays:
                weekdays = ["1"]
        else:
            mode, weekdays = "interval", []
        return _build_cron(mode, hour, minute, self.interval_spin.value(), weekdays)


class TaskDetailDialog(QDialog):
    """双击任务行弹出的详情对话框：完整错误 + 换号历史。"""

    switch_requested = pyqtSignal()  # 用户点击了"更换账号"

    def __init__(self, task, accounts_map: dict, parent=None):
        super().__init__(parent)
        self.task = task
        self.setWindowTitle(f"任务详情 — {task.name or task.id}")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 基本信息
        form = QFormLayout()
        form.addRow("任务ID:", QLabel(str(task.id)))
        form.addRow("任务名称:", QLabel(task.name or ""))
        form.addRow("目标群组:", QLabel(f"群组 ID={task.group_id}"))
        acc_name = accounts_map.get(task.account_id, f"ID={task.account_id}")
        form.addRow("当前账号:", QLabel(acc_name))
        form.addRow("执行计划:", QLabel(_cron_to_human(task.cron_expr)))
        form.addRow("成功/失败:", QLabel(f"{task.run_count}/{task.fail_count}"))
        next_str = getattr(task, "next_run_str", None) or "未知"
        form.addRow("下次执行:", QLabel(next_str))
        layout.addLayout(form)

        # 最近错误
        last_error = getattr(task, "last_error", None) or ""
        if last_error:
            layout.addWidget(QLabel("最近错误:"))
            err_box = QLabel(last_error)
            err_box.setWordWrap(True)
            err_box.setStyleSheet(
                "color: #F44336; background: #FFF3F3; border: 1px solid #FFCDD2;"
                " border-radius: 4px; padding: 8px;"
            )
            layout.addWidget(err_box)

        # 换号历史
        layout.addWidget(QLabel("账号使用历史:"))
        history_table = QTableWidget(0, 3)
        history_table.setHorizontalHeaderLabels(["时间", "切换到账号", "原因"])
        history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        history_table.setMaximumHeight(160)

        raw = getattr(task, "account_history", None) or "[]"
        try:
            history = json.loads(raw)
        except Exception:
            history = []
        history_table.setRowCount(len(history))
        for r, entry in enumerate(history):
            acc_id = entry.get("account_id", "?")
            acc_label = accounts_map.get(acc_id, f"ID={acc_id}")
            history_table.setItem(r, 0, QTableWidgetItem(entry.get("time", "")))
            history_table.setItem(r, 1, QTableWidgetItem(acc_label))
            history_table.setItem(r, 2, QTableWidgetItem(entry.get("reason", "")))
        layout.addWidget(history_table)

        # 按钮行
        btn_row = QHBoxLayout()
        self.btn_switch = QPushButton("更换账号")
        self.btn_switch.setStyleSheet("font-weight: bold;")
        btn_close = QPushButton("关闭")
        btn_row.addWidget(self.btn_switch)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self.btn_switch.clicked.connect(lambda: (self.accept(), self.switch_requested.emit()))
        btn_close.clicked.connect(self.reject)


class SwitchAccountDialog(QDialog):
    """选择新账号并检测同群冲突、历史失败记录及跨分组风险。"""

    def __init__(self, task, accounts, all_tasks, parent=None):
        super().__init__(parent)
        self.task = task
        self.setWindowTitle(f"更换账号 — {task.name or task.id}")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        task_owner = getattr(task, "owner", "默认") or "默认"

        # ── 统计数据 ──────────────────────────────────────────────────
        task_counts         = {}
        same_group_accounts = set()
        group_failed_accounts = set()
        group_tried_accounts  = set()

        for t in all_tasks:
            if t.is_active and t.id != task.id:
                task_counts[t.account_id] = task_counts.get(t.account_id, 0) + 1
                if t.group_id == task.group_id:
                    same_group_accounts.add(t.account_id)

            if t.group_id == task.group_id:
                if not t.is_active:
                    group_failed_accounts.add(t.account_id)
                group_tried_accounts.add(t.account_id)
                try:
                    history = json.loads(getattr(t, "account_history", None) or "[]")
                    for entry in history:
                        old_id = entry.get("old_account_id")
                        if old_id:
                            group_tried_accounts.add(old_id)
                            reason = entry.get("reason", "")
                            if "燃尽" in reason or "失败" in reason or "换号" in reason:
                                group_failed_accounts.add(old_id)
                except Exception:
                    pass

        # 排序：同分组优先，其次未试过，再次任务数少
        def sort_key(a):
            acc_owner = getattr(a, "owner", "默认") or "默认"
            cross     = int(acc_owner != task_owner)          # 跨分组排最后
            failed    = int(a.id in group_failed_accounts)
            tried     = int(a.id in group_tried_accounts)
            count     = task_counts.get(a.id, 0)
            return (cross, failed * 2 + tried, count)

        accounts_sorted = sorted(accounts, key=sort_key)

        # ── UI ──────────────────────────────────────────────────────
        info = QLabel(f"当前任务：{task.name or task.id}（群组 ID={task.group_id}，归属：{task_owner}）")
        info.setStyleSheet("color: #666;")
        layout.addWidget(info)

        legend = QLabel(
            "标记说明：  ✅ 未在此群试过    ⚠ 此群曾被换掉    🚫 此群曾失败\n"
            "          ⛔ 跨归属分组（请勿选用，账号不属于你）"
        )
        legend.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(legend)

        layout.addWidget(QLabel("选择新账号："))
        self.combo = QComboBox()
        self._accounts_list       = accounts_sorted
        self._group_failed_accounts = group_failed_accounts
        self._group_tried_accounts  = group_tried_accounts
        self._same_group_accounts   = same_group_accounts
        self._task_owner            = task_owner

        for acc in accounts_sorted:
            acc_owner = getattr(acc, "owner", "默认") or "默认"
            count = task_counts.get(acc.id, 0)
            name  = (acc.first_name or acc.phone or f"id={acc.id}").strip()
            cross = acc_owner != task_owner

            if cross:
                group_badge = f"⛔ 跨分组[{acc_owner}]"
            elif acc.id in group_failed_accounts:
                group_badge = "🚫 此群曾失败"
            elif acc.id in group_tried_accounts:
                group_badge = "⚠ 此群曾换掉"
            else:
                group_badge = "✅ 未试过"

            load = "[空闲]" if count == 0 else f"[{count}个任务]"
            self.combo.addItem(f"{name}  {load}  {group_badge}", acc.id)

        layout.addWidget(self.combo)

        self.warn_label = QLabel()
        self.warn_label.setWordWrap(True)
        self.warn_label.setVisible(False)
        layout.addWidget(self.warn_label)

        self.combo.currentIndexChanged.connect(self._check_warnings)
        self._check_warnings()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _check_warnings(self):
        acc_id = self.combo.currentData()
        acc = next((a for a in self._accounts_list if a.id == acc_id), None)
        acc_owner = (getattr(acc, "owner", "默认") or "默认") if acc else "默认"
        msgs = []

        if acc_owner != self._task_owner:
            msgs.append(
                f"⛔ 此账号归属「{acc_owner}」，当前任务归属「{self._task_owner}」——这是跨分组操作！\n"
                "   强烈不建议选用：此账号可能属于你的合伙人，确认后任务归属也会被改为对方分组。"
            )
        elif acc_id in self._group_failed_accounts:
            msgs.append("🚫 此账号在该群曾经失败或被ban，换过去大概率仍会失败，建议选择「未试过」的账号。")
        elif acc_id in self._group_tried_accounts:
            msgs.append("⚠ 此账号在该群曾被换掉过，可能存在风险。")

        if acc_id in self._same_group_accounts:
            msgs.append("⚠ 此账号已有同一群组的活跃任务，会导致同群多账号发消息。")

        if msgs:
            is_critical = any("⛔" in m for m in msgs)
            is_red      = is_critical or any("🚫" in m for m in msgs)
            style = "#B71C1C" if is_critical else ("#F44336" if is_red else "#856404")
            bg    = "#FFEBEE" if is_red else "#FFF3CD"
            self.warn_label.setStyleSheet(
                f"color: {style}; background: {bg}; border-radius: 4px; padding: 8px;"
                " border: 1px solid currentColor;"
            )
            self.warn_label.setText("\n".join(msgs))
            self.warn_label.setVisible(True)
        else:
            self.warn_label.setVisible(False)

    def get_account_id(self) -> int:
        return self.combo.currentData()


class TaskDialog(QDialog):
    def __init__(self, parent=None, accounts=None, groups=None, task_counts=None):
        super().__init__(parent)
        self.setWindowTitle("新建定时消息任务")
        self.setMinimumWidth(500)
        layout = QFormLayout(self)
        layout.setSpacing(10)

        self._groups_list = groups or []
        self._name_auto = True  # 标记名称是否仍为自动填写状态

        task_counts = task_counts or {}
        self.account_combo = QComboBox()
        for acc in (accounts or []):
            count = task_counts.get(acc.id, 0)
            name = (acc.first_name or acc.phone or f"id={acc.id}").strip()
            tag = "[空闲]" if count == 0 else f"[{count}个任务]"
            self.account_combo.addItem(f"{name}  {tag}", acc.id)
        layout.addRow("发送账号:", self.account_combo)

        self.group_combo = QComboBox()
        for grp in self._groups_list:
            self.group_combo.addItem(f"{grp.title or grp.tg_id}", grp.id)
        layout.addRow("目标群组:", self.group_combo)

        self.name = QLineEdit()
        self.name.setPlaceholderText("自动填写群组名，可手动修改")
        layout.addRow("任务名称:", self.name)

        self.message = QTextEdit()
        self.message.setPlaceholderText("输入要发送的消息内容...")
        self.message.setMinimumHeight(80)
        layout.addRow("消息内容:", self.message)

        time_group = QGroupBox("发送时间设置")
        time_layout = QVBoxLayout(time_group)

        self.mode_daily    = QRadioButton("每天固定时间发送")
        self.mode_weekly   = QRadioButton("每周指定天发送")
        self.mode_interval = QRadioButton("每隔 X 分钟发送")
        self.mode_daily.setChecked(True)
        self.mode_group = QButtonGroup()
        for btn in [self.mode_daily, self.mode_weekly, self.mode_interval]:
            self.mode_group.addButton(btn)

        mode_row = QHBoxLayout()
        for btn in [self.mode_daily, self.mode_weekly, self.mode_interval]:
            mode_row.addWidget(btn)
        time_layout.addLayout(mode_row)

        hm_row = QHBoxLayout()
        self.hour_spin   = QSpinBox(); self.hour_spin.setRange(0, 23);  self.hour_spin.setValue(9);  self.hour_spin.setSuffix(" 时")
        self.minute_spin = QSpinBox(); self.minute_spin.setRange(0, 59); self.minute_spin.setValue(0); self.minute_spin.setSuffix(" 分")
        hm_row.addWidget(QLabel("时间:"))
        hm_row.addWidget(self.hour_spin)
        hm_row.addWidget(self.minute_spin)
        hm_row.addStretch()
        time_layout.addLayout(hm_row)

        self.weekday_group = QWidget()
        wd_layout = QHBoxLayout(self.weekday_group)
        wd_layout.setContentsMargins(0, 0, 0, 0)
        self.weekday_checks = []
        for i, name in enumerate(["周一", "周二", "周三", "周四", "周五", "周六", "周日"]):
            cb = QCheckBox(name)
            cb.setProperty("wd_value", str(i + 1) if i < 6 else "0")
            self.weekday_checks.append(cb)
            wd_layout.addWidget(cb)
        time_layout.addWidget(self.weekday_group)
        self.weekday_group.setVisible(False)

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

        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("color: #1976D2; font-weight: bold;")
        time_layout.addWidget(self.preview_label)

        layout.addRow(time_group)

        self.timezone = QComboBox()
        self.timezone.addItems(["Asia/Shanghai", "UTC", "America/New_York", "Europe/London"])
        layout.addRow("时区:", self.timezone)

        self.mode_daily.toggled.connect(self._update_mode)
        self.mode_weekly.toggled.connect(self._update_mode)
        self.mode_interval.toggled.connect(self._update_mode)
        self.hour_spin.valueChanged.connect(self._update_preview)
        self.minute_spin.valueChanged.connect(self._update_preview)
        self.interval_spin.valueChanged.connect(self._update_preview)
        for cb in self.weekday_checks:
            cb.stateChanged.connect(self._update_preview)
        self.group_combo.currentIndexChanged.connect(self._auto_fill_name)
        self.name.textEdited.connect(lambda: setattr(self, '_name_auto', False))

        self._update_preview()
        self._auto_fill_name()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _auto_fill_name(self):
        if not self._name_auto:
            return
        idx = self.group_combo.currentIndex()
        if 0 <= idx < len(self._groups_list):
            grp = self._groups_list[idx]
            self.name.setText(grp.title or grp.tg_id)

    def _update_mode(self):
        is_weekly   = self.mode_weekly.isChecked()
        is_interval = self.mode_interval.isChecked()
        self.weekday_group.setVisible(is_weekly)
        self.interval_widget.setVisible(is_interval)
        self.hour_spin.setEnabled(not is_interval)
        self.minute_spin.setEnabled(not is_interval)
        self._update_preview()

    def _update_preview(self):
        cron  = self._get_cron()
        human = _cron_to_human(cron)
        self.preview_label.setText(f"执行计划：{human}  （cron: {cron}）")

    def _get_cron(self) -> str:
        hour = self.hour_spin.value()
        minute = self.minute_spin.value()
        if self.mode_daily.isChecked():
            mode, weekdays = "daily", []
        elif self.mode_weekly.isChecked():
            mode = "weekly"
            weekdays = [cb.property("wd_value") for cb in self.weekday_checks if cb.isChecked()]
            if not weekdays:
                weekdays = ["1"]
        else:
            mode, weekdays = "interval", []
        return _build_cron(mode, hour, minute, self.interval_spin.value(), weekdays)

    def get_values(self):
        return {
            "name":         self.name.text().strip() or "未命名任务",
            "account_id":   self.account_combo.currentData(),
            "group_id":     self.group_combo.currentData(),
            "message_text": self.message.toPlainText().strip(),
            "cron_expr":    self._get_cron(),
            "timezone":     self.timezone.currentText(),
        }


class BatchTaskDialog(QDialog):
    def __init__(self, parent=None, accounts=None, groups=None, task_counts=None, group_task_counts=None):
        super().__init__(parent)
        self.setWindowTitle("批量分配任务")
        self.setMinimumWidth(660)
        self.setMinimumHeight(540)

        self._groups = groups or []
        self._task_counts = task_counts or {}
        self._group_task_counts = group_task_counts or {}  # 每个群已有的活跃任务数
        self._accounts_sorted = sorted(
            accounts or [],
            key=lambda a: self._task_counts.get(a.id, 0)
        )

        main = QVBoxLayout(self)
        main.setSpacing(10)

        # ── 消息内容 ──
        form = QFormLayout()
        self.message = QTextEdit()
        self.message.setMinimumHeight(80)
        self.message.setMaximumHeight(120)
        self.message.setPlaceholderText("输入要发送的消息内容（所有群组共用同一条消息）...")
        form.addRow("消息内容:", self.message)
        main.addLayout(form)

        # ── 时间设置 ──
        time_group = QGroupBox("发送时间设置")
        tl = QVBoxLayout(time_group)

        self.mode_daily    = QRadioButton("每天固定时间")
        self.mode_weekly   = QRadioButton("每周指定天")
        self.mode_interval = QRadioButton("每隔 X 分钟")
        self.mode_daily.setChecked(True)
        self._mode_group = QButtonGroup()
        for btn in [self.mode_daily, self.mode_weekly, self.mode_interval]:
            self._mode_group.addButton(btn)
        mode_row = QHBoxLayout()
        for btn in [self.mode_daily, self.mode_weekly, self.mode_interval]:
            mode_row.addWidget(btn)
        tl.addLayout(mode_row)

        hm_row = QHBoxLayout()
        self.hour_spin   = QSpinBox(); self.hour_spin.setRange(0, 23);  self.hour_spin.setValue(9);  self.hour_spin.setSuffix(" 时")
        self.minute_spin = QSpinBox(); self.minute_spin.setRange(0, 59); self.minute_spin.setValue(0); self.minute_spin.setSuffix(" 分")
        hm_row.addWidget(QLabel("时间:")); hm_row.addWidget(self.hour_spin); hm_row.addWidget(self.minute_spin); hm_row.addStretch()
        tl.addLayout(hm_row)

        self._wd_widget = QWidget()
        wd_layout = QHBoxLayout(self._wd_widget); wd_layout.setContentsMargins(0,0,0,0)
        self.weekday_checks = []
        for i, n in enumerate(["周一","周二","周三","周四","周五","周六","周日"]):
            cb = QCheckBox(n); cb.setProperty("wd_value", str(i+1) if i<6 else "0")
            self.weekday_checks.append(cb); wd_layout.addWidget(cb)
        tl.addWidget(self._wd_widget); self._wd_widget.setVisible(False)

        self._iv_widget = QWidget()
        iv_layout = QHBoxLayout(self._iv_widget); iv_layout.setContentsMargins(0,0,0,0)
        iv_layout.addWidget(QLabel("每隔"))
        self.interval_spin = QSpinBox(); self.interval_spin.setRange(1,1440); self.interval_spin.setValue(30); self.interval_spin.setSuffix(" 分钟")
        iv_layout.addWidget(self.interval_spin); iv_layout.addStretch()
        tl.addWidget(self._iv_widget); self._iv_widget.setVisible(False)

        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("color: #1976D2; font-weight: bold;")
        tl.addWidget(self.preview_label)
        main.addWidget(time_group)

        tz_row = QHBoxLayout()
        tz_row.addWidget(QLabel("时区:"))
        self.timezone = QComboBox()
        self.timezone.addItems(["Asia/Shanghai", "UTC", "America/New_York", "Europe/London"])
        tz_row.addWidget(self.timezone); tz_row.addStretch()
        main.addLayout(tz_row)

        # ── 群组分配列表 ──
        main.addWidget(QLabel("选择群组（自动分配空闲账号，可手动更换）："))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        rows_layout = QVBoxLayout(scroll_widget)
        rows_layout.setSpacing(4)
        rows_layout.setContentsMargins(4, 4, 4, 4)

        self._checks = []
        self._combos = []

        for grp in self._groups:
            row_widget = QWidget()
            row = QHBoxLayout(row_widget); row.setContentsMargins(0,0,0,0)

            existing = self._group_task_counts.get(grp.id, 0)
            cb_label = grp.title or grp.tg_id
            cb = QCheckBox(cb_label)
            cb.setChecked(True)
            cb.stateChanged.connect(self._update_confirm_btn)
            self._checks.append(cb)

            combo = QComboBox(); combo.setMinimumWidth(220)
            for acc in self._accounts_sorted:
                count = self._task_counts.get(acc.id, 0)
                name = (acc.first_name or acc.phone or f"id={acc.id}").strip()
                tag = "[空闲]" if count == 0 else f"[{count}个任务]"
                combo.addItem(f"{name}  {tag}", acc.id)
            self._combos.append(combo)

            row.addWidget(cb, 1)
            if existing > 0:
                warn = QLabel(f"⚠ 已有{existing}个任务")
                warn.setStyleSheet("color: #FF9800; font-size: 11px;")
                row.addWidget(warn)
            row.addWidget(combo)
            rows_layout.addWidget(row_widget)

        rows_layout.addStretch()
        scroll.setWidget(scroll_widget)
        main.addWidget(scroll)

        # ── 底部按钮 ──
        btn_row = QHBoxLayout()
        self.confirm_btn = QPushButton()
        self.confirm_btn.setStyleSheet("font-weight: bold; padding: 4px 16px;")
        cancel_btn = QPushButton("取消")
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.confirm_btn)
        main.addLayout(btn_row)

        # 连接信号
        self.mode_daily.toggled.connect(self._update_mode)
        self.mode_weekly.toggled.connect(self._update_mode)
        self.mode_interval.toggled.connect(self._update_mode)
        self.hour_spin.valueChanged.connect(self._update_preview)
        self.minute_spin.valueChanged.connect(self._update_preview)
        self.interval_spin.valueChanged.connect(self._update_preview)
        for cb in self.weekday_checks:
            cb.stateChanged.connect(self._update_preview)
        self.confirm_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)

        self._update_preview()
        self._update_confirm_btn()

    def _update_mode(self):
        is_weekly = self.mode_weekly.isChecked()
        is_interval = self.mode_interval.isChecked()
        self._wd_widget.setVisible(is_weekly)
        self._iv_widget.setVisible(is_interval)
        self.hour_spin.setEnabled(not is_interval)
        self.minute_spin.setEnabled(not is_interval)
        self._update_preview()

    def _update_preview(self):
        cron = self._get_cron()
        self.preview_label.setText(f"执行计划：{_cron_to_human(cron)}  （cron: {cron}）")

    def _get_cron(self) -> str:
        hour = self.hour_spin.value()
        minute = self.minute_spin.value()
        if self.mode_daily.isChecked():
            mode, weekdays = "daily", []
        elif self.mode_weekly.isChecked():
            mode = "weekly"
            weekdays = [cb.property("wd_value") for cb in self.weekday_checks if cb.isChecked()]
            if not weekdays:
                weekdays = ["1"]
        else:
            mode, weekdays = "interval", []
        return _build_cron(mode, hour, minute, self.interval_spin.value(), weekdays)

    def _update_confirm_btn(self):
        count = sum(1 for cb in self._checks if cb.isChecked())
        self.confirm_btn.setText(f"确认创建 {count} 个任务")
        self.confirm_btn.setEnabled(count > 0)

    def get_batch_tasks(self) -> list:
        cron = self._get_cron()
        tz   = self.timezone.currentText()
        msg  = self.message.toPlainText().strip()
        result = []
        for i, (cb, combo) in enumerate(zip(self._checks, self._combos)):
            if cb.isChecked():
                grp = self._groups[i]
                result.append({
                    "name":         grp.title or grp.tg_id,
                    "account_id":   combo.currentData(),
                    "group_id":     grp.id,
                    "message_text": msg,
                    "cron_expr":    cron,
                    "timezone":     tz,
                })
        return result


class TaskTab(QWidget):
    def __init__(self):
        super().__init__()
        self._worker = None
        self._tasks = {}
        self._build_ui()
        self.refresh_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        btn_row = QHBoxLayout()
        self.btn_new         = QPushButton("新建任务")
        self.btn_batch       = QPushButton("批量分配")
        self.btn_toggle      = QPushButton("启用/停用")
        self.btn_switch      = QPushButton("更换账号")
        self.btn_reschedule  = QPushButton("批量改时间")
        self.btn_auto_switch = QPushButton("一键换号")
        self.btn_delete      = QPushButton("删除任务")
        self.btn_refresh     = QPushButton("刷新")
        self.btn_batch.setStyleSheet("font-weight: bold;")
        self.btn_auto_switch.setStyleSheet(
            "background: #FF5722; color: white; font-weight: bold; padding: 4px 8px;"
        )
        self.btn_auto_switch.setToolTip("为所有停用任务自动分配空闲账号，将燃尽账号标为养号中")
        for btn in [self.btn_new, self.btn_batch, self.btn_toggle,
                    self.btn_switch, self.btn_reschedule, self.btn_auto_switch,
                    self.btn_delete, self.btn_refresh]:
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 分组筛选：过滤任务列表 + 限定新建任务时的账号选择范围
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("分组筛选："))
        self.owner_filter_combo = QComboBox()
        self.owner_filter_combo.setMinimumWidth(160)
        self.owner_filter_combo.setToolTip(
            "筛选仅显示该归属分组的任务。\n"
            "新建任务/批量分配时，也只列出该分组的账号供选择。\n"
            "一键换号已在数据层按每个任务自身归属隔离，无需此处设置。"
        )
        self.owner_filter_combo.addItem("全部", "")
        self.owner_filter_combo.currentIndexChanged.connect(self._on_owner_filter_changed)
        filter_row.addWidget(self.owner_filter_combo)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "ID", "名称", "归属", "账号ID", "群组ID", "执行计划", "状态", "下次执行", "执行/失败", "最近错误"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        self.btn_new.clicked.connect(self._on_new)
        self.btn_batch.clicked.connect(self._on_batch)
        self.btn_toggle.clicked.connect(self._on_toggle)
        self.btn_switch.clicked.connect(self._on_switch)
        self.btn_reschedule.clicked.connect(self._on_reschedule)
        self.btn_auto_switch.clicked.connect(self._on_auto_switch)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_refresh.clicked.connect(self.refresh_table)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)

    def _on_owner_filter_changed(self):
        self._populate_table(list(self._tasks.values()))

    def refresh_table(self):
        if hasattr(self, '_refresh_worker') and self._refresh_worker.isRunning():
            return
        worker = RefreshWorker()
        worker.finished.connect(self._populate_table)
        worker.error.connect(lambda e: self.status_label.setText(f"刷新失败: {e}"))
        self._refresh_worker = worker
        worker.start()

    def _populate_table(self, tasks):
        self._tasks = {t.id: t for t in tasks}

        # 更新分组筛选 combo
        owners = sorted({getattr(t, "owner", "默认") or "默认" for t in tasks})
        current_owner = self.owner_filter_combo.currentData() or ""
        self.owner_filter_combo.blockSignals(True)
        self.owner_filter_combo.clear()
        self.owner_filter_combo.addItem("全部", "")
        for o in owners:
            self.owner_filter_combo.addItem(o, o)
        idx = self.owner_filter_combo.findData(current_owner)
        if idx >= 0:
            self.owner_filter_combo.setCurrentIndex(idx)
        self.owner_filter_combo.blockSignals(False)

        owner_filter = self.owner_filter_combo.currentData() or ""
        visible = [t for t in tasks
                   if not owner_filter or (getattr(t, "owner", "默认") or "默认") == owner_filter]

        self.table.setRowCount(len(visible))
        for row, task in enumerate(visible):
            if hasattr(task, "next_run_str"):
                next_str = task.next_run_str or "未注册"
            else:
                import core.scheduler as scheduler
                next_run = scheduler.get_next_run(task.id)
                next_str = next_run.strftime("%m-%d %H:%M") if next_run else "未注册"

            task_owner = getattr(task, "owner", "默认") or "默认"

            self.table.setItem(row, 0, QTableWidgetItem(str(task.id)))
            self.table.setItem(row, 1, QTableWidgetItem(task.name or ""))

            owner_item = QTableWidgetItem(task_owner)
            owner_item.setForeground(QColor("#1565C0"))
            font = owner_item.font(); font.setBold(True); owner_item.setFont(font)
            self.table.setItem(row, 2, owner_item)

            self.table.setItem(row, 3, QTableWidgetItem(str(task.account_id)))
            self.table.setItem(row, 4, QTableWidgetItem(str(task.group_id)))
            self.table.setItem(row, 5, QTableWidgetItem(_cron_to_human(task.cron_expr)))

            active_item = QTableWidgetItem("启用" if task.is_active else "停用")
            active_item.setForeground(QColor("#4CAF50" if task.is_active else "#9E9E9E"))
            self.table.setItem(row, 6, active_item)

            next_item = QTableWidgetItem(next_str)
            if task.is_active and next_str == "未注册":
                next_item.setForeground(QColor("#FF9800"))
            self.table.setItem(row, 7, next_item)

            self.table.setItem(row, 8, QTableWidgetItem(
                f"{task.run_count}/{task.fail_count}"
            ))

            last_error = getattr(task, "last_error", None) or ""
            err_item = QTableWidgetItem(last_error)
            if last_error:
                err_item.setForeground(QColor("#F44336"))
            self.table.setItem(row, 9, err_item)

    def _set_buttons(self, enabled: bool):
        for btn in [self.btn_new, self.btn_batch, self.btn_toggle,
                    self.btn_switch, self.btn_reschedule, self.btn_auto_switch, self.btn_delete]:
            btn.setEnabled(enabled)

    def _on_new(self):
        self._set_buttons(False)
        self.status_label.setText("加载中...")

        def fetch():
            return list_accounts(), list_groups(), list_tasks()

        self._fetch_worker = TaskWorker(fetch)
        self._fetch_worker.finished.connect(self._on_fetch_done)
        self._fetch_worker.error.connect(lambda e: (
            self._set_buttons(True),
            self.status_label.setText(""),
            QMessageBox.critical(self, "错误", e),
        ))
        self._fetch_worker.start()

    def _refresh_owner_combo(self, accounts):
        """用账号列表更新归属分组筛选 combo。"""
        owners = sorted({getattr(a, "owner", "默认") or "默认" for a in accounts})
        current = self.owner_filter_combo.currentData()
        self.owner_filter_combo.blockSignals(True)
        self.owner_filter_combo.clear()
        self.owner_filter_combo.addItem("全部账号", "")
        for o in owners:
            self.owner_filter_combo.addItem(o, o)
        idx = self.owner_filter_combo.findData(current)
        if idx >= 0:
            self.owner_filter_combo.setCurrentIndex(idx)
        self.owner_filter_combo.blockSignals(False)

    def _filter_accounts_by_owner(self, accounts: list) -> list:
        owner = self.owner_filter_combo.currentData() or ""
        if not owner:
            return accounts
        return [a for a in accounts if getattr(a, "owner", "默认") == owner]

    def _on_fetch_done(self, result):
        self._set_buttons(True)
        self.status_label.setText("")
        accounts, groups, tasks = result
        if not accounts:
            QMessageBox.warning(self, "提示", "请先在「账号管理」导入并验证账号")
            return
        if not groups:
            QMessageBox.warning(self, "提示", "请先在「群组管理」添加目标群组")
            return

        self._refresh_owner_combo(accounts)
        accounts = self._filter_accounts_by_owner(accounts)
        if not accounts:
            QMessageBox.warning(self, "提示", "当前归属分组筛选下没有可用账号，请在「账号管理」设置账号归属或切换「全部账号」")
            return

        # 统计每个账号当前任务数，空闲账号排前面
        task_counts = {}
        for t in tasks:
            if t.is_active:
                task_counts[t.account_id] = task_counts.get(t.account_id, 0) + 1
        accounts_sorted = sorted(accounts, key=lambda a: task_counts.get(a.id, 0))

        dlg = TaskDialog(self, accounts=accounts_sorted, groups=groups, task_counts=task_counts)
        if dlg.exec_() != QDialog.Accepted:
            return
        vals = dlg.get_values()
        if not vals["message_text"]:
            QMessageBox.warning(self, "提示", "消息内容不能为空")
            return
        self._set_buttons(False)
        self.status_label.setText("正在创建任务...")
        self._worker = TaskWorker(create_task, **vals)
        self._worker.finished.connect(self._on_create_done)
        self._worker.error.connect(self._on_action_error)
        self._worker.start()

    def _on_create_done(self, task):
        self._set_buttons(True)
        if hasattr(task, "next_run_str"):
            next_str = task.next_run_str or "未知"
        else:
            import core.scheduler as scheduler
            next_run = scheduler.get_next_run(task.id)
            next_str = next_run.strftime("%m-%d %H:%M") if next_run else "未知"
        self.status_label.setText(
            f"任务已创建：{_cron_to_human(task.cron_expr)}，下次执行：{next_str}"
        )
        self.refresh_table()

    def _on_toggle(self):
        ids = self._get_selected_ids()
        if not ids:
            self.status_label.setText("请先选中任务行")
            return
        self._set_buttons(False)

        def do_toggle():
            for tid in ids:
                task = self._tasks.get(tid)
                if task:
                    toggle_task(tid, not task.is_active)
            return None

        self._worker = TaskWorker(do_toggle)
        self._worker.finished.connect(lambda _: (self._set_buttons(True), self.refresh_table()))
        self._worker.error.connect(self._on_action_error)
        self._worker.start()

    def _on_delete(self):
        ids = self._get_selected_ids()
        if not ids:
            return
        reply = QMessageBox.question(self, "确认", f"确认删除 {len(ids)} 个任务？")
        if reply != QMessageBox.Yes:
            return
        self._set_buttons(False)
        self.status_label.setText("正在删除...")

        def do_delete():
            for tid in ids:
                delete_task(tid)
            return None

        self._worker = TaskWorker(do_delete)
        self._worker.finished.connect(lambda _: (self._set_buttons(True), self.status_label.setText(""), self.refresh_table()))
        self._worker.error.connect(self._on_action_error)
        self._worker.start()

    def _on_batch(self):
        self._set_buttons(False)
        self.status_label.setText("加载中...")

        def fetch():
            return list_accounts(), list_groups(), list_tasks()

        self._batch_fetch_worker = TaskWorker(fetch)
        self._batch_fetch_worker.finished.connect(self._on_batch_fetch_done)
        self._batch_fetch_worker.error.connect(lambda e: (
            self._set_buttons(True),
            self.status_label.setText(""),
            QMessageBox.critical(self, "错误", e),
        ))
        self._batch_fetch_worker.start()

    def _on_batch_fetch_done(self, result):
        self._set_buttons(True)
        self.status_label.setText("")
        accounts, groups, tasks = result

        if not accounts:
            QMessageBox.warning(self, "提示", "请先在「账号管理」导入并验证账号")
            return
        if not groups:
            QMessageBox.warning(self, "提示", "请先在「群组管理」添加目标群组")
            return

        self._refresh_owner_combo(accounts)
        accounts = self._filter_accounts_by_owner(accounts)
        if not accounts:
            QMessageBox.warning(self, "提示", "当前归属分组筛选下没有可用账号，请在「账号管理」设置账号归属或切换「全部账号」")
            return

        task_counts = {}        # 每个账号的活跃任务数
        group_task_counts = {}  # 每个群组的活跃任务数
        for t in tasks:
            if t.is_active:
                task_counts[t.account_id] = task_counts.get(t.account_id, 0) + 1
                group_task_counts[t.group_id] = group_task_counts.get(t.group_id, 0) + 1
        accounts_sorted = sorted(accounts, key=lambda a: task_counts.get(a.id, 0))

        dlg = BatchTaskDialog(self, accounts=accounts_sorted, groups=groups,
                              task_counts=task_counts, group_task_counts=group_task_counts)
        if dlg.exec_() != QDialog.Accepted:
            return
        if not dlg.message.toPlainText().strip():
            QMessageBox.warning(self, "提示", "消息内容不能为空")
            return

        tasks_params = dlg.get_batch_tasks()
        if not tasks_params:
            return

        self._set_buttons(False)
        self.status_label.setText(f"正在创建 {len(tasks_params)} 个任务...")
        self._batch_worker = BatchCreateWorker(tasks_params)
        self._batch_worker.progress.connect(
            lambda cur, total: self.status_label.setText(f"正在创建 {cur}/{total}...")
        )
        self._batch_worker.finished.connect(self._on_batch_done)
        self._batch_worker.start()

    def _on_batch_done(self, success, fail):
        self._set_buttons(True)
        msg = f"批量创建完成：成功 {success} 个"
        if fail:
            msg += f"，失败 {fail} 个"
        self.status_label.setText(msg)
        self.refresh_table()

    # ── 双击查看详情 ────────────────────────────────────────────────────

    def _on_row_double_clicked(self, row: int, _col: int):
        item = self.table.item(row, 0)
        if not item:
            return
        task_id = int(item.text())
        task = self._tasks.get(task_id)
        if not task:
            return
        # 用已有账号列表构建 id→名字 映射（_fetch_worker 数据可能有，否则异步拉）
        self._open_detail(task)

    def _open_detail(self, task):
        self._set_buttons(False)
        self.status_label.setText("加载中...")

        def fetch():
            return list_accounts(), list_tasks()

        self._detail_fetch_worker = TaskWorker(fetch)
        self._detail_fetch_worker.finished.connect(
            lambda r: self._show_detail_dialog(task, r)
        )
        self._detail_fetch_worker.error.connect(lambda e: (
            self._set_buttons(True),
            self.status_label.setText(""),
            QMessageBox.critical(self, "错误", e),
        ))
        self._detail_fetch_worker.start()

    def _show_detail_dialog(self, task, fetch_result):
        self._set_buttons(True)
        self.status_label.setText("")
        accounts, all_tasks = fetch_result
        accounts_map = {}
        for acc in accounts:
            name = (acc.first_name or acc.phone or f"id={acc.id}").strip()
            accounts_map[acc.id] = f"{name} (ID={acc.id})"

        dlg = TaskDetailDialog(task, accounts_map, self)
        dlg.switch_requested.connect(
            lambda: self._open_switch_dialog(task, accounts, all_tasks)
        )
        dlg.exec_()

    # ── 更换账号 ────────────────────────────────────────────────────────

    def _on_switch(self):
        ids = self._get_selected_ids()
        if len(ids) != 1:
            self.status_label.setText("请先选中一个任务行再点更换账号")
            return
        task = self._tasks.get(ids[0])
        if not task:
            return
        self._open_detail(task)  # 复用详情加载，从详情里点换号

    def _open_switch_dialog(self, task, accounts, all_tasks):
        dlg = SwitchAccountDialog(task, accounts, all_tasks, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        new_account_id = dlg.get_account_id()
        if new_account_id == task.account_id:
            self.status_label.setText("账号未变更")
            return

        self._set_buttons(False)
        self.status_label.setText("正在更换账号...")
        self._switch_worker = TaskWorker(
            switch_task_account, task_id=task.id,
            new_account_id=new_account_id, reason="手动更换"
        )
        self._switch_worker.finished.connect(self._on_switch_done)
        self._switch_worker.error.connect(self._on_action_error)
        self._switch_worker.start()

    def _on_switch_done(self, task):
        self._set_buttons(True)
        self.status_label.setText(f"账号已更换，任务 {task.name or task.id} 错误已清除")
        self.refresh_table()

    def _on_auto_switch(self):
        stopped = [t for t in self._tasks.values() if not t.is_active]
        if not stopped:
            self.status_label.setText("没有停用的任务，无需换号")
            return

        by_owner = {}
        for t in stopped:
            o = getattr(t, "owner", "默认") or "默认"
            by_owner[o] = by_owner.get(o, 0) + 1
        owner_summary = "\n".join(f"  • {o}：{n} 个任务" for o, n in sorted(by_owner.items()))

        dlg = QDialog(self)
        dlg.setWindowTitle("一键换号")
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel(
            f"发现 {len(stopped)} 个停用任务：\n{owner_summary}"
        ))

        layout.addWidget(QLabel("\n选择使用哪个分组的账号来替换："))
        combo = QComboBox()
        combo.addItem("按任务自身归属分组（不跨组）", "")
        try:
            all_accs = list_accounts()
            all_owners = sorted({getattr(a, "owner", "默认") or "默认" for a in all_accs})
        except Exception:
            all_owners = sorted(by_owner.keys())
        for o in all_owners:
            combo.addItem(f"统一使用「{o}」分组的账号", o)
        layout.addWidget(combo)

        tip = QLabel(
            "\n操作内容：\n"
            "① 为每个停用任务分配所选分组内的空闲账号\n"
            "② 将原来燃尽的账号标为「养号中」\n"
            "③ 自动重新启用这些任务"
        )
        tip.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(tip)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("执行换号")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec_() != QDialog.Accepted:
            return

        target_owner = combo.currentData() or ""
        self._set_buttons(False)
        self.status_label.setText("正在一键换号...")
        self._auto_switch_worker = TaskWorker(
            batch_auto_reassign, target_owner=target_owner)
        self._auto_switch_worker.finished.connect(self._on_auto_switch_done)
        self._auto_switch_worker.error.connect(self._on_action_error)
        self._auto_switch_worker.start()

    def _on_auto_switch_done(self, result: dict):
        self._set_buttons(True)
        if result.get("no_accounts"):
            QMessageBox.warning(
                self, "无可用账号",
                "所有停用任务的归属分组内均无空闲账号！\n"
                "请先在「账号管理」导入新账号（设置正确的归属分组），\n"
                "或解除部分账号的养号状态。"
            )
            self.status_label.setText("换号失败：无可用账号")
            return
        n       = result.get("reassigned", 0)
        r       = len(result.get("rested", []))
        skipped = result.get("skipped", [])
        msg = f"一键换号完成：{n} 个任务已重新分配并启用，{r} 个燃尽账号已标为养号中"
        if skipped:
            msg += f"\n⚠ {len(skipped)} 个任务因本组无空闲账号被跳过（任务ID：{skipped}）"
            QMessageBox.warning(self, "部分任务跳过", msg)
        self.status_label.setText(msg.split("\n")[0])
        self.refresh_table()

    def _on_reschedule(self):
        ids = self._get_selected_ids()
        if not ids:
            self.status_label.setText("请先选中至少一个任务行")
            return
        dlg = BatchRescheduleDialog(ids, self._tasks, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        cron = dlg.get_cron()
        self._set_buttons(False)
        self.status_label.setText(f"正在修改 {len(ids)} 个任务的时间...")
        self._reschedule_worker = BatchRescheduleWorker(ids, cron)
        self._reschedule_worker.progress.connect(
            lambda cur, total: self.status_label.setText(f"正在修改 {cur}/{total}...")
        )
        self._reschedule_worker.finished.connect(self._on_reschedule_done)
        self._reschedule_worker.start()

    def _on_reschedule_done(self, success, fail):
        self._set_buttons(True)
        msg = f"修改完成：成功 {success} 个"
        if fail:
            msg += f"，失败 {fail} 个"
        self.status_label.setText(msg)
        self.refresh_table()

    def _on_action_error(self, msg):
        self._set_buttons(True)
        self.status_label.setText("")
        QMessageBox.critical(self, "操作失败", msg)

    def _get_selected_ids(self):
        rows = set(idx.row() for idx in self.table.selectedIndexes())
        ids = []
        for row in rows:
            item = self.table.item(row, 0)
            if item:
                ids.append(int(item.text()))
        return ids
