"""Переиспользуемые элементы управления для главного окна."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import colorchooser, filedialog, ttk

from ..image_processor import ImageProcessor
from ..models import (
    InputValidationError,
    MAX_FRAME_PERCENTAGE,
    RGBColor,
    parse_hex_color,
    rgb_to_hex,
)

PathCallback = Callable[[Path], None]
ColorCallback = Callable[[RGBColor], None]
BackgroundCallback = Callable[[Path | None], None]


def _initial_directory(value: str) -> str | None:
    if not value.strip():
        return None
    candidate = Path(value.strip()).expanduser()
    if candidate.is_file():
        return str(candidate.parent)
    if candidate.is_dir():
        return str(candidate)
    if candidate.parent.is_dir():
        return str(candidate.parent)
    return None


class _PathControl(ttk.LabelFrame):
    """Базовый элемент с полем для пути и областью кнопок."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        title: str,
        variable: tk.StringVar,
    ) -> None:
        super().__init__(master, text=title, padding=10)
        self.variable = variable
        self._enabled = True
        self.columnconfigure(0, weight=1)
        self.entry = ttk.Entry(self, textvariable=variable)
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._buttons: list[ttk.Widget] = []

    def _add_button(self, text: str, command: Callable[[], None]) -> None:
        button = ttk.Button(self, text=text, command=command)
        button.grid(row=0, column=len(self._buttons) + 1, padx=(0, 6))
        self._buttons.append(button)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        state = "normal" if enabled else "disabled"
        self.entry.configure(state=state)
        for button in self._buttons:
            button.configure(state=state)


