"""简单 PySide6 控制面板：路径、线程数、断点、清理与日志。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .auto import run_auto_mode, run_cleanup_only
from .pipeline import default_worker_count


def _project_root() -> Path:
    """仓库根目录（含 input/ output/ tools/）。"""
    # gui 从包内启动时 cwd 可能不同；优先入口脚本所在目录
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # unlock_gui.py 位于项目根
    main = getattr(sys.modules.get("__main__"), "__file__", None)
    if main:
        p = Path(main).resolve().parent
        if (p / "kugou_unlock").is_dir() or (p / "input").is_dir():
            return p
    return Path.cwd()


class _TaskWorker(QObject):
    """在后台线程跑自动模式或清理，避免卡住 UI。"""

    log_line = Signal(str)
    finished = Signal(int)

    def __init__(
        self,
        mode: str,
        *,
        input_dir: str,
        output_dir: str,
        tools_dir: str,
        workers: int,
        progress_path: str,
        remove_source: bool,
        reset_progress: bool,
    ):
        super().__init__()
        self.mode = mode
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.tools_dir = tools_dir
        self.workers = workers
        self.progress_path = progress_path
        self.remove_source = remove_source
        self.reset_progress = reset_progress

    @Slot()
    def run(self) -> None:
        def log(msg: str) -> None:
            self.log_line.emit(str(msg))

        try:
            if self.mode == "cleanup":
                code = run_cleanup_only(
                    output_dir=self.output_dir,
                    tools_dir=self.tools_dir,
                    reset_progress=self.reset_progress,
                    log=log,
                )
            else:
                code = run_auto_mode(
                    input_dir=self.input_dir,
                    output_dir=self.output_dir,
                    tools_dir=self.tools_dir,
                    workers=self.workers,
                    progress_path=self.progress_path or None,
                    remove_source=self.remove_source,
                    log=log,
                )
        except Exception as e:
            log(f"[!] Unexpected error: {e}")
            code = 1
        self.finished.emit(code)


class MainWindow(QMainWindow):
    def __init__(self, root: Path | None = None):
        super().__init__()
        self.root = Path(root) if root else _project_root()
        self.setWindowTitle("酷狗本地解密工具 · KuGou Unlock")
        self.resize(820, 640)
        self._thread: QThread | None = None
        self._worker: _TaskWorker | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)

        layout.addWidget(self._build_paths_group())
        layout.addWidget(self._build_options_group())

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 10))
        self.log_view.setMinimumHeight(280)

        layout.addLayout(self._build_actions())
        layout.addWidget(QLabel("运行日志"))
        layout.addWidget(self.log_view)

        self.statusBar().showMessage(f"工作目录: {self.root}")

    def _build_paths_group(self) -> QGroupBox:
        box = QGroupBox("目录")
        form = QFormLayout(box)

        self.input_edit = QLineEdit(str(self.root / "input"))
        self.output_edit = QLineEdit(str(self.root / "output"))
        self.tools_edit = QLineEdit(str(self.root / "tools"))
        self.progress_edit = QLineEdit(str(self.root / "tools" / "progress.json"))

        form.addRow("输入目录 (input)", self._path_row(self.input_edit, dir_mode=True))
        form.addRow("输出目录 (output)", self._path_row(self.output_edit, dir_mode=True))
        form.addRow("工具目录 (tools)", self._path_row(self.tools_edit, dir_mode=True))
        form.addRow("进度 JSON", self._path_row(self.progress_edit, dir_mode=False))
        return box

    def _path_row(self, edit: QLineEdit, *, dir_mode: bool) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, stretch=1)
        btn = QPushButton("浏览…")
        btn.clicked.connect(lambda: self._browse(edit, dir_mode=dir_mode))
        row.addWidget(btn)
        return w

    def _browse(self, edit: QLineEdit, *, dir_mode: bool) -> None:
        start = edit.text().strip() or str(self.root)
        if dir_mode:
            path = QFileDialog.getExistingDirectory(self, "选择目录", start)
        else:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "选择进度文件",
                start,
                "JSON (*.json);;All (*.*)",
            )
        if path:
            edit.setText(path)

    def _build_options_group(self) -> QGroupBox:
        box = QGroupBox("参数")
        form = QFormLayout(box)

        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 32)
        self.workers_spin.setValue(default_worker_count())
        self.workers_spin.setToolTip("多线程并发数（磁盘解密建议 2–8）")

        self.keep_source = QCheckBox("保留加密源文件（成功后不删除 input/music_files 中的文件）")
        self.reset_progress = QCheckBox("清理时同时重置进度 JSON（下次全部重跑）")

        form.addRow("工作线程数", self.workers_spin)
        form.addRow(self.keep_source)
        form.addRow(self.reset_progress)
        return box

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.btn_start = QPushButton("开始解密")
        self.btn_start.setDefault(True)
        self.btn_start.clicked.connect(self._on_start)

        self.btn_cleanup = QPushButton("清理工作区")
        self.btn_cleanup.clicked.connect(self._on_cleanup)

        self.btn_open_input = QPushButton("打开 input")
        self.btn_open_input.clicked.connect(lambda: self._open_dir(self.input_edit.text()))

        self.btn_open_output = QPushButton("打开 output")
        self.btn_open_output.clicked.connect(lambda: self._open_dir(self.output_edit.text()))

        self.btn_clear_log = QPushButton("清空日志")
        self.btn_clear_log.clicked.connect(self.log_view.clear)

        row.addWidget(self.btn_start)
        row.addWidget(self.btn_cleanup)
        row.addWidget(self.btn_open_input)
        row.addWidget(self.btn_open_output)
        row.addStretch(1)
        row.addWidget(self.btn_clear_log)
        return row

    def _open_dir(self, path: str) -> None:
        p = Path(path.strip() or ".")
        p.mkdir(parents=True, exist_ok=True)
        # Windows / cross-platform
        try:
            if sys.platform == "win32":
                os.startfile(str(p))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.system(f'open "{p}"')
            else:
                os.system(f'xdg-open "{p}"')
        except OSError as e:
            QMessageBox.warning(self, "打开目录失败", str(e))

    def _set_busy(self, busy: bool) -> None:
        self.btn_start.setEnabled(not busy)
        self.btn_cleanup.setEnabled(not busy)
        self.workers_spin.setEnabled(not busy)
        self.keep_source.setEnabled(not busy)
        self.reset_progress.setEnabled(not busy)
        for edit in (
            self.input_edit,
            self.output_edit,
            self.tools_edit,
            self.progress_edit,
        ):
            edit.setEnabled(not busy)
        if busy:
            self.statusBar().showMessage("运行中…")
        else:
            self.statusBar().showMessage(f"工作目录: {self.root}")

    def _append_log(self, line: str) -> None:
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)
        self.log_view.insertPlainText(line if line.endswith("\n") else line + "\n")
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    def _start_task(self, mode: str) -> None:
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(self, "提示", "已有任务在运行。")
            return

        input_dir = self.input_edit.text().strip()
        output_dir = self.output_edit.text().strip()
        tools_dir = self.tools_edit.text().strip()
        progress = self.progress_edit.text().strip()

        if mode == "auto" and not input_dir:
            QMessageBox.warning(self, "参数", "请填写输入目录。")
            return
        if not output_dir or not tools_dir:
            QMessageBox.warning(self, "参数", "请填写输出目录与工具目录。")
            return

        self._append_log("")
        self._append_log(f"── 启动任务: {mode} ──")
        self._set_busy(True)

        thread = QThread(self)
        worker = _TaskWorker(
            mode,
            input_dir=input_dir,
            output_dir=output_dir,
            tools_dir=tools_dir,
            workers=self.workers_spin.value(),
            progress_path=progress,
            remove_source=not self.keep_source.isChecked(),
            reset_progress=self.reset_progress.isChecked(),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log_line.connect(self._append_log)
        worker.finished.connect(self._on_task_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_start(self) -> None:
        self._start_task("auto")

    def _on_cleanup(self) -> None:
        if self.reset_progress.isChecked():
            reply = QMessageBox.question(
                self,
                "确认",
                "将清理临时文件并删除进度 JSON，确认继续？",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._start_task("cleanup")

    @Slot(int)
    def _on_task_finished(self, code: int) -> None:
        self._set_busy(False)
        self._thread = None
        self._worker = None
        if code == 0:
            self._append_log("── 完成 ──")
            self.statusBar().showMessage("完成")
        else:
            self._append_log(f"── 结束（退出码 {code}）──")
            self.statusBar().showMessage(f"结束，退出码 {code}")


def run_gui(root: Path | str | None = None) -> int:
    # Windows 高 DPI
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("KuGou Unlock")
    app.setStyle("Fusion")
    win = MainWindow(Path(root) if root else None)
    win.show()
    return app.exec()
