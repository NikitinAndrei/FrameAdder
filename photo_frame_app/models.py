"""Модели данных приложения, не зависящие от графического интерфейса."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from re import fullmatch
from typing import TypeAlias

from PIL import Image

RGBColor: TypeAlias = tuple[int, int, int]
MAX_FRAME_PERCENTAGE = 200.0


class InputValidationError(ValueError):
    """Ошибка в параметрах задания, которую можно показать пользователю."""


def parse_hex_color(value: str) -> RGBColor:
    """Преобразовать #RRGGBB (или RRGGBB) в RGB."""

    normalized = value.strip()
    if normalized.startswith("#"):
        normalized = normalized[1:]
    if fullmatch(r"[0-9a-fA-F]{6}", normalized) is None:
        raise InputValidationError("Введите цвет в формате #RRGGBB, например #FFFFFF.")
    return (
        int(normalized[0:2], 16),
        int(normalized[2:4], 16),
        int(normalized[4:6], 16),
    )


def rgb_to_hex(color: RGBColor) -> str:
    """Вернуть RGB-цвет в каноническом HEX-формате."""

    return "#{:02X}{:02X}{:02X}".format(*color)


@dataclass(frozen=True, slots=True)
class FrameSettings:
    """Параметры создаваемой рамки."""

    percentage: float = 16.0
    color: RGBColor = (255, 255, 255)
    background_path: Path | None = None
    make_square: bool = True

    def __post_init__(self) -> None:
        if not isfinite(self.percentage):
            raise InputValidationError("Процент рамки должен быть конечным числом.")
        if not 0 <= self.percentage <= MAX_FRAME_PERCENTAGE:
            raise InputValidationError(
                f"Процент рамки должен быть от 0 до {MAX_FRAME_PERCENTAGE:g}."
            )
        if len(self.color) != 3 or any(
            not isinstance(channel, int) or not 0 <= channel <= 255
            for channel in self.color
        ):
            raise InputValidationError("Цвет рамки должен быть задан в формате RGB.")


@dataclass(frozen=True, slots=True)
class ProcessingJob:
    """Полностью проверенное задание на обработку."""

    source: Path
    output_directory: Path
    files: tuple[Path, ...]
    settings: FrameSettings


@dataclass(frozen=True, slots=True)
class ProcessingFailure:
    source: Path
    message: str


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    output_files: tuple[Path, ...]
    failures: tuple[ProcessingFailure, ...]

    @property
    def succeeded(self) -> int:
        return len(self.output_files)

    @property
    def failed(self) -> int:
        return len(self.failures)


@dataclass(frozen=True, slots=True)
class PreviewData:
    image: Image.Image
    source_file: Path
    source_size: tuple[int, int]
    output_size: tuple[int, int]
    total_files: int