class SourcePathControl(_PathControl):
    """Выбор одного изображения либо папки с изображениями."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        variable: tk.StringVar,
        on_selected: PathCallback,
    ) -> None:
        super().__init__(master, title="Источник", variable=variable)
        self._on_selected = on_selected
        self._add_button("Выбрать папку…", self.choose_directory)

    def choose_file(self) -> None:
        """Открыть системный диалог выбора изображения."""

        if not self._enabled:
            return
        filename = filedialog.askopenfilename(
            parent=self,
            title="Выберите изображение",
            initialdir=_initial_directory(self.variable.get()),
            filetypes=ImageProcessor.FILE_TYPES,
        )
        if filename:
            selected_path = Path(filename)
            self.variable.set(filename)
            self._on_selected(selected_path)

    def choose_directory(self) -> None:
        """Открыть системный диалог выбора папки."""

        if not self._enabled:
            return
        directory = filedialog.askdirectory(
            parent=self,
            title="Выберите папку с изображениями",
            initialdir=_initial_directory(self.variable.get()),
            mustexist=True,
        )
        if directory:
            selected_path = Path(directory)
            self.variable.set(directory)
            self._on_selected(selected_path)

class OutputPathControl(_PathControl):
    """Выбор папки, в которую будут сохранены готовые файлы."""

    def __init__(self, master: tk.Misc, *, variable: tk.StringVar) -> None:
        super().__init__(master, title="Папка для готовых файлов", variable=variable)
        self._add_button("Выбрать…", self._choose_directory)

    def _choose_directory(self) -> None:
        directory = filedialog.askdirectory(
            parent=self,
            title="Выберите папку для готовых файлов",
            initialdir=_initial_directory(self.variable.get()),
            mustexist=False,
        )
        if directory:
            self.variable.set(directory)


class ColorPicker(ttk.Frame):
    """Кнопка выбора цвета с образцом текущего значения."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        initial_color: RGBColor,
        on_changed: ColorCallback,
    ) -> None:
        super().__init__(master)
        self.color = initial_color
        self._on_changed = on_changed
        self._updating_hex = False
        self._hex_valid = True
        self.columnconfigure(0, weight=1)

        self.button = ttk.Button(
            self,
            text="Выбрать цвет рамки…",
            command=self._choose_color,
        )
        self.button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.swatch = tk.Canvas(
            self,
            width=36,
            height=24,
            highlightthickness=1,
            highlightbackground="#808080",
        )
        self.swatch.grid(row=0, column=1)
        self._paint_swatch()

        hex_row = ttk.Frame(self)
        hex_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(9, 0))
        hex_row.columnconfigure(1, weight=1)
        ttk.Label(hex_row, text="HEX:").grid(row=0, column=0, padx=(0, 8))
        self.hex_variable = tk.StringVar(value=rgb_to_hex(initial_color))
        self.hex_entry = ttk.Entry(
            hex_row,
            textvariable=self.hex_variable,
            width=12,
        )
        self.hex_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.hex_hint = ttk.Label(hex_row, text="#RRGGBB", foreground="#5f6368")
        self.hex_hint.grid(row=0, column=2, sticky="w")
        self.hex_variable.trace_add("write", self._on_hex_edited)
        self.hex_entry.bind("<Return>", self._normalize_hex)
        self.hex_entry.bind("<FocusOut>", self._normalize_hex)

    @property
    def hex_color(self) -> str:
        return rgb_to_hex(self.color)

    @property
    def selected_color(self) -> RGBColor:
        """Цвет из HEX-поля либо понятная пользователю ошибка."""

        return parse_hex_color(self.hex_variable.get())

    def _paint_swatch(self) -> None:
        self.swatch.configure(background=self.hex_color)

    def _choose_color(self) -> None:
        rgb, _ = colorchooser.askcolor(
            color=self.hex_color,
            parent=self,
            title="Цвет рамки",
        )
        if rgb is None:
            return
        color = tuple(round(channel) for channel in rgb)  # type: ignore[assignment]
        self._set_color(color, update_hex=True)

    def _on_hex_edited(self, *_args: object) -> None:
        if self._updating_hex:
            return
        try:
            color = parse_hex_color(self.hex_variable.get())
        except InputValidationError:
            self.hex_hint.configure(text="Неверный формат", foreground="#b3261e")
            was_valid = self._hex_valid
            self._hex_valid = False
            if was_valid:
                self._on_changed(self.color)
            return

        self.hex_hint.configure(text="#RRGGBB", foreground="#5f6368")
        self._set_color(color, update_hex=False)

    def _normalize_hex(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        try:
            color = self.selected_color
        except InputValidationError:
            self.bell()
            return
        self._set_color(color, update_hex=True)

    def _set_color(self, color: RGBColor, *, update_hex: bool) -> None:
        changed = color != self.color or not self._hex_valid
        self.color = color
        self._hex_valid = True
        self._paint_swatch()
        if update_hex:
            self._updating_hex = True
            self.hex_variable.set(rgb_to_hex(color))
            self._updating_hex = False
            self.hex_hint.configure(text="#RRGGBB", foreground="#5f6368")
        if changed:
            self._on_changed(color)

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.button.configure(state=state)
        self.hex_entry.configure(state=state)


class BackgroundImagePicker(ttk.Frame):
    """Выбор необязательного изображения, которое лежит под фотографией."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_changed: BackgroundCallback,
    ) -> None:
        super().__init__(master)
        self.path: Path | None = None
        self._on_changed = on_changed
        self.columnconfigure(0, weight=1)

        self.choose_button = ttk.Button(
            self,
            text="Выбрать изображение фона…",
            command=self._choose_image,
        )
        self.choose_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.clear_button = ttk.Button(
            self,
            text="Убрать",
            command=self._clear,
            state="disabled",
        )
        self.clear_button.grid(row=0, column=1)

        self.path_variable = tk.StringVar(value="Фон не выбран — используется цвет")
        self.path_label = ttk.Label(
            self,
            textvariable=self.path_variable,
            foreground="#5f6368",
            wraplength=260,
        )
        self.path_label.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(7, 0),
        )

    @property
    def selected_path(self) -> Path | None:
        return self.path

    def _choose_image(self) -> None:
        filename = filedialog.askopenfilename(
            parent=self,
            title="Выберите фоновое изображение",
            initialdir=_initial_directory(str(self.path or "")),
            filetypes=ImageProcessor.FILE_TYPES,
        )
        if not filename:
            return
        self.path = Path(filename)
        self.path_variable.set(f"Фон: {self.path}")
        self.clear_button.configure(state="normal")
        self._on_changed(self.path)

    def _clear(self) -> None:
        if self.path is None:
            return
        self.path = None
        self.path_variable.set("Фон не выбран — используется цвет")
        self.clear_button.configure(state="disabled")
        self._on_changed(None)

    def set_enabled(self, enabled: bool) -> None:
        self.choose_button.configure(state="normal" if enabled else "disabled")
        clear_enabled = enabled and self.path is not None
        self.clear_button.configure(state="normal" if clear_enabled else "disabled")


class FrameSettingsControl(ttk.LabelFrame):
    """Настройки толщины и цвета рамки."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        percentage_variable: tk.StringVar,
        square_output_variable: tk.BooleanVar,
        initial_color: RGBColor,
        on_color_changed: ColorCallback,
        on_background_changed: BackgroundCallback,
    ) -> None:
        super().__init__(master, text="Настройки рамки", padding=12)
        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="Размер, %:").grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        self.percentage_spinbox = ttk.Spinbox(
            self,
            from_=0,
            to=MAX_FRAME_PERCENTAGE,
            increment=1,
            width=9,
            textvariable=percentage_variable,
        )
        self.percentage_spinbox.grid(row=0, column=1, sticky="w")

        self.square_checkbutton = ttk.Checkbutton(
            self,
            text="Оквадратить",
            variable=square_output_variable,
        )
        self.square_checkbutton.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(10, 0),
        )

        ttk.Label(
            self,
            text=(
                "Включено: Квадрат \n"
                "Выключено: Рамка одинаковой ширины"
            ),
            wraplength=260,
            foreground="#5f6368",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 14))

        self.color_picker = ColorPicker(
            self,
            initial_color=initial_color,
            on_changed=on_color_changed,
        )
        self.color_picker.grid(row=3, column=0, columnspan=2, sticky="ew")

        self.background_picker = BackgroundImagePicker(
            self,
            on_changed=on_background_changed,
        )
        self.background_picker.grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(14, 0),
        )

    def set_enabled(self, enabled: bool) -> None:
        self.percentage_spinbox.configure(
            state="normal" if enabled else "disabled"
        )
        self.square_checkbutton.configure(
            state="normal" if enabled else "disabled"
        )
        self.color_picker.set_enabled(enabled)
        self.background_picker.set_enabled(enabled)

    @property
    def selected_color(self) -> RGBColor:
        return self.color_picker.selected_color

    @property
    def selected_background_path(self) -> Path | None:
        return self.background_picker.selected_path
