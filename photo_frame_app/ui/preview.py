"""Панель масштабируемого превью результата и выбор матрицы коллажа."""

from __future__ import annotations

import sys
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageTk

from ..models import MATRIX_TEMPLATES, PreviewData


class PreviewPanel(ttk.LabelFrame):
    """Показывает результат и ячейки выбранного шаблона."""

    EMPTY_MESSAGE = "Двойной щёлчок для выбора картинки"

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_source_requested: Callable[[int], None],
        on_template_changed: Callable[[str], None],
        on_rotate_requested: Callable[[int], None],
        template_icons: dict[str, Path],
    ) -> None:
        super().__init__(master, text="Предпросмотр", padding=10)
        self._on_source_requested = on_source_requested
        self._on_template_changed = on_template_changed
        self._on_rotate_requested = on_rotate_requested
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            self,
            background="#252525",
            highlightthickness=0,
            width=520,
            height=390,
            cursor="hand2",
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")

        style = ttk.Style(self)
        style.configure("Template.Toolbutton", padding=(4, 2))
        style.map(
            "Template.Toolbutton",
            relief=[("selected", "sunken"), ("!selected", "raised")],
        )
        ttk.Label(
            self,
            text="Клик по фото для поворота",
            foreground="#8a8a8a",
            font=("Segoe UI", 8),
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        template_row = ttk.Frame(self)
        template_row.grid(row=2, column=0, pady=(2, 0))
        ttk.Label(template_row, text="Шаблон:", font=("Arial", 16)).grid(
            row=0, column=0, padx=(0, 8), pady=(0, 0)
        )
        self.template_variable = tk.StringVar(value="1x1")
        self._template_images = {
            name: tk.PhotoImage(file=str(path)).subsample(2)
            for name, path in template_icons.items()
        }
        self._template_buttons: list[ttk.Button] = []
        for column, name in enumerate(MATRIX_TEMPLATES, start=1):
            button = ttk.Button(
                template_row,
                image=self._template_images[name],
                compound=tk.CENTER,
                command=lambda template=name: self._select_template(template),
                style="Template.Toolbutton",
            )
            button.grid(row=0, column=column, padx=5)
            self._template_buttons.append(button)
        self._template_buttons[0].state(["selected"])

        self._template = "1x1"
        self._enabled = True
        self._sources: tuple[Path | None, ...] = (None,)
        self._image: Image.Image | None = None
        self._photo_image: ImageTk.PhotoImage | None = None
        self._message = self.EMPTY_MESSAGE
        self._click_after_id: str | None = None
        self._click_delay_ms = self._system_double_click_time()
        self.canvas.bind("<Configure>", self._render)
        self.canvas.bind("<Button-1>", self._schedule_rotation)
        self.canvas.bind("<Double-Button-1>", self._request_source)
        self._render()

    def _select_template(self, template: str) -> None:
        self._cancel_scheduled_rotation()
        self.template_variable.set(template)
        for name, button in zip(MATRIX_TEMPLATES, self._template_buttons):
            button.state(["selected"] if name == template else ["!selected"])
        self._template = template
        count = self.cell_count
        self._sources = (self._sources + (None,) * count)[:count]
        if self._image is not None:
            self._image.close()
        self._image = None
        self._photo_image = None
        self._render()
        self._on_template_changed(self._template)

    @property
    def cell_count(self) -> int:
        rows, columns = MATRIX_TEMPLATES[self._template]
        return rows * columns

    def set_sources(self, sources: tuple[Path | None, ...]) -> None:
        self._sources = (sources + (None,) * self.cell_count)[: self.cell_count]
        if self._image is not None:
            self._image.close()
        self._image = None
        self._photo_image = None
        self._message = self.EMPTY_MESSAGE
        self._render()

    @staticmethod
    def _system_double_click_time() -> int:
        if sys.platform == "win32":
            try:
                from ctypes import windll

                return int(windll.user32.GetDoubleClickTime())
            except (AttributeError, OSError, TypeError, ValueError):
                pass
        return 400

    def _cell_at(self, event: tk.Event[tk.Misc]) -> int:
        rows, columns = MATRIX_TEMPLATES[self._template]
        column = min(
            columns - 1,
            max(0, event.x * columns // max(1, self.canvas.winfo_width())),
        )
        row = min(
            rows - 1,
            max(0, event.y * rows // max(1, self.canvas.winfo_height())),
        )
        return row * columns + column

    def _cancel_scheduled_rotation(self) -> None:
        if self._click_after_id is not None:
            self.after_cancel(self._click_after_id)
            self._click_after_id = None

    def _schedule_rotation(self, event: tk.Event[tk.Misc]) -> None:
        if not self._enabled:
            return
        self._cancel_scheduled_rotation()
        slot = self._cell_at(event)
        self._click_after_id = self.after(
            self._click_delay_ms,
            lambda: self._rotate_from_click(slot),
        )

    def _rotate_from_click(self, slot: int) -> None:
        self._click_after_id = None
        if (
            self._enabled
            and slot < len(self._sources)
            and self._sources[slot] is not None
        ):
            self._on_rotate_requested(slot)

    def _request_source(self, event: tk.Event[tk.Misc]) -> None:
        if not self._enabled:
            return
        self._cancel_scheduled_rotation()
        self._on_source_requested(self._cell_at(event))

    def set_enabled(self, enabled: bool) -> None:
        if not enabled:
            self._cancel_scheduled_rotation()
        self._enabled = enabled
        state = ["!disabled"] if enabled else ["disabled"]
        for button in self._template_buttons:
            button.state(state)

    def show_preview(self, preview: PreviewData) -> None:
        if self._image is not None:
            self._image.close()
        self._image = preview.image
        self._message = ""
        self._render()

    def show_message(self, message: str) -> None:
        if self._image is not None:
            self._image.close()
        self._image = None
        self._photo_image = None
        self._message = message
        self._render()

    def _render(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self.canvas.delete("all")
        canvas_width = max(self.canvas.winfo_width(), 1)
        canvas_height = max(self.canvas.winfo_height(), 1)

        if self._image is not None:
            display_image = self._image.copy()
            display_image.thumbnail(
                (max(canvas_width - 24, 1), max(canvas_height - 24, 1)),
                Image.Resampling.LANCZOS,
            )
            self._photo_image = ImageTk.PhotoImage(display_image)
            self.canvas.create_image(
                canvas_width // 2,
                canvas_height // 2,
                image=self._photo_image,
                anchor="center",
            )
            return

        rows, columns = MATRIX_TEMPLATES[self._template]
        for index in range(rows * columns):
            row, column = divmod(index, columns)
            left = column * canvas_width // columns + 3
            right = (column + 1) * canvas_width // columns - 3
            top = row * canvas_height // rows + 3
            bottom = (row + 1) * canvas_height // rows - 3
            self.canvas.create_rectangle(
                left, top, right, bottom, outline="#707070", width=1
            )
            source = self._sources[index] if index < len(self._sources) else None
            if source is not None:
                text = source.name
            elif self.cell_count > 1:
                text = f"Изображение {index + 1}\n{self.EMPTY_MESSAGE}"
            else:
                text = self._message
            self.canvas.create_text(
                (left + right) // 2,
                (top + bottom) // 2,
                text=text,
                fill="#d0d0d0",
                width=max(right - left - 20, 40),
                justify="center",
            )
        if (
            self._message
            and self._message != self.EMPTY_MESSAGE
            and all(source is not None for source in self._sources)
        ):
            self.canvas.create_rectangle(
                20,
                canvas_height // 2 - 35,
                canvas_width - 20,
                canvas_height // 2 + 35,
                fill="#252525",
                outline="#707070",
            )
            self.canvas.create_text(
                canvas_width // 2,
                canvas_height // 2,
                text=self._message,
                fill="#d0d0d0",
                width=max(canvas_width - 60, 40),
                justify="center",
            )
