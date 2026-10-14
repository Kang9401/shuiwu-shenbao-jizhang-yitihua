import datetime as dt
import json
import re
import sys
from pathlib import Path

from PyQt6.QtCore import QProcess, QProcessEnvironment, Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QRadioButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from etax_batch_export import TaxOrg, default_month, read_orgs_from_excel


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
WORK_DIR = APP_DIR
DEFAULT_ORG_EXCEL = WORK_DIR / "机构信息表.xlsx"
CDP_URL = "http://127.0.0.1:9222"
TASK_SPECIAL_DEDUCTION_SCRIPT = WORK_DIR / "etax_batch_export.py"
TASK_IMPORT_SCRIPT = WORK_DIR / "etax_batch_import.py"
TASK_TAX_CERTIFICATE_SCRIPT = WORK_DIR / "etax_tax_certificate_download.py"
TASK_SPECIAL_DEDUCTION_EXE = WORK_DIR / "etax_batch_export.exe"
TASK_IMPORT_EXE = WORK_DIR / "etax_batch_import.exe"
TASK_TAX_CERTIFICATE_EXE = WORK_DIR / "etax_tax_certificate_download.exe"
OUTPUT_DIR = WORK_DIR / "output"
START_DEBUG_CHROME_SCRIPT = WORK_DIR / "start_debug_chrome.ps1"
DEFAULT_CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CONFIG_PATH = WORK_DIR / "etax_config.json"


def month_options() -> list[str]:
    today = dt.date.today().replace(day=1)
    months: list[str] = []
    for offset in range(-6, 7):
        year = today.year + (today.month - 1 + offset) // 12
        month = (today.month - 1 + offset) % 12 + 1
        months.append(f"{year}-{month:02d}")
    return months


def add_months(month: str, offset: int) -> str:
    year, month_num = [int(part) for part in month.split("-", 1)]
    index = year * 12 + month_num - 1 + offset
    return f"{index // 12}-{index % 12 + 1:02d}"


def previous_month() -> str:
    today = dt.date.today().replace(day=1)
    return add_months(f"{today.year}-{today.month:02d}", -1)


