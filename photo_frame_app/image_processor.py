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
    MATRIX_TEMPLATES,
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

    @staticmethod
    def collage_output_name(source_files: tuple[Path, ...]) -> str:
        """Составить имя коллажа из имён всех исходных изображений."""

        return "+".join(Path(source_file).stem for source_file in source_files) + ".png"

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

    @classmethod
    def create_collage_job(
        cls,
        sources: tuple[Path, ...],
        output_directory: Path,
        settings: FrameSettings,
    ) -> ProcessingJob:
        """Создать задание на один коллаж из выбранных файлов."""

        rows, columns = MATRIX_TEMPLATES[settings.matrix_template]
        required = rows * columns
        if settings.matrix_template == "1x1" or len(sources) != required:
            raise InputValidationError(
                f"Для шаблона {settings.matrix_template} выберите {required} изображения."
            )
        files = tuple(cls.find_images(Path(source))[0] for source in sources)
        output_directory = Path(output_directory).expanduser()
        background_path = cls.validate_background_path(settings.background_path)
        if output_directory.exists() and not output_directory.is_dir():
            raise InputValidationError(
                f"Путь результата занят файлом: {output_directory}"
            )
        output_file = output_directory.resolve(strict=False) / cls.collage_output_name(
            files
        )
        for source_file in files:
            cls._validate_output_path(source_file, output_file, background_path)
        return ProcessingJob(
            source=files[0],
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
        frame = int(
            (
                Decimal(max(width, height))
                * Decimal(str(settings.percentage))
                / 200
            ).to_integral_value(rounding=ROUND_HALF_UP)
        )
        return width + 2 * frame, height + 2 * frame

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
        if settings.rotations and settings.rotations[0] == 180:
            source = source.rotate(180)
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

    @staticmethod
    def _prepare_collage_sources(
        images: tuple[Image.Image, ...],
        rows: int,
        columns: int,
    ) -> tuple[tuple[Image.Image, ...], int]:
        """Ориентировать изображения и найти общий размер ячейки без увеличения."""

        prepared: list[Image.Image] = []
        cell_scale: int | None = None
        for image in images:
            source = ImageOps.exif_transpose(image).convert("RGBA")
            width, height = source.size
            if columns > rows and width > height:
                oriented = source.transpose(Image.Transpose.ROTATE_270)
                source.close()
                source = oriented
            elif rows > columns and height > width:
                oriented = source.transpose(Image.Transpose.ROTATE_270)
                source.close()
                source = oriented
            width, height = source.size
            available_scale = min(width // rows, height // columns)
            if available_scale < 1:
                source.close()
                for item in prepared:
                    item.close()
                raise InputValidationError("Изображение слишком мало для выбранного шаблона.")
            cell_scale = (
                available_scale
                if cell_scale is None
                else min(cell_scale, available_scale)
            )
            prepared.append(source)
        assert cell_scale is not None
        return tuple(prepared), cell_scale

    @classmethod
    def create_collage(
        cls,
        images: tuple[Image.Image, ...],
        settings: FrameSettings,
        background_image: Image.Image | None = None,
        *,
        max_side: int | None = None,
    ) -> tuple[Image.Image, tuple[int, int]]:
        """Собрать квадратную матрицу с общей внешней рамкой и рамкой на стыках."""

        rows, columns = MATRIX_TEMPLATES[settings.matrix_template]
        required = rows * columns
        if settings.matrix_template == "1x1" or len(images) != required:
            raise InputValidationError(
                f"Для шаблона {settings.matrix_template} выберите {required} изображения."
            )
        prepared, cell_scale = cls._prepare_collage_sources(images, rows, columns)
        try:
            if not settings.make_square and (rows == 1 or columns == 1):
                return cls._create_linear_collage(
                    prepared,
                    settings,
                    rows,
                    columns,
                    background_image,
                    max_side=max_side,
                )
            base_side = rows * columns * cell_scale
            output_side = cls.output_size(
                (base_side, base_side),
                FrameSettings(percentage=settings.percentage),
            )[0]
            rendered_side = min(output_side, max_side) if max_side else output_side
            ratio = rendered_side / output_side
            frame = (output_side - base_side) / 2
            canvas = Image.new(
                "RGBA", (rendered_side, rendered_side), (*settings.color, 255)
            )
            if background_image is None and settings.background_path is not None:
                background_image = cls.load_background_image(settings.background_path)
            if background_image is not None:
                prepared_background = (
                    background_image
                    if background_image.mode == "RGBA"
                    else ImageOps.exif_transpose(background_image).convert("RGBA")
                )
                cls._composite_centered(
                    canvas,
                    prepared_background,
                    original_canvas_size=(output_side, output_side),
                )

            rotations = settings.rotations + (0,) * (required - len(settings.rotations))
            for index, source in enumerate(prepared):
                row, column = divmod(index, columns)
                left_boundary = output_side * column / columns
                right_boundary = output_side * (column + 1) / columns
                top_boundary = output_side * row / rows
                bottom_boundary = output_side * (row + 1) / rows
                left = left_boundary + (frame if column == 0 else frame / 2)
                right = right_boundary - (
                    frame if column == columns - 1 else frame / 2
                )
                top = top_boundary + (frame if row == 0 else frame / 2)
                bottom = bottom_boundary - (
                    frame if row == rows - 1 else frame / 2
                )
                box = (
                    round(left * ratio),
                    round(top * ratio),
                    round(right * ratio),
                    round(bottom * ratio),
                )
                target_size = (max(1, box[2] - box[0]), max(1, box[3] - box[1]))
                rotated = source.rotate(180) if rotations[index] == 180 else source
                try:
                    with ImageOps.contain(
                        rotated,
                        target_size,
                        Image.Resampling.LANCZOS,
                    ) as fitted:
                        x = box[0] + (target_size[0] - fitted.width) // 2
                        y = box[1] + (target_size[1] - fitted.height) // 2
                        canvas.alpha_composite(fitted, dest=(x, y))
                finally:
                    if rotated is not source:
                        rotated.close()
            return canvas.convert("RGB"), (output_side, output_side)
        finally:
            for source in prepared:
                source.close()

    @classmethod
    def _create_linear_collage(
        cls,
        sources: tuple[Image.Image, ...],
        settings: FrameSettings,
        rows: int,
        columns: int,
        background_image: Image.Image | None,
        *,
        max_side: int | None,
    ) -> tuple[Image.Image, tuple[int, int]]:
        """Собрать линейный коллаж с одинаковой рамкой без оквадрачивания."""

        if rows == 1:
            shared_side = min(source.height for source in sources)
            image_sizes = tuple(
                (
                    max(1, round(source.width * shared_side / source.height)),
                    shared_side,
                )
                for source in sources
            )
            base_width = sum(width for width, _height in image_sizes)
            base_height = shared_side
        else:
            shared_side = min(source.width for source in sources)
            image_sizes = tuple(
                (
                    shared_side,
                    max(1, round(source.height * shared_side / source.width)),
                )
                for source in sources
            )
            base_width = shared_side
            base_height = sum(height for _width, height in image_sizes)

        frame = int(
            (
                Decimal(max(base_width, base_height))
                * Decimal(str(settings.percentage))
                / 200
            ).to_integral_value(rounding=ROUND_HALF_UP)
        )
        output_size: tuple[int, int] = (
            base_width + (columns + 1) * frame,
            base_height + (rows + 1) * frame,
        )
        ratio = (
            min(1.0, max_side / max(output_size))
            if max_side is not None
            else 1.0
        )
        rendered_size: tuple[int, int] | list[int] = [max(1, round(side * ratio)) for side in output_size]
        canvas = Image.new("RGBA", rendered_size, (*settings.color, 255))
        if background_image is not None:
            prepared_background = (
                background_image
                if background_image.mode == "RGBA"
                else ImageOps.exif_transpose(background_image).convert("RGBA")
            )
            cls._composite_centered(
                canvas,
                prepared_background,
                original_canvas_size=output_size,
            )

        rotations = settings.rotations + (0,) * (len(sources) - len(settings.rotations))
        x = frame
        y = frame
        for index, (source, image_size) in enumerate(zip(sources, image_sizes)):
            rotated = source.rotate(180) if rotations[index] == 180 else source
            target_size = tuple(max(1, round(side * ratio)) for side in image_size)
            try:
                with rotated.resize(target_size, Image.Resampling.LANCZOS) as resized:
                    canvas.alpha_composite(
                        resized,
                        dest=(round(x * ratio), round(y * ratio)),
                    )
            finally:
                if rotated is not source:
                    rotated.close()
            if rows == 1:
                x += image_size[0] + frame
            else:
                y += image_size[1] + frame
        return canvas.convert("RGB"), output_size

    @classmethod
    def build_preview(
        cls,
        source: Path | tuple[Path, ...],
        settings: FrameSettings,
    ) -> PreviewData:
        if settings.matrix_template != "1x1":
            if not isinstance(source, tuple):
                raise InputValidationError("Выберите изображения для всех ячеек коллажа.")
            background_image = cls.load_background_image(settings.background_path)
            opened: list[Image.Image] = []
            try:
                for path in source:
                    opened.append(Image.open(path))
                framed, output_size = cls.create_collage(
                    tuple(opened),
                    settings,
                    background_image,
                    max_side=cls.PREVIEW_MAX_SIDE,
                )
            except IMAGE_FILE_ERRORS as error:
                raise InputValidationError(f"Не удалось собрать коллаж: {error}") from error
            finally:
                for image in opened:
                    image.close()
                if background_image is not None:
                    background_image.close()
            return PreviewData(
                image=framed,
                source_file=source[0],
                source_size=output_size,
                output_size=output_size,
                total_files=len(source),
            )

        if isinstance(source, tuple):
            source = source[0]
        files = cls.find_images(source)
        preview_file = files[0]
        background_image = cls.load_background_image(settings.background_path)
        try:
            with Image.open(preview_file) as image:
                with ImageOps.exif_transpose(image) as oriented:
                    source_size = oriented.size
                    output_size = cls.output_size(source_size, settings)
                    max_side = max(output_size)
                    preview_size = list(
                        max(1, (2 * side * cls.PREVIEW_MAX_SIDE + max_side) // (2 * max_side))
                        for side in output_size
                    ) if max_side > cls.PREVIEW_MAX_SIDE else output_size
                    with Image.new("RGBA", preview_size, (*settings.color, 255)) as canvas:
                        if background_image is not None:
                            cls._composite_centered(
                                canvas, background_image, original_canvas_size=output_size
                            )
                        with oriented.convert("RGBA") as foreground:
                            if settings.rotations and settings.rotations[0] == 180:
                                with foreground.rotate(180) as rotated:
                                    cls._composite_centered(
                                        canvas,
                                        rotated,
                                        original_canvas_size=output_size,
                                    )
                            else:
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
    def process_collage(
        cls,
        source_files: tuple[Path, ...],
        output_file: Path,
        settings: FrameSettings,
        background_image: Image.Image | None = None,
    ) -> None:
        """Собрать коллаж и атомарно сохранить его в PNG."""

        for source_file in source_files:
            cls._validate_output_path(source_file, output_file, settings.background_path)
        temporary_file = output_file.with_name(
            f".{output_file.stem}.{uuid4().hex}{output_file.suffix}"
        )
        opened: list[Image.Image] = []
        try:
            for source_file in source_files:
                opened.append(Image.open(source_file))
            collage, _ = cls.create_collage(
                tuple(opened), settings, background_image
            )
            with collage:
                collage.save(temporary_file, format="PNG", optimize=True)
            os.replace(temporary_file, output_file)
        finally:
            for image in opened:
                image.close()
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
            if job.settings.matrix_template != "1x1":
                output_file = job.output_directory / cls.collage_output_name(job.files)
                try:
                    cls.process_collage(
                        job.files, output_file, job.settings, background_image
                    )
                except IMAGE_FILE_ERRORS as error:
                    if progress_callback is not None:
                        progress_callback(1, 1, job.files[0], False)
                    return ProcessingResult(
                        (),
                        (
                            ProcessingFailure(
                                job.files[0], str(error) or type(error).__name__
                            ),
                        ),
                    )
                if progress_callback is not None:
                    progress_callback(1, 1, job.files[0], True)
                return ProcessingResult((output_file,), ())

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
