"""Точка входа в приложение для добавления рамки к фотографиям."""

from decimal import Decimal
from pathlib import Path

from PIL import Image

from photo_frame_app.image_processor import ImageProcessor
from photo_frame_app.models import FrameSettings, ProcessingResult
from photo_frame_app.ui.main_window import run_app


def add_white_border_to_square(
    image: Image.Image,
    extra_percent: float = 0.26,
) -> Image.Image:
    """Совместимая с исходным скриптом функция добавления белой рамки."""

    settings = FrameSettings(
        percentage=float(Decimal(str(extra_percent)) * 100),
        color=(255, 255, 255),
    )
    return ImageProcessor.add_frame(image, settings)


def process_folder(
    input_folder: Path,
    percentage: float = 0.16,
    output_path: Path | None = None,
    color: tuple[int, int, int] = (255, 255, 255),
    background_path: Path | None = None,
    make_square: bool = True,
) -> ProcessingResult:
    """Обработать папку без запуска GUI (оставлено для обратной совместимости)."""

    processor = ImageProcessor()
    input_folder = Path(input_folder)
    destination = output_path or processor.default_output_directory(input_folder)
    job = processor.create_job(
        input_folder,
        Path(destination),
        FrameSettings(
            percentage=float(Decimal(str(percentage)) * 100),
            color=color,
            background_path=background_path,
            make_square=make_square,
        ),
    )
    return processor.run_job(job)


def main() -> None:
    run_app()


if __name__ == "__main__":
    main()
