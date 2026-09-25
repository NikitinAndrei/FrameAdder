"""Панель масштабируемого превью результата."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from PIL import Image, ImageTk

from ..models import PreviewData


class PreviewPanel(ttk.LabelFrame):
    """Показывает готовую рамку, сохраняя пропорции изображения."""

    EMPTY_MESSAGE = "Двойной щёлчок для выбора картинки"

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_source_requested: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, text="Предпросмотр", padding=10)
        self._on_source_requested = on_source_requested
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            self,
            background="#252525",
            highlightthickness=0,
            width=520,
            height=390,
            cursor="hand2" if on_source_requested is not None else "",
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.info_variable = tk.StringVar(value=self.EMPTY_MESSAGE)
        self.info_label = ttk.Label(
            self,
            textvariable=self.info_variable,
            anchor="center",
            justify="center",
        )
        self.info_label.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        self._image: Image.Image | None = None
        self._photo_image: ImageTk.PhotoImage | None = None
        self._message = self.EMPTY_MESSAGE
        self.canvas.bind("<Configure>", self._render)
        if on_source_requested is not None:
            self.canvas.bind("<Double-Button-1>", self._request_source)
            self.info_label.bind("<Double-Button-1>", self._request_source)
        self._render()

    def _request_source(self, _event: tk.Event[tk.Misc]) -> None:
        if self._on_source_requested is not None:
            self._on_source_requested()

    def show_preview(self, preview: PreviewData) -> None:
        self._image = preview.image
        self._message = ""
        width, height = preview.source_size
        result_width, result_height = preview.output_size
        count_text = (
            f"первая из {preview.total_files}"
            if preview.total_files > 1
            else "1 файл"
        )
        self.info_variable.set(
            f"{preview.source_file.name} ({count_text})  •  "
            f"{width}×{height} → {result_width}×{result_height}"
        )
        self._render()

    def show_message(self, message: str) -> None:
        self._image = None
        self._photo_image = None
        self._message = message
        self.info_variable.set(message)
        self._render()

    def _render(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self.canvas.delete("all")
        canvas_width = max(self.canvas.winfo_width(), 1)
        canvas_height = max(self.canvas.winfo_height(), 1)

        if self._image is None:
            self.canvas.create_text(
                canvas_width // 2,
                canvas_height // 2,
                text=self._message,
                fill="#d0d0d0",
                width=max(canvas_width - 40, 40),
                justify="center",
            )
            return

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