def decode_process_output(data) -> str:
    raw = bytes(data)
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def load_app_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_app_config(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    tmp_path = CONFIG_PATH.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    tmp_path.replace(CONFIG_PATH)


class OrgPreviewDialog(QDialog):
    def __init__(self, orgs: list[TaxOrg], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("确认执行机构")
        self.resize(620, 420)

        layout = QVBoxLayout(self)
        summary = QLabel(f"请确认本次将处理以下 {len(orgs)} 个机构。确认后程序开始执行。")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        table = QTableWidget(len(orgs), 2)
        table.setHorizontalHeaderLabels(["机构代码", "机构名称"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for row, org in enumerate(orgs):
            table.setItem(row, 0, QTableWidgetItem(org.code))
            table.setItem(row, 1, QTableWidgetItem(org.name))
        layout.addWidget(table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认执行")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("自然人电子税务局自动化工具")
        self.resize(1320, 760)
        self.process: QProcess | None = None
        self.init_process: QProcess | None = None
        self.result_rows: dict[str, int] = {}
        self.current_run_task: str | None = None
        self.current_org_code: str | None = None
        self.current_run_started_at: dt.datetime | None = None
        self.current_run_month: str | None = None
        self.last_failed_task_key: str | None = None
        self.last_failed_org_code: str | None = None
        self.current_counts: dict[tuple[str, str], int] = {}
        self.org_excel_path = DEFAULT_ORG_EXCEL
        self.app_config = load_app_config()
        self.task_columns = {
            "special_deduction": 2,
            "import": 3,
            "tax_certificate": 4,
            "income_report": 5,
        }

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("自然人电子税务局自动化工具")
        title.setObjectName("Title")
        root.addWidget(title)

        content = QHBoxLayout()
        content.setSpacing(14)

        left_panel = QWidget()
        left_panel.setObjectName("LeftPanel")
        left_panel.setFixedWidth(440)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        left_layout.addWidget(self.build_param_group())
        left_layout.addWidget(self.build_task_group(), stretch=1)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)
        right_layout.addWidget(self.build_result_group(), stretch=2)
        right_layout.addWidget(self.build_log_group(), stretch=3)

        content.addWidget(left_panel, stretch=0)
        content.addWidget(right_panel, stretch=1)
        root.addLayout(content, stretch=1)

        self.apply_style()
        self.update_org_input_state()
        self.refresh_month_views()
        self.resize_result_columns()

    def build_param_group(self) -> QGroupBox:
        group = QGroupBox("操作参数")
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)
        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 1)

        self.month_combo = QComboBox()
        self.month_combo.setEditable(True)
        self.month_combo.addItems(month_options())
        self.month_combo.currentTextChanged.connect(lambda: self.refresh_month_views())
        current_month = previous_month()
        index = self.month_combo.findText(current_month)
        if index >= 0:
            self.month_combo.setCurrentIndex(index)
        else:
            self.month_combo.setEditText(current_month)

        self.all_orgs_checkbox = QRadioButton("是")
        self.partial_orgs_radio = QRadioButton("否")
        self.org_scope_group = QButtonGroup(self)
        self.org_scope_group.addButton(self.all_orgs_checkbox)
        self.org_scope_group.addButton(self.partial_orgs_radio)
        self.all_orgs_checkbox.setChecked(True)
        self.all_orgs_checkbox.toggled.connect(self.update_org_input_state)
        self.partial_orgs_radio.toggled.connect(self.update_org_input_state)
        org_scope_row = QHBoxLayout()
        org_scope_row.setContentsMargins(0, 0, 0, 0)
        org_scope_row.setSpacing(18)
        org_scope_row.addWidget(self.all_orgs_checkbox)
        org_scope_row.addWidget(self.partial_orgs_radio)
        org_scope_row.addStretch(1)

        self.org_code_input = QLineEdit()
        self.org_code_input.setPlaceholderText("选择否后输入机构代码，例如 11818")
        self.org_code_input.textChanged.connect(lambda: self.refresh_result_table())

        self.org_excel_input = QLineEdit(str(DEFAULT_ORG_EXCEL))
        self.org_excel_input.setReadOnly(True)
        self.org_excel_button = QPushButton("选择")
        self.org_excel_button.setFixedWidth(72)
        self.org_excel_button.clicked.connect(self.choose_org_excel)
        org_excel_row = QHBoxLayout()
        org_excel_row.setContentsMargins(0, 0, 0, 0)
        org_excel_row.setSpacing(8)
        org_excel_row.addWidget(self.org_excel_input, stretch=1)
        org_excel_row.addWidget(self.org_excel_button)

        self.chrome_path_input = QLineEdit(str(self.app_config.get("chrome_path") or DEFAULT_CHROME_PATH))
        self.chrome_path_input.setPlaceholderText(r"例如 C:\Program Files\Google\Chrome\Application\chrome.exe")
        self.chrome_path_input.editingFinished.connect(self.save_chrome_path_config)
        chrome_hint = QLabel("如果浏览器初始化失败，请粘贴本机 chrome.exe 的完整路径，重新初始化。")
        chrome_hint.setObjectName("Hint")
        chrome_hint.setWordWrap(True)

        layout.addWidget(QLabel("申报月份"), 0, 0)
        layout.addWidget(self.month_combo, 0, 1)
        layout.addWidget(QLabel("申报机构"), 1, 0)
        layout.addLayout(org_excel_row, 1, 1)
        layout.addWidget(QLabel("处理全部"), 2, 0)
        layout.addLayout(org_scope_row, 2, 1)
        layout.addWidget(QLabel("指定机构"), 3, 0)
        layout.addWidget(self.org_code_input, 3, 1)
        layout.addWidget(QLabel("Chrome地址"), 4, 0)
        layout.addWidget(self.chrome_path_input, 4, 1)
        layout.addWidget(chrome_hint, 5, 1)
        return group

    def build_task_group(self) -> QGroupBox:
        group = QGroupBox("执行任务")
        layout = QVBoxLayout(group)

        self.init_button = QPushButton("初始化")
        self.init_button.clicked.connect(self.initialize_chrome)
        layout.addLayout(
            self.build_step_row(
                "步骤 1",
                "浏览器初始化",
                self.init_button,
                "启动可接管的 Chrome。启动后请在该窗口手工登录自然人电子税务局。",
            )
        )
        layout.addWidget(self.separator())

        self.task1_button = QPushButton("开始")
        self.task1_button.clicked.connect(lambda: self.prepare_and_run("special_deduction"))
        if not self.special_deduction_backend_exists():
            self.task1_button.setText("待配置")
            self.task1_button.setEnabled(False)
        layout.addLayout(
            self.build_step_row(
                "步骤 2",
                "专项附加导出",
                self.task1_button,
                "批量导出专项附加扣除文件。执行前会校验月份和机构 Excel。"
                if self.special_deduction_backend_exists()
                else "批量导出专项附加扣除文件。当前缺少导出后端程序。",
            )
        )
        layout.addWidget(self.separator())

        self.task2_button = QPushButton("开始")
        self.task2_button.clicked.connect(lambda: self.prepare_and_run("import"))
        layout.addLayout(
            self.build_step_row(
                "步骤 3",
                "导入数据",
                self.task2_button,
                "从 input 目录按机构代码前缀匹配文件，批量导入人员信息、工资薪金、劳务报酬、奖金等文件。",
            )
        )
        layout.addWidget(self.separator())

        self.tax_cert_button = QPushButton("开始")
        self.tax_cert_button.clicked.connect(lambda: self.prepare_and_run("tax_certificate"))
        layout.addLayout(
            self.build_step_row(
                "步骤 4",
                "完税证明下载",
                self.tax_cert_button,
                "按机构查询缴款记录并下载完税证明 PDF。默认查询申报月份的次月缴款记录。",
            )
        )

        layout.addWidget(self.separator())
        self.income_report_button = QPushButton("开始")
        self.income_report_button.clicked.connect(lambda: self.prepare_and_run("income_report"))
        layout.addLayout(
            self.build_step_row(
                "步骤 5",
                "综合所得申报表下载",
                self.income_report_button,
                "按机构导出综合所得申报表到 output 文件夹。",
            )
        )

        layout.addWidget(self.separator())
        layout.addWidget(self.build_history_widget(), stretch=1)
        return group

    def build_step_row(self, step: str, title: str, button: QPushButton, description: str) -> QVBoxLayout:
        row = QVBoxLayout()
        row.setSpacing(6)

        step_label = QLabel(step)
        step_label.setObjectName("StepBadge")

        title_label = QLabel(title)
        title_label.setObjectName("StepTitle")

        button.setObjectName("StepButton")
        button.setFixedWidth(96)

        desc_label = QLabel(description)
        desc_label.setObjectName("TaskDesc")
        desc_label.setWordWrap(True)

        header = QHBoxLayout()
        header.addWidget(step_label)
        header.addWidget(title_label, stretch=1)
        header.addWidget(button)
        row.addLayout(header)
        row.addWidget(desc_label)
        return row

    def build_history_widget(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title = QLabel("执行历史")
        title.setObjectName("StepTitle")
        layout.addWidget(title)

        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(["任务", "开始时间", "结束时间", "耗时"])
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        layout.addWidget(self.history_table, stretch=1)
        return panel

    def build_result_group(self) -> QGroupBox:
        group = QGroupBox("任务处理结果表")
        layout = QVBoxLayout(group)
        self.result_table = QTableWidget(0, 6)
        self.result_table.setHorizontalHeaderLabels([
            "机构代码",
            "机构名称",
            "专项申报",
            "个税申报导入",
            "完税证明",
            "综合所得申报表",
        ])
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.result_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        layout.addWidget(self.result_table)
        return group

    def build_log_group(self) -> QGroupBox:
        group = QGroupBox("日志展示")
        layout = QVBoxLayout(group)

        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        self.resume_failed_button = QPushButton("从失败继续")
        self.resume_failed_button.setEnabled(False)
        self.resume_failed_button.clicked.connect(self.resume_from_failed)
        self.stop_button = QPushButton("停止任务")
        self.stop_button.setObjectName("DangerButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_process)
        self.copy_log_button = QPushButton("复制")
        self.copy_log_button.clicked.connect(self.copy_log)
        self.clear_log_button = QPushButton("清空")
        self.clear_log_button.clicked.connect(lambda: self.log_edit.clear())
        toolbar.addWidget(self.resume_failed_button)
        toolbar.addWidget(self.stop_button)
        toolbar.addWidget(self.copy_log_button)
        toolbar.addWidget(self.clear_log_button)
        layout.addLayout(toolbar)

        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.log_edit)
        return group

    def separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    def update_org_input_state(self, *_) -> None:
        self.org_code_input.setEnabled(not self.all_orgs_checkbox.isChecked())
        if self.all_orgs_checkbox.isChecked():
            self.org_code_input.clear()
        self.refresh_month_views()

    def choose_org_excel(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "选择机构 Excel",
            str(self.org_excel_path.parent if self.org_excel_path.exists() else WORK_DIR),
            "Excel 文件 (*.xlsx *.xls);;所有文件 (*)",
        )
        if not file_name:
            return
        self.org_excel_path = Path(file_name)
        self.org_excel_input.setText(str(self.org_excel_path))
        self.refresh_result_table()

    def save_chrome_path_config(self) -> None:
        chrome_path = self.chrome_path_input.text().strip()
        self.app_config["chrome_path"] = chrome_path
        save_app_config(self.app_config)

    def refresh_month_views(self) -> None:
        self.refresh_result_table()
        self.refresh_history_table()

    def orgs_for_result_table(self) -> list[TaxOrg]:
        if not self.org_excel_path.exists():
            return []
        try:
            orgs = read_orgs_from_excel(self.org_excel_path)
        except Exception:
            return []
        org_code = self.org_code_input.text().strip()
        if org_code:
            orgs = [org for org in orgs if org.code == org_code]
        return orgs

    def refresh_result_table(self) -> None:
        if not hasattr(self, "result_table"):
            return
        orgs = self.orgs_for_result_table()
        saved = self.load_task_results()
        saved_orgs = saved.get("orgs", {})
        self.result_rows.clear()
        self.result_table.setRowCount(len(orgs))
        for row, org in enumerate(orgs):
            self.result_rows[org.code] = row
            self.set_table_item(row, 0, org.code)
            self.set_table_item(row, 1, org.name)
            saved_row = saved_orgs.get(org.code, {})
            self.set_table_item(row, 2, saved_row.get("special_deduction", "待处理"))
            self.set_table_item(row, 3, saved_row.get("import", "待处理"))
            self.set_table_item(row, 4, saved_row.get("tax_certificate", "待处理"))
            self.set_table_item(row, 5, saved_row.get("income_report", "待处理"))
        self.result_table.resizeRowsToContents()
        self.resize_result_columns()

    def resize_result_columns(self) -> None:
        if not hasattr(self, "result_table"):
            return
        width = max(self.result_table.viewport().width(), 760)
        weights = [0.12, 0.22, 0.16, 0.18, 0.16, 0.16]
        for column, weight in enumerate(weights):
            self.result_table.setColumnWidth(column, int(width * weight))
        if hasattr(self, "history_table"):
            history_width = max(self.history_table.viewport().width(), 360)
            history_weights = [0.24, 0.28, 0.28, 0.20]
            for column, weight in enumerate(history_weights):
                self.history_table.setColumnWidth(column, int(history_width * weight))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resize_result_columns()

    def set_table_item(self, row: int, column: int, text: str) -> None:
        item = self.result_table.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            self.result_table.setItem(row, column, item)
        item.setText(text)
        if text.startswith("成功"):
            item.setForeground(Qt.GlobalColor.darkGreen)
        elif text.startswith("失败"):
            item.setForeground(Qt.GlobalColor.red)
        elif text == "处理中":
            item.setForeground(Qt.GlobalColor.darkBlue)
        else:
            item.setForeground(Qt.GlobalColor.darkGray)

    def update_task_status(self, org_code: str, task_key: str, status: str) -> None:
        if not hasattr(self, "result_table"):
            return
        row = self.result_rows.get(org_code)
        column = self.task_columns.get(task_key)
        if row is None or column is None:
            return
        self.set_table_item(row, column, status)
        self.save_task_results()

    def reset_task_status_for_orgs(self, task_key: str, orgs: list[TaxOrg]) -> None:
        for org in orgs:
            self.update_task_status(org.code, task_key, "待处理")

    def task_display_name(self, task_key: str) -> str:
        return {
            "special_deduction": "专项附加导出",
            "import": "导入数据",
            "tax_certificate": "完税证明下载",
            "income_report": "综合所得申报表下载",
        }.get(task_key, task_key)

    def special_deduction_backend_exists(self) -> bool:
        backend = TASK_SPECIAL_DEDUCTION_EXE if getattr(sys, "frozen", False) else TASK_SPECIAL_DEDUCTION_SCRIPT
        return backend.exists()

    def append_log(self, message: str) -> None:
        self.log_edit.appendPlainText(message.rstrip())
        self.log_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.update_result_from_log(message)

    def copy_log(self) -> None:
        QApplication.clipboard().setText(self.log_edit.toPlainText())
        self.append_log("日志内容已复制到剪贴板。")

    def update_result_from_log(self, message: str) -> None:
        if not self.current_run_task:
            return

        for line in message.splitlines():
            started = (
                re.search(r"开始处理单位：(.+?)（(\d+)）", line)
                or re.search(r"开始处理申报导入：(.+?)（(\d+)）", line)
                or re.search(r"开始下载完税证明：(.+?)（(\d+)）", line)
                or re.search(r"开始下载综合所得申报表：(.+?)（(\d+)）", line)
            )
            if started:
                self.current_org_code = started.group(2)
                self.current_counts[(self.current_run_task, self.current_org_code)] = 0
                self.update_task_status(self.current_org_code, self.current_run_task, "处理中")
                continue

            if self.current_run_task == "special_deduction":
                done = re.search(r"单位处理完成：(.+?) ->", line)
                if done and self.current_org_code:
                    self.update_task_status(self.current_org_code, "special_deduction", "成功 1笔")

            if self.current_run_task == "import" and "文件导入成功：" in line and self.current_org_code:
                key = ("import", self.current_org_code)
                self.current_counts[key] = self.current_counts.get(key, 0) + 1
                self.update_task_status(self.current_org_code, "import", f"成功 {self.current_counts[key]}笔")

            if self.current_run_task == "import" and "机构申报导入完成：" in line and self.current_org_code:
                key = ("import", self.current_org_code)
                self.update_task_status(self.current_org_code, "import", f"成功 {self.current_counts.get(key, 0)}笔")

            tax_done = (
                re.search(r"机构完税证明及综合所得申报表下载完成：.+?（(\d+)），共 (\d+) 个文件", line)
                or re.search(r"机构完税证明下载完成：.+?（(\d+)），共 (\d+) 个文件", line)
            )
            if self.current_run_task == "tax_certificate" and tax_done:
                self.update_task_status(tax_done.group(1), "tax_certificate", f"成功 {tax_done.group(2)}笔")

            income_done = re.search(r"机构综合所得申报表下载完成：.+?（(\d+)），共 (\d+) 个文件", line)
            if self.current_run_task == "income_report" and income_done:
                self.update_task_status(income_done.group(1), "income_report", f"成功 {income_done.group(2)}笔")

            if (
                ("未查询到缴款记录，跳过机构：" in line or "未查询到缴款记录，跳过完税证明下载：" in line)
                and self.current_org_code
                and self.current_run_task == "tax_certificate"
            ):
                self.update_task_status(self.current_org_code, "tax_certificate", "成功 0笔")

    def initialize_chrome(self) -> None:
        if self.process is not None:
            QMessageBox.information(self, "任务运行中", "当前已有自动化任务正在执行，请等待结束后再初始化。")
            return
        if self.init_process is not None:
            QMessageBox.information(self, "初始化运行中", "Chrome 初始化正在执行，请稍候。")
            return
        if not START_DEBUG_CHROME_SCRIPT.exists():
            message = f"找不到初始化脚本：{START_DEBUG_CHROME_SCRIPT}"
            self.append_log(message)
            QMessageBox.critical(self, "初始化失败", message)
            return

        self.append_log("=" * 80)
        self.append_log(f"开始初始化 Chrome：{START_DEBUG_CHROME_SCRIPT}")
        chrome_path = self.chrome_path_input.text().strip()
        self.save_chrome_path_config()
        self.append_log(
            "命令：powershell -NoProfile -ExecutionPolicy Bypass -File start_debug_chrome.ps1"
            + (f" -ChromePath \"{chrome_path}\"" if chrome_path else "")
        )

        self.init_process = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        self.init_process.setProcessEnvironment(env)
        self.init_process.setWorkingDirectory(str(WORK_DIR))
        self.init_process.setProgram("powershell")
        init_args = [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(START_DEBUG_CHROME_SCRIPT),
        ]
        if chrome_path:
            init_args.extend(["-ChromePath", chrome_path])
        self.init_process.setArguments(init_args)
        self.init_process.readyReadStandardOutput.connect(self.read_init_stdout)
        self.init_process.readyReadStandardError.connect(self.read_init_stderr)
        self.init_process.finished.connect(self.init_finished)
        self.init_process.errorOccurred.connect(self.init_error)
        self.set_running_state(True)
        self.init_process.start()

    def read_init_stdout(self) -> None:
        if self.init_process is None:
            return
        text = decode_process_output(self.init_process.readAllStandardOutput())
        if text:
            self.append_log(text)

    def read_init_stderr(self) -> None:
        if self.init_process is None:
            return
        text = decode_process_output(self.init_process.readAllStandardError())
        if text:
            self.append_log(text)

    def init_finished(self, exit_code: int, exit_status) -> None:
        if exit_code == 0:
            self.append_log("初始化完成：Chrome 已启动。请在该 Chrome 窗口中手工登录自然人电子税务局。")
        else:
            self.append_log(f"初始化失败：start_debug_chrome.ps1 退出码 {exit_code}。请检查上方错误日志。")
            QMessageBox.critical(
                self,
                "初始化失败",
                f"启动 Chrome 初始化脚本失败，退出码：{exit_code}\n请查看日志区域的错误信息。",
            )
        self.init_process = None
        self.set_running_state(False)

    def init_error(self, error) -> None:
        self.append_log(f"初始化进程启动异常：{error}")
        QMessageBox.critical(self, "初始化失败", f"初始化进程启动异常：{error}")
        self.init_process = None
        self.set_running_state(False)

    def validate_inputs(self, task_key: str) -> tuple[str, list[TaxOrg]] | None:
        month = self.month_combo.currentText().strip()
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            QMessageBox.warning(self, "参数不完整", "税款所属月份必须是 yyyy-mm 格式，例如 2026-06。")
            return None

        if not self.org_excel_path.exists():
            QMessageBox.warning(self, "缺少文件", f"找不到机构 Excel：\n{self.org_excel_path}")
            return None

        org_code = self.org_code_input.text().strip()
        if not self.all_orgs_checkbox.isChecked() and not org_code:
            QMessageBox.warning(self, "参数不完整", "请填写指定机构代码，或勾选“处理全部机构”。")
            return None

        try:
            orgs = read_orgs_from_excel(self.org_excel_path)
        except Exception as exc:
            QMessageBox.critical(self, "读取机构 Excel 失败", str(exc))
            return None

        if org_code:
            orgs = [org for org in orgs if org.code == org_code]
            if not orgs:
                QMessageBox.warning(self, "机构不存在", f"机构 Excel 中找不到机构代码：{org_code}")
                return None

        return month, orgs

    def import_progress_path(self, month: str) -> Path:
        return OUTPUT_DIR / f"import_progress_{month}.json"

    def task_results_path(self, month: str | None = None) -> Path:
        month = month or self.month_combo.currentText().strip()
        safe_month = month if re.fullmatch(r"\d{4}-\d{2}", month) else "unknown"
        return OUTPUT_DIR / f"task_results_{safe_month}.json"

    def load_task_results(self, month: str | None = None) -> dict:
        path = self.task_results_path(month)
        if not path.exists():
            return {"month": month or self.month_combo.currentText().strip(), "orgs": {}, "history": []}
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except Exception as exc:
            print(f"读取任务结果文件失败，将忽略旧结果：{path}；原因：{exc}")
            return {"month": month or self.month_combo.currentText().strip(), "orgs": {}, "history": []}
        if not isinstance(data, dict):
            return {"month": month or self.month_combo.currentText().strip(), "orgs": {}, "history": []}
        data.setdefault("orgs", {})
        data.setdefault("history", [])
        return data

    def save_task_results(self) -> None:
        if not hasattr(self, "result_table"):
            return
        month = self.month_combo.currentText().strip()
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            return
        OUTPUT_DIR.mkdir(exist_ok=True)
        data = self.load_task_results(month)
        data["month"] = month
        data["updated_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data.setdefault("orgs", {})
        data.setdefault("history", [])
        for code, row in self.result_rows.items():
            data["orgs"][code] = {
                "name": self.result_table.item(row, 1).text() if self.result_table.item(row, 1) else "",
                "special_deduction": self.result_table.item(row, 2).text() if self.result_table.item(row, 2) else "待处理",
                "import": self.result_table.item(row, 3).text() if self.result_table.item(row, 3) else "待处理",
                "tax_certificate": self.result_table.item(row, 4).text() if self.result_table.item(row, 4) else "待处理",
                "income_report": self.result_table.item(row, 5).text() if self.result_table.item(row, 5) else "待处理",
            }
        path = self.task_results_path(month)
        tmp_path = path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        tmp_path.replace(path)

    def refresh_history_table(self) -> None:
        if not hasattr(self, "history_table"):
            return
        data = self.load_task_results()
        history = data.get("history", [])
        if not isinstance(history, list):
            history = []
        rows = list(reversed(history[-20:]))
        self.history_table.setRowCount(len(rows))
        for row, item in enumerate(rows):
            self.set_history_item(row, 0, str(item.get("task", "")))
            self.set_history_item(row, 1, str(item.get("started_at", "")))
            self.set_history_item(row, 2, str(item.get("ended_at", "")))
            self.set_history_item(row, 3, str(item.get("duration", "")))
        self.history_table.resizeRowsToContents()
        self.resize_result_columns()

    def set_history_item(self, row: int, column: int, text: str) -> None:
        item = self.history_table.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            self.history_table.setItem(row, column, item)
        item.setText(text)

    def append_execution_history(self, task_key: str, month: str, started_at: dt.datetime, exit_code: int) -> None:
        ended_at = dt.datetime.now()
        seconds = max(0, int((ended_at - started_at).total_seconds()))
        duration = self.format_duration(seconds)
        data = self.load_task_results(month)
        data["month"] = month
        data["updated_at"] = ended_at.strftime("%Y-%m-%d %H:%M:%S")
        data.setdefault("orgs", {})
        history = data.setdefault("history", [])
        if not isinstance(history, list):
            history = []
            data["history"] = history
        history.append(
            {
                "task_key": task_key,
                "task": self.task_display_name(task_key),
                "started_at": started_at.strftime("%Y-%m-%d %H:%M:%S"),
                "ended_at": ended_at.strftime("%Y-%m-%d %H:%M:%S"),
                "duration": duration,
                "exit_code": exit_code,
                "status": "成功" if exit_code == 0 else "失败",
            }
        )
        path = self.task_results_path(month)
        OUTPUT_DIR.mkdir(exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        tmp_path.replace(path)
        self.refresh_history_table()

    def format_duration(self, seconds: int) -> str:
        minutes, sec = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}小时{minutes}分{sec}秒"
        if minutes:
            return f"{minutes}分{sec}秒"
        return f"{sec}秒"

    def load_import_progress(self, month: str) -> dict:
        path = self.import_progress_path(month)
        if not path.exists():
            return {"month": month, "completed": {}}
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except Exception as exc:
            self.append_log(f"读取导入进度文件失败，将忽略旧进度：{path}；原因：{exc}")
            return {"month": month, "completed": {}}
        if not isinstance(data, dict):
            return {"month": month, "completed": {}}
        data.setdefault("completed", {})
        return data

    def choose_import_resume_mode(self, month: str, orgs: list[TaxOrg]) -> list[str] | None:
        if not self.all_orgs_checkbox.isChecked():
            return []
        progress = self.load_import_progress(month)
        completed = progress.get("completed", {})
        completed_orgs = [org for org in orgs if org.code in completed]
        if not completed_orgs:
            return []

        preview_lines = []
        for org in completed_orgs[:12]:
            completed_at = completed.get(org.code, {}).get("completed_at", "")
            preview_lines.append(f"{org.code} {org.name} {completed_at}")
        if len(completed_orgs) > 12:
            preview_lines.append(f"... 还有 {len(completed_orgs) - 12} 个")

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Question)
        message.setWindowTitle("发现上次执行记录")
        message.setText(
            f"检测到 {month} 已有 {len(completed_orgs)} 个机构执行完成。\n\n"
            "已完成机构：\n"
            + "\n".join(preview_lines)
            + "\n\n请选择本次执行方式。"
        )
        rerun_button = message.addButton("全部重跑", QMessageBox.ButtonRole.ActionRole)
        resume_button = message.addButton("从上次失败处继续", QMessageBox.ButtonRole.AcceptRole)
        cancel_button = message.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(resume_button)
        message.exec()

        clicked = message.clickedButton()
        if clicked == resume_button:
            self.append_log(f"用户选择续跑：跳过 {len(completed_orgs)} 个已完成机构。")
            return ["--resume"]
        if clicked == rerun_button:
            self.append_log("用户选择全部重跑：将清除本次机构的历史完成记录。")
            return ["--reset-progress"]
        if clicked == cancel_button:
            self.append_log("用户取消执行。")
            return None
        return None

    def prepare_and_run(self, task_key: str) -> None:
        if self.process is not None:
            QMessageBox.information(self, "任务运行中", "当前已有任务正在执行，请等待结束或先停止。")
            return

        validated = self.validate_inputs(task_key)
        if validated is None:
            return
        month, orgs = validated

        dialog = OrgPreviewDialog(orgs, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.append_log("用户取消执行。")
            return

        if not self.confirm_clear_existing_results(task_key, month, orgs):
            self.append_log("用户取消执行。")
            return

        extra_args: list[str] = []
        if task_key == "special_deduction":
            backend = TASK_SPECIAL_DEDUCTION_EXE if getattr(sys, "frozen", False) else TASK_SPECIAL_DEDUCTION_SCRIPT
            if not backend.exists():
                self.append_log("任务一未执行：缺少导出后端程序。")
                return
            target = backend
        else:
            if task_key == "tax_certificate":
                target = TASK_TAX_CERTIFICATE_EXE if getattr(sys, "frozen", False) else TASK_TAX_CERTIFICATE_SCRIPT
                extra_args.extend(["--task", "tax_certificate"])
            elif task_key == "income_report":
                target = TASK_TAX_CERTIFICATE_EXE if getattr(sys, "frozen", False) else TASK_TAX_CERTIFICATE_SCRIPT
                extra_args.extend(["--task", "income_report"])
            else:
                target = TASK_IMPORT_EXE if getattr(sys, "frozen", False) else TASK_IMPORT_SCRIPT
            if task_key == "import":
                resume_args = self.choose_import_resume_mode(month, orgs)
                if resume_args is None:
                    return
                extra_args.extend(resume_args)
                if not self.all_orgs_checkbox.isChecked() and not extra_args:
                    extra_args.append("--reset-progress")

        if not target.exists():
            QMessageBox.critical(self, "缺少程序", f"找不到任务程序：\n{target}")
            return

        self.reset_task_status_for_orgs(task_key, orgs)
        backend_month = add_months(month, 1) if task_key == "tax_certificate" else month
        self.run_backend(target, month, task_key=task_key, orgs=orgs, extra_args=extra_args, backend_month=backend_month)

    def confirm_clear_existing_results(self, task_key: str, month: str, orgs: list[TaxOrg]) -> bool:
        saved = self.load_task_results(month)
        saved_orgs = saved.get("orgs", {})
        processed: list[str] = []
        for org in orgs:
            status = saved_orgs.get(org.code, {}).get(task_key, "待处理")
            if status and status != "待处理":
                processed.append(f"{org.code} {org.name}：{status}")
        if not processed:
            return True

        preview = "\n".join(processed[:12])
        if len(processed) > 12:
            preview += f"\n... 还有 {len(processed) - 12} 个"
        reply = QMessageBox.question(
            self,
            "确认重新执行",
            f"{month} 的“{self.task_display_name(task_key)}”已有 {len(processed)} 个目标机构存在处理结果。\n\n"
            f"{preview}\n\n"
            "点击“是”将清空这些目标机构当前任务的结果并重新执行；点击“否”取消。",
        )
        return reply == QMessageBox.StandardButton.Yes

    def backend_for_task(self, task_key: str) -> Path:
        if task_key == "special_deduction":
            return TASK_SPECIAL_DEDUCTION_EXE if getattr(sys, "frozen", False) else TASK_SPECIAL_DEDUCTION_SCRIPT
        if task_key == "import":
            return TASK_IMPORT_EXE if getattr(sys, "frozen", False) else TASK_IMPORT_SCRIPT
        if task_key == "tax_certificate":
            return TASK_TAX_CERTIFICATE_EXE if getattr(sys, "frozen", False) else TASK_TAX_CERTIFICATE_SCRIPT
        if task_key == "income_report":
            return TASK_TAX_CERTIFICATE_EXE if getattr(sys, "frozen", False) else TASK_TAX_CERTIFICATE_SCRIPT
        raise RuntimeError(f"未知任务类型：{task_key}")

    def resume_from_failed(self) -> None:
        if self.process is not None or self.init_process is not None:
            QMessageBox.information(self, "任务运行中", "当前已有任务正在执行，请等待结束后再续跑。")
            return
        if not self.last_failed_task_key or not self.last_failed_org_code:
            QMessageBox.information(self, "没有失败记录", "当前没有可续跑的失败机构。")
            return

        month = self.month_combo.currentText().strip()
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            QMessageBox.warning(self, "参数不完整", "税款所属月份必须是 yyyy-mm 格式，例如 2026-06。")
            return
        try:
            all_orgs = read_orgs_from_excel(self.org_excel_path)
        except Exception as exc:
            QMessageBox.critical(self, "读取机构 Excel 失败", str(exc))
            return
        start_index = next((i for i, org in enumerate(all_orgs) if org.code == self.last_failed_org_code), None)
        if start_index is None:
            QMessageBox.warning(self, "机构不存在", f"机构 Excel 中找不到失败机构代码：{self.last_failed_org_code}")
            return
        orgs = all_orgs[start_index:]
        task_name = {
            "special_deduction": "专项附加导出",
            "import": "导入数据",
            "tax_certificate": "完税证明下载",
            "income_report": "综合所得申报表下载",
        }.get(self.last_failed_task_key, self.last_failed_task_key)
        reply = QMessageBox.question(
            self,
            "确认续跑",
            f"将从失败机构 {orgs[0].code} {orgs[0].name} 开始继续执行“{task_name}”，共 {len(orgs)} 个机构。\n是否继续？",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        target = self.backend_for_task(self.last_failed_task_key)
        if not target.exists():
            QMessageBox.critical(self, "缺少程序", f"找不到任务程序：\n{target}")
            return
        self.all_orgs_checkbox.setChecked(True)
        self.reset_task_status_for_orgs(self.last_failed_task_key, orgs)
        self.run_backend(
            target,
            month,
            task_key=self.last_failed_task_key,
            orgs=orgs,
            extra_args=self.resume_extra_args(self.last_failed_task_key, self.last_failed_org_code),
            backend_month=add_months(month, 1) if self.last_failed_task_key == "tax_certificate" else month,
        )

    def resume_extra_args(self, task_key: str, org_code: str) -> list[str]:
        args = ["--start-org-code", org_code]
        if task_key == "tax_certificate":
            args.extend(["--task", "tax_certificate"])
        elif task_key == "income_report":
            args.extend(["--task", "income_report"])
        return args

    def run_backend(
        self,
        target: Path,
        month: str,
        *,
        task_key: str,
        orgs: list[TaxOrg],
        extra_args: list[str] | None = None,
        backend_month: str | None = None,
    ) -> None:
        backend_month = backend_month or month
        if target.suffix.lower() == ".exe":
            program = str(target)
            args = ["--cdp", CDP_URL, "--month", backend_month, "--org-excel", str(self.org_excel_path), "--yes"]
        else:
            program = sys.executable
            args = [str(target), "--cdp", CDP_URL, "--month", backend_month, "--org-excel", str(self.org_excel_path), "--yes"]
        if not self.all_orgs_checkbox.isChecked():
            args.extend(["--org-code", self.org_code_input.text().strip()])
        if extra_args:
            args.extend(extra_args)

        self.append_log("=" * 80)
        self.append_log(f"启动任务：{target.name}")
        if backend_month != month:
            self.append_log(f"界面申报月份：{month}；本任务实际执行月份：{backend_month}")
        self.append_log(f"命令：{program} {' '.join(args)}")

        self.current_run_task = task_key
        self.current_org_code = None
        self.current_run_started_at = dt.datetime.now()
        self.current_run_month = month
        for org in orgs:
            self.update_task_status(org.code, task_key, "待处理")

        self.process = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")
        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(WORK_DIR))
        self.process.setProgram(program)
        self.process.setArguments(args)
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.readyReadStandardError.connect(self.read_stderr)
        self.process.finished.connect(self.process_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.set_running_state(True)
        self.process.start()

    def read_stdout(self) -> None:
        if self.process is None:
            return
        text = decode_process_output(self.process.readAllStandardOutput())
        if text:
            self.append_log(text)

    def read_stderr(self) -> None:
        if self.process is None:
            return
        text = decode_process_output(self.process.readAllStandardError())
        if text:
            self.append_log(text)

    def process_finished(self, exit_code: int, exit_status) -> None:
        if exit_code != 0 and self.current_run_task and self.current_org_code:
            self.update_task_status(self.current_org_code, self.current_run_task, "失败")
            self.last_failed_task_key = self.current_run_task
            self.last_failed_org_code = self.current_org_code
            self.resume_failed_button.setEnabled(True)
        if self.current_run_task and self.current_run_started_at and self.current_run_month:
            self.append_execution_history(
                self.current_run_task,
                self.current_run_month,
                self.current_run_started_at,
                exit_code,
            )
        self.append_log(f"任务结束，退出码：{exit_code}")
        self.process = None
        self.current_run_task = None
        self.current_org_code = None
        self.current_run_started_at = None
        self.current_run_month = None
        self.set_running_state(False)

    def process_error(self, error) -> None:
        if self.current_run_task and self.current_org_code:
            self.update_task_status(self.current_org_code, self.current_run_task, "失败")
            self.last_failed_task_key = self.current_run_task
            self.last_failed_org_code = self.current_org_code
            self.resume_failed_button.setEnabled(True)
        if self.current_run_task and self.current_run_started_at and self.current_run_month:
            self.append_execution_history(
                self.current_run_task,
                self.current_run_month,
                self.current_run_started_at,
                1,
            )
        self.append_log(f"任务启动或执行异常：{error}")
        self.process = None
        self.current_run_task = None
        self.current_org_code = None
        self.current_run_started_at = None
        self.current_run_month = None
        self.set_running_state(False)

    def stop_process(self) -> None:
        target = self.process or self.init_process
        if target is None:
            return
        self.append_log("正在请求停止当前运行进程...")
        target.terminate()
        if not target.waitForFinished(3000):
            self.append_log("普通停止未完成，强制结束进程。")
            target.kill()

    def set_running_state(self, running: bool) -> None:
        self.task1_button.setEnabled(not running)
        if not self.special_deduction_backend_exists():
            self.task1_button.setEnabled(False)
        self.task2_button.setEnabled(not running)
        self.tax_cert_button.setEnabled(not running)
        self.income_report_button.setEnabled(not running)
        self.init_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.resume_failed_button.setEnabled((not running) and bool(self.last_failed_task_key and self.last_failed_org_code))
        self.month_combo.setEnabled(not running)
        self.all_orgs_checkbox.setEnabled(not running)
        self.partial_orgs_radio.setEnabled(not running)
        self.chrome_path_input.setEnabled(not running)
        self.org_code_input.setEnabled((not running) and (not self.all_orgs_checkbox.isChecked()))

    def apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                font-family: "Microsoft YaHei UI", "Microsoft YaHei", Arial;
                font-size: 14px;
            }
            #Title {
                font-size: 22px;
                font-weight: 600;
                padding: 4px 0 8px 0;
            }
            QGroupBox {
                font-weight: 600;
                border: 1px solid #d8dde6;
                border-radius: 6px;
                margin-top: 10px;
                padding: 14px 12px 12px 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }
            QPushButton {
                min-height: 27px;
                padding: 4px 12px;
                border-radius: 4px;
                border: 1px solid #2563eb;
                background: #2563eb;
                color: white;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #1d4ed8;
                border-color: #1d4ed8;
            }
            QPushButton:pressed {
                background: #1e40af;
            }
            QPushButton:disabled {
                color: #9aa3af;
                background: #f1f3f5;
                border-color: #d0d5dd;
            }
            QPushButton#StepButton {
                min-height: 26px;
                padding: 3px 10px;
                font-weight: 500;
            }
            QPushButton#DangerButton {
                background: #dc2626;
                border-color: #dc2626;
                color: white;
            }
            QPushButton#DangerButton:hover {
                background: #b91c1c;
                border-color: #b91c1c;
            }
            QPushButton#DangerButton:pressed {
                background: #991b1b;
            }
            QPushButton#DangerButton:disabled {
                color: #9aa3af;
                background: #f1f3f5;
                border-color: #d0d5dd;
            }
            QLineEdit, QComboBox {
                min-height: 32px;
                padding: 2px 8px;
                border: 1px solid #cfd6e0;
                border-radius: 4px;
                background: white;
            }
            QPlainTextEdit {
                background: #101828;
                color: #e5e7eb;
                border: 1px solid #293548;
                border-radius: 4px;
                font-family: Consolas, "Microsoft YaHei UI";
                font-size: 13px;
            }
            QTableWidget {
                gridline-color: #d8dde6;
                selection-background-color: #dbeafe;
                selection-color: #111827;
                background: white;
                alternate-background-color: #f8fafc;
            }
            QHeaderView::section {
                background: #f1f5f9;
                color: #111827;
                font-weight: 600;
                border: 0;
                border-right: 1px solid #d8dde6;
                border-bottom: 1px solid #d8dde6;
                padding: 6px;
            }
            #Hint, #TaskDesc {
                color: #596579;
                font-weight: 400;
            }
            #StepBadge {
                color: #2563eb;
                font-weight: 600;
                padding: 4px 0;
            }
            #StepTitle {
                font-weight: 600;
                color: #111827;
            }
            """
        )


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
