"""Главное окно и координация пользовательских действий."""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk

from ..image_processor import ImageProcessor
from ..models import (
    FrameSettings,
    InputValidationError,
    ProcessingJob,
    ProcessingResult,
    RGBColor,
)
from ..preview_worker import PreviewWorker
from .controls import FrameSettingsControl, OutputPathControl, SourcePathControl
from .preview import PreviewPanel


@dataclass(frozen=True, slots=True)
class _ProgressEvent:
    completed: int
    total: int
    source_file: Path
    succeeded: bool


@dataclass(frozen=True, slots=True)
class _DoneEvent:
    result: ProcessingResult


@dataclass(frozen=True, slots=True)
class _ErrorEvent:
    error: Exception


WorkerEvent = _ProgressEvent | _DoneEvent | _ErrorEvent


def _resource_path(relative_path: str) -> Path:
    """Возвращает путь к ресурсу в исходниках или внутри сборки PyInstaller."""
    bundle_directory = getattr(sys, "_MEIPASS", None)
    if bundle_directory is not None:
        return Path(bundle_directory) / relative_path
    return Path(__file__).resolve().parents[2] / relative_path


class PhotoFrameApp(tk.Tk):
    """Окно приложения; файловая обработка делегирована ImageProcessor."""

    PREVIEW_DELAY_MS = 250

    def __init__(self, processor: ImageProcessor | None = None) -> None:
        super().__init__()
        self._set_window_icon()
        self.processor = processor or ImageProcessor()
        self.title("Рамка для фотографий")
        self.geometry("980x700")
        self.minsize(780, 580)

        self.source_variable = tk.StringVar()
        self.output_variable = tk.StringVar()
        self.percentage_variable = tk.StringVar(value="16")
        self.square_output_variable = tk.BooleanVar(value=True)
        self.status_variable = tk.StringVar(value="Готово к работе")
        self._frame_color: RGBColor = (255, 255, 255)
        self._preview_after_id: str | None = None
        self._preview_poll_after_id: str | None = None
        self._poll_after_id: str | None = None
        self._busy = False
        self._active_output: Path | None = None
        self._worker_events: queue.Queue[WorkerEvent] = queue.Queue()
        self._preview_worker = PreviewWorker(self.processor.build_preview)

        self._configure_styles()
        self._build_layout()
        self._bind_events()
        self._poll_preview_events()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_window_icon(self) -> None:
        try:
            self.iconbitmap(str(_resource_path("assets/app.ico")))
        except tk.TclError:
            # Отсутствующая иконка не должна мешать запуску приложения.
            pass

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
        style.configure("Subtitle.TLabel", foreground="#5f6368")
        style.configure("Run.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8))

    def _build_layout(self) -> None:
        container = ttk.Frame(self, padding=16)
        container.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)
        container.columnconfigure(0, weight=1)

        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(header, text="Добавление рамки", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        self.source_control = SourcePathControl(
            container,
            variable=self.source_variable,
            on_selected=self._on_source_selected,
        )
        self.source_control.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self.output_control = OutputPathControl(
            container,
            variable=self.output_variable,
        )
        self.output_control.grid(row=2, column=0, sticky="ew", pady=(0, 12))

        content = ttk.Frame(container)
        content.grid(row=3, column=0, sticky="nsew")
        content.rowconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)

        self.settings_control = FrameSettingsControl(
            content,
            percentage_variable=self.percentage_variable,
            square_output_variable=self.square_output_variable,
            initial_color=self._frame_color,
            on_color_changed=self._on_color_changed,
            on_background_changed=self._on_background_changed,
        )
        self.settings_control.grid(
            row=0, column=0, sticky="new", padx=(0, 12)
        )

        self.preview_panel = PreviewPanel(
            content,
            on_source_requested=self.source_control.choose_file,
        )
        self.preview_panel.grid(row=0, column=1, sticky="nsew")

        footer = ttk.Frame(container)
        footer.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        self.progress_bar = ttk.Progressbar(footer, mode="determinate", maximum=1)
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        self.process_button = ttk.Button(
            footer,
            text="Добавить рамку",
            command=self._start_processing,
            style="Run.TButton",
        )
        self.process_button.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(
            footer,
            textvariable=self.status_variable,
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

    def _bind_events(self) -> None:
        self.source_variable.trace_add("write", self._schedule_preview)
        self.percentage_variable.trace_add("write", self._schedule_preview)
        self.square_output_variable.trace_add("write", self._schedule_preview)
        self.bind("<Control-Return>", lambda _event: self._start_processing())
        self.bind("<Control-o>", lambda _event: self.source_control.choose_file())

    def _on_source_selected(self, source: Path) -> None:
        self.output_variable.set(str(self.processor.default_output_directory(source)))
        self._schedule_preview()

    def _on_color_changed(self, color: RGBColor) -> None:
        self._frame_color = color
        self._schedule_preview()

    def _on_background_changed(self, _background_path: Path | None) -> None:
        self._schedule_preview()

    def _schedule_preview(self, *_args: object) -> None:
        self._preview_worker.invalidate()
        if self._preview_after_id is not None:
            self.after_cancel(self._preview_after_id)
        self._preview_after_id = self.after(
            self.PREVIEW_DELAY_MS,
            self._refresh_preview,
        )

    def _refresh_preview(self) -> None:
        self._preview_after_id = None
        source_text = self.source_variable.get().strip().strip('"')
        if not source_text:
            self.preview_panel.show_message(PreviewPanel.EMPTY_MESSAGE)
            return

        try:
            settings = self._read_settings()
        except (InputValidationError, OSError) as error:
            self.preview_panel.show_message(str(error))
            return

        self._preview_worker.submit(Path(source_text), settings)
        if not self._busy:
            self.status_variable.set("Обновление предпросмотра…")

    def _poll_preview_events(self) -> None:
        self._preview_poll_after_id = None
        event = self._preview_worker.poll()
        if event is not None:
            if event.error is not None:
                self.preview_panel.show_message(
                    str(event.error) or type(event.error).__name__
                )
                if not self._busy:
                    self.status_variable.set("Не удалось обновить предпросмотр")
            elif event.preview is not None:
                self.preview_panel.show_preview(event.preview)
                if not self._busy:
                    self.status_variable.set("Предпросмотр обновлён")
        self._preview_poll_after_id = self.after(80, self._poll_preview_events)

    def _read_settings(self) -> FrameSettings:
        percentage_text = self.percentage_variable.get().strip().replace(",", ".")
        try:
            percentage = float(percentage_text)
        except ValueError as error:
            raise InputValidationError("Введите числовой процент рамки.") from error
        return FrameSettings(
            percentage=percentage,
            color=self.settings_control.selected_color,
            background_path=self.settings_control.selected_background_path,
            make_square=self.square_output_variable.get(),
        )

    def _start_processing(self) -> None:
        if self._busy:
            return

        source_text = self.source_variable.get().strip().strip('"')
        output_text = self.output_variable.get().strip().strip('"')
        if not source_text:
            messagebox.showerror("Не выбран источник", "Выберите изображение или папку.")
            return

        source = Path(source_text)
        if not output_text:
            output = self.processor.default_output_directory(source)
            self.output_variable.set(str(output))
        else:
            output = Path(output_text)

        try:
            settings = self._read_settings()
            job = self.processor.create_job(source, output, settings)
        except (InputValidationError, OSError) as error:
            messagebox.showerror("Проверьте параметры", str(error))
            return

        self._active_output = job.output_directory
        self.progress_bar.configure(maximum=len(job.files), value=0)
        self._set_busy(True)
        self.status_variable.set(f"Обработка: 0 из {len(job.files)}")

        worker = threading.Thread(
            target=self._run_job_in_background,
            args=(job,),
            daemon=True,
            name="image-processor",
        )
        worker.start()
        self._poll_worker_events()

    def _run_job_in_background(self, job: ProcessingJob) -> None:
        def report_progress(
            completed: int,
            total: int,
            source_file: Path,
            succeeded: bool,
        ) -> None:
            self._worker_events.put(
                _ProgressEvent(completed, total, source_file, succeeded)
            )

        try:
            result = self.processor.run_job(job, report_progress)
        except Exception as error:  # Ошибка передаётся в главный поток tkinter.
            self._worker_events.put(_ErrorEvent(error))
        else:
            self._worker_events.put(_DoneEvent(result))

    def _poll_worker_events(self) -> None:
        self._poll_after_id = None
        while True:
            try:
                event = self._worker_events.get_nowait()
            except queue.Empty:
                break

            if isinstance(event, _ProgressEvent):
                self.progress_bar.configure(value=event.completed)
                outcome = "готово" if event.succeeded else "ошибка"
                self.status_variable.set(
                    f"{event.completed} из {event.total}: "
                    f"{event.source_file.name} — {outcome}"
                )
            elif isinstance(event, _DoneEvent):
                self._finish_processing(event.result)
                return
            elif isinstance(event, _ErrorEvent):
                self._set_busy(False)
                self.status_variable.set("Обработка прервана из-за ошибки")
                messagebox.showerror("Ошибка обработки", str(event.error))
                return

        if self._busy:
            self._poll_after_id = self.after(80, self._poll_worker_events)

    def _finish_processing(self, result: ProcessingResult) -> None:
        self._set_busy(False)
        if result.failures:
            failure_lines = [
                f"• {failure.source.name}: {failure.message}"
                for failure in result.failures[:5]
            ]
            if result.failed > 5:
                failure_lines.append(f"…и ещё {result.failed - 5}")
            details = "\n".join(failure_lines)
            self.status_variable.set(
                f"Готово: {result.succeeded}, с ошибками: {result.failed}"
            )
            messagebox.showwarning(
                "Обработка завершена",
                f"Сохранено файлов: {result.succeeded}\n"
                f"Не обработано: {result.failed}\n\n{details}",
            )
            return

        self.status_variable.set(f"Готово: сохранено файлов — {result.succeeded}")
        messagebox.showinfo(
            "Обработка завершена",
            f"Сохранено файлов: {result.succeeded}\n"
            f"Папка: {self._active_output}",
        )

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.source_control.set_enabled(not busy)
        self.output_control.set_enabled(not busy)
        self.settings_control.set_enabled(not busy)
        self.process_button.configure(state="disabled" if busy else "normal")

    def _on_close(self) -> None:
        if self._busy:
            messagebox.showwarning(
                "Идёт обработка",
                "Дождитесь завершения обработки перед закрытием приложения.",
            )
            return
        if self._preview_after_id is not None:
            self.after_cancel(self._preview_after_id)
        if self._preview_poll_after_id is not None:
            self.after_cancel(self._preview_poll_after_id)
        if self._poll_after_id is not None:
            self.after_cancel(self._poll_after_id)
        self._preview_worker.close()
        self.destroy()


def _enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def run_app() -> None:
    _enable_windows_dpi_awareness()
    app = PhotoFrameApp()
    app.mainloop()
