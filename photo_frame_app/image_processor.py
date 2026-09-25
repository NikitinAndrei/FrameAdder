"""Поиск и обработка изображений без зависимости от tkinter."""

from __future__ import annotations

import os
from collections.abc import Callable
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps

from .models import (
    FrameSettings,
    InputValidationError,
    PreviewData,
    ProcessingFailure,
    ProcessingJob,
    ProcessingResult,
)

ProgressCallback = Callable[[int, int, Path, bool], None]
IMAGE_FILE_ERRORS = (
    OSError,
    ValueError,
    KeyError,
    SyntaxError,
    Image.DecompressionBombError,
)


class ImageProcessor:
    """Сервис для создания превью и пакетной обработки изображений."""

    PREVIEW_MAX_SIDE = 1200
    SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".bmp"})
    FILE_TYPES = (
        ("Изображения", "*.jpg *.jpeg *.png *.bmp"),
        ("Все файлы", "*.*"),
    )
    _FORMATS = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".bmp": "BMP",
    }

    @classmethod
    def find_images(cls, source: Path) -> tuple[Path, ...]:
        """Вернуть поддерживаемые изображения в стабильном порядке."""

        source = Path(source).expanduser()
        if not source.exists():
            raise InputValidationError(f"Путь не существует: {source}")

        if source.is_file():
            if source.suffix.lower() not in cls.SUPPORTED_EXTENSIONS:
                raise InputValidationError(
                    "Выбранный файл имеет неподдерживаемый формат. "
                    "Используйте JPG, JPEG, PNG или BMP."
                )
            return (source,)

        if not source.is_dir():
            raise InputValidationError(f"Путь не является файлом или папкой: {source}")

        files = tuple(
            sorted(
                (
                    path
                    for path in source.iterdir()
                    if path.is_file()
                    and path.suffix.lower() in cls.SUPPORTED_EXTENSIONS
                ),
                key=lambda path: path.name.casefold(),
            )
        )
        if not files:
            raise InputValidationError(
                "В выбранной папке нет изображений JPG, JPEG, PNG или BMP."
            )
        return files

    @staticmethod
    def default_output_directory(source: Path) -> Path:
        """Предложить отдельную папку, не затрагивающую оригиналы."""

        source = Path(source)
        name = source.stem if source.is_file() else source.name
        return source.parent / f"{name}_with_frame"

    @classmethod
    def validate_background_path(cls, background_path: Path | None) -> Path | None:
        """Проверить путь к необязательному фоновому изображению."""

        if background_path is None:
            return None
        path = Path(background_path).expanduser()
        if not path.exists() or not path.is_file():
            raise InputValidationError(
                f"Фоновое изображение не найдено: {path}"
            )
        if path.suffix.lower() not in cls.SUPPORTED_EXTENSIONS:
            raise InputValidationError(
                "Фоновое изображение имеет неподдерживаемый формат. "
                "Используйте JPG, JPEG, PNG или BMP."
            )
        return path

    @classmethod
    def load_background_image(
        cls,
        background_path: Path | None,
    ) -> Image.Image | None:
        """Загрузить фон с учётом EXIF-ориентации и отвязать его от файла."""

        path = cls.validate_background_path(background_path)
        if path is None:
            return None
        try:
            with Image.open(path) as image:
                return ImageOps.exif_transpose(image).convert("RGBA")
        except IMAGE_FILE_ERRORS as error:
            raise InputValidationError(
                f"Не удалось открыть фоновое изображение {path.name}: {error}"
            ) from error

    @classmethod
    def create_job(
        cls,
        source: Path,
        output_directory: Path,
        settings: FrameSettings,
    ) -> ProcessingJob:
        source = Path(source).expanduser()
        output_directory = Path(output_directory).expanduser()
        files = cls.find_images(source)
        background_path = cls.validate_background_path(settings.background_path)

        if output_directory.exists() and not output_directory.is_dir():
            raise InputValidationError(
                f"Путь результата занят файлом: {output_directory}"
            )

        output_resolved = output_directory.resolve(strict=False)
        for source_file in files:
            cls._validate_output_path(
                source_file, output_resolved / source_file.name, background_path
            )

        return ProcessingJob(
            source=source,
            output_directory=output_directory,
            files=files,
            settings=settings,
        )

    @staticmethod
    def _validate_output_path(
        source_file: Path,
        output_file: Path,
        background_path: Path | None,
    ) -> None:
        """Защитить фотографию и фон, в том числе при обработке без create_job."""

        target = output_file.expanduser().resolve(strict=False)
        if source_file.expanduser().resolve(strict=False) == target:
            raise InputValidationError(
                "Папка результата совпадает с папкой оригиналов. "
                "Выберите другую папку, чтобы не перезаписать исходные файлы."
            )
        if (
            background_path is not None
            and Path(background_path).expanduser().resolve(strict=False) == target
        ):
            raise InputValidationError(
                "Файл результата перезапишет фоновое изображение. "
                "Выберите другую папку для готовых файлов."
            )

    @staticmethod
    def output_size(
        source_size: tuple[int, int],
        settings: FrameSettings,
    ) -> tuple[int, int]:
        width, height = source_size
        scale = Decimal(1) + Decimal(str(settings.percentage)) / 100

        def rounded_side(side: int) -> int:
            return int((Decimal(side) * scale).to_integral_value(rounding=ROUND_HALF_UP))

        if settings.make_square:
            new_side = rounded_side(max(width, height))
            return new_side, new_side
        return rounded_side(width), rounded_side(height)

    @staticmethod
    def _composite_centered(
        canvas: Image.Image,
        layer: Image.Image,
        *,
        original_canvas_size: tuple[int, int] | None = None,
    ) -> None:
        """Обрезать слой по холсту; для превью уменьшить только видимую область."""

        canvas_width, canvas_height = original_canvas_size or canvas.size
        layer_width, layer_height = layer.size
        x_offset = (canvas_width - layer_width) // 2
        y_offset = (canvas_height - layer_height) // 2

        left = max(0, -x_offset)
        top = max(0, -y_offset)
        right = min(layer_width, canvas_width - x_offset)
        bottom = min(layer_height, canvas_height - y_offset)
        if right <= left or bottom <= top:
            return

        # Целочисленное округление половин вверх без погрешности float.
        def preview_coordinate(value: int, target_side: int, original_side: int) -> int:
            return (2 * value * target_side + original_side) // (2 * original_side)

        x = preview_coordinate(x_offset + left, canvas.width, canvas_width)
        y = preview_coordinate(y_offset + top, canvas.height, canvas_height)
        x_end = preview_coordinate(x_offset + right, canvas.width, canvas_width)
        y_end = preview_coordinate(y_offset + bottom, canvas.height, canvas_height)
        if x_end <= x or y_end <= y:
            return

        if canvas.size == (canvas_width, canvas_height):
            visible_layer = layer.crop((left, top, right, bottom))
        else:
            visible_layer = layer.resize(
                (x_end - x, y_end - y),
                Image.Resampling.LANCZOS,
                box=(left, top, right, bottom),
            )
        with visible_layer:
            canvas.alpha_composite(visible_layer, dest=(x, y))

    @staticmethod
    def add_frame(
        image: Image.Image,
        settings: FrameSettings,
        background_image: Image.Image | None = None,
    ) -> Image.Image:
        """Собрать цвет, необязательный фон и основное изображение по центру."""

        oriented = ImageOps.exif_transpose(image)
        source = oriented.convert("RGBA")
        width, height = source.size
        output_width, output_height = ImageProcessor.output_size(
            (width, height),
            settings,
        )

        canvas = Image.new(
            "RGBA",
            (output_width, output_height),
            (*settings.color, 255),
        )

        if background_image is None and settings.background_path is not None:
            background_image = ImageProcessor.load_background_image(
                settings.background_path
            )
        if background_image is not None:
            prepared_background = (
                background_image
                if background_image.mode == "RGBA"
                else ImageOps.exif_transpose(background_image).convert("RGBA")
            )
            ImageProcessor._composite_centered(canvas, prepared_background)

        ImageProcessor._composite_centered(canvas, source)
        return canvas.convert("RGB")

    @classmethod
    def build_preview(cls, source: Path, settings: FrameSettings) -> PreviewData:
        files = cls.find_images(source)
        preview_file = files[0]
        background_image = cls.load_background_image(settings.background_path)
        try:
            with Image.open(preview_file) as image:
                with ImageOps.exif_transpose(image) as oriented:
                    source_size = oriented.size
                    output_size = cls.output_size(source_size, settings)
                    max_side = max(output_size)
                    preview_size = tuple(
                        max(1, (2 * side * cls.PREVIEW_MAX_SIDE + max_side) // (2 * max_side))
                        for side in output_size
                    ) if max_side > cls.PREVIEW_MAX_SIDE else output_size
                    with Image.new("RGBA", preview_size, (*settings.color, 255)) as canvas:
                        if background_image is not None:
                            cls._composite_centered(
                                canvas, background_image, original_canvas_size=output_size
                            )
                        with oriented.convert("RGBA") as foreground:
                            cls._composite_centered(
                                canvas, foreground, original_canvas_size=output_size
                            )
                        framed = canvas.convert("RGB")
        except IMAGE_FILE_ERRORS as error:
            raise InputValidationError(
                f"Не удалось открыть изображение {preview_file.name}: {error}"
            ) from error
        finally:
            if background_image is not None:
                background_image.close()

        return PreviewData(
            image=framed,
            source_file=preview_file,
            source_size=source_size,
            output_size=output_size,
            total_files=len(files),
        )

    @classmethod
    def process_file(
        cls,
        source_file: Path,
        output_file: Path,
        settings: FrameSettings,
        background_image: Image.Image | None = None,
    ) -> None:
        """Обработать один файл и атомарно заменить прежний результат."""

        cls._validate_output_path(source_file, output_file, settings.background_path)
        temporary_file = output_file.with_name(
            f".{output_file.stem}.{uuid4().hex}{output_file.suffix}"
        )
        try:
            if background_image is None and settings.background_path is not None:
                background_image = cls.load_background_image(settings.background_path)
            with Image.open(source_file) as image:
                source_info = image.info.copy()
                framed = cls.add_frame(image, settings, background_image)

            save_options: dict[str, object] = {}
            if output_file.suffix.lower() in {".jpg", ".jpeg"}:
                save_options.update(quality=95, optimize=True)
            elif output_file.suffix.lower() == ".png":
                save_options["optimize"] = True

            if source_info.get("icc_profile"):
                save_options["icc_profile"] = source_info["icc_profile"]
            if source_info.get("dpi"):
                save_options["dpi"] = source_info["dpi"]

            framed.save(
                temporary_file,
                format=cls._FORMATS[output_file.suffix.lower()],
                **save_options,
            )
            os.replace(temporary_file, output_file)
        finally:
            temporary_file.unlink(missing_ok=True)

    @classmethod
    def run_job(
        cls,
        job: ProcessingJob,
        progress_callback: ProgressCallback | None = None,
    ) -> ProcessingResult:
        background_image = cls.load_background_image(job.settings.background_path)
        try:
            job.output_directory.mkdir(parents=True, exist_ok=True)
            output_files: list[Path] = []
            failures: list[ProcessingFailure] = []
            total = len(job.files)

            for index, source_file in enumerate(job.files, start=1):
                output_file = job.output_directory / source_file.name
                succeeded = False
                try:
                    cls.process_file(
                        source_file,
                        output_file,
                        job.settings,
                        background_image,
                    )
                except IMAGE_FILE_ERRORS as error:
                    failures.append(
                        ProcessingFailure(
                            source=source_file,
                            message=str(error) or type(error).__name__,
                        )
                    )
                else:
                    output_files.append(output_file)
                    succeeded = True

                if progress_callback is not None:
                    progress_callback(index, total, source_file, succeeded)

            return ProcessingResult(tuple(output_files), tuple(failures))
        finally:
            if background_image is not None:
                background_image.close()
