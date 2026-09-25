from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from photo_frame_app.image_processor import ImageProcessor
from photo_frame_app.models import (
    FrameSettings,
    InputValidationError,
    parse_hex_color,
    rgb_to_hex,
)


class ImageProcessorTests(unittest.TestCase):
    def test_hex_color_conversion(self) -> None:
        self.assertEqual(parse_hex_color("#12aBcF"), (18, 171, 207))
        self.assertEqual(parse_hex_color("12ABCF"), (18, 171, 207))
        self.assertEqual(rgb_to_hex((18, 171, 207)), "#12ABCF")

        for invalid_color in (
            "#FFF",
            "#GG0000",
            "#-1FF00",
            "#+1+2+3",
            "12 AB CF",
            "1234567",
            "",
        ):
            with self.subTest(invalid_color=invalid_color):
                with self.assertRaises(InputValidationError):
                    parse_hex_color(invalid_color)

    def test_percentage_is_limited_to_two_hundred(self) -> None:
        FrameSettings(percentage=0)
        FrameSettings(percentage=200)

        for percentage in (-0.1, 200.1, float("inf")):
            with self.subTest(percentage=percentage):
                with self.assertRaises(InputValidationError):
                    FrameSettings(percentage=percentage)

    def test_add_frame_uses_largest_side_and_percentage(self) -> None:
        source = Image.new("RGB", (100, 50), (200, 10, 20))

        result = ImageProcessor.add_frame(
            source,
            FrameSettings(percentage=20, color=(1, 2, 3)),
        )

        self.assertEqual(result.size, (120, 120))
        self.assertEqual(result.getpixel((0, 0)), (1, 2, 3))
        self.assertEqual(result.getpixel((60, 60)), (200, 10, 20))

    def test_proportional_frame_keeps_rectangular_shape(self) -> None:
        source = Image.new("RGB", (100, 50), (200, 10, 20))

        result = ImageProcessor.add_frame(
            source,
            FrameSettings(
                percentage=20,
                color=(1, 2, 3),
                make_square=False,
            ),
        )

        self.assertEqual(result.size, (120, 60))
        self.assertEqual(result.getpixel((0, 0)), (1, 2, 3))
        self.assertEqual(result.getpixel((9, 30)), (1, 2, 3))
        self.assertEqual(result.getpixel((10, 5)), (200, 10, 20))

    def test_output_size_rounds_halves_up(self) -> None:
        settings = FrameSettings(percentage=10, make_square=False)

        self.assertEqual(ImageProcessor.output_size((5, 3), settings), (6, 3))

        settings = FrameSettings(percentage=16, make_square=False)
        self.assertEqual(ImageProcessor.output_size((100, 50), settings), (116, 58))

    def test_transparent_pixels_are_composited_over_frame_color(self) -> None:
        source = Image.new("RGBA", (10, 10), (255, 0, 0, 0))

        result = ImageProcessor.add_frame(
            source,
            FrameSettings(percentage=10, color=(20, 30, 40)),
        )

        self.assertEqual(result.mode, "RGB")
        self.assertEqual(result.getpixel((5, 5)), (20, 30, 40))

    def test_large_background_is_centered_and_cropped_without_scaling(self) -> None:
        source = Image.new("RGB", (4, 2), (220, 10, 20))
        background = Image.new("RGB", (10, 10))
        for y in range(10):
            for x in range(10):
                background.putpixel((x, y), (x * 10, y * 10, 0))

        result = ImageProcessor.add_frame(
            source,
            FrameSettings(percentage=50, color=(1, 2, 3)),
            background,
        )

        self.assertEqual(result.size, (6, 6))
        self.assertEqual(result.getpixel((0, 0)), (20, 20, 0))
        self.assertEqual(result.getpixel((5, 5)), (70, 70, 0))
        self.assertEqual(result.getpixel((2, 2)), (220, 10, 20))

    def test_small_background_is_not_stretched(self) -> None:
        transparent_source = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        small_background = Image.new("RGB", (2, 2), (10, 200, 30))

        result = ImageProcessor.add_frame(
            transparent_source,
            FrameSettings(percentage=20, color=(4, 5, 6)),
            small_background,
        )

        self.assertEqual(result.size, (12, 12))
        self.assertEqual(result.getpixel((5, 5)), (10, 200, 30))
        self.assertEqual(result.getpixel((4, 5)), (4, 5, 6))

    def test_folder_images_are_sorted_and_non_images_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            Image.new("RGB", (2, 2)).save(folder / "z.png")
            Image.new("RGB", (2, 2)).save(folder / "A.jpg")
            (folder / "notes.txt").write_text("not an image", encoding="utf-8")

            files = ImageProcessor.find_images(folder)

            self.assertEqual([path.name for path in files], ["A.jpg", "z.png"])

    def test_job_rejects_overwriting_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            Image.new("RGB", (2, 2)).save(folder / "photo.png")

            with self.assertRaises(InputValidationError):
                ImageProcessor.create_job(folder, folder, FrameSettings())

    def test_job_rejects_overwriting_background_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.png"
            output = root / "output"
            background = output / "source.png"
            Image.new("RGB", (2, 2)).save(source)
            output.mkdir()
            Image.new("RGB", (2, 2)).save(background)

            with self.assertRaisesRegex(InputValidationError, "фоновое изображение"):
                ImageProcessor.create_job(
                    source,
                    output,
                    FrameSettings(background_path=background),
                )

    def test_job_processes_supported_files_and_reports_corrupt_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            Image.new("RGB", (40, 20), (255, 0, 0)).save(source / "ok.png")
            (source / "broken.jpg").write_bytes(b"not a jpeg")
            progress: list[tuple[int, bool]] = []

            job = ImageProcessor.create_job(
                source,
                output,
                FrameSettings(percentage=25, color=(0, 0, 0)),
            )
            result = ImageProcessor.run_job(
                job,
                lambda completed, _total, _path, succeeded: progress.append(
                    (completed, succeeded)
                ),
            )

            self.assertEqual(result.succeeded, 1)
            self.assertEqual(result.failed, 1)
            self.assertEqual(len(progress), 2)
            with Image.open(output / "ok.png") as processed:
                self.assertEqual(processed.size, (50, 50))

    def test_job_loads_selected_background_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            Image.new("RGB", (40, 20), (255, 0, 0)).save(source / "photo.png")
            background_path = root / "background.png"
            Image.new("RGB", (100, 100), (0, 180, 40)).save(background_path)

            job = ImageProcessor.create_job(
                source,
                output,
                FrameSettings(
                    percentage=25,
                    color=(0, 0, 0),
                    background_path=background_path,
                ),
            )
            result = ImageProcessor.run_job(job)

            self.assertEqual(result.succeeded, 1)
            with Image.open(output / "photo.png") as processed:
                self.assertEqual(processed.size, (50, 50))
                self.assertEqual(processed.getpixel((0, 0)), (0, 180, 40))
                self.assertEqual(processed.getpixel((25, 25)), (255, 0, 0))

    def test_preview_is_limited_without_changing_reported_output_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "source.png"
            Image.new("RGB", (1600, 1000), (220, 10, 20)).save(source)

            preview = ImageProcessor.build_preview(
                source,
                FrameSettings(percentage=200, color=(1, 2, 3)),
            )
            self.addCleanup(preview.image.close)

            self.assertEqual(preview.output_size, (4800, 4800))
            self.assertEqual(preview.image.size, (1200, 1200))
            self.assertEqual(preview.image.getpixel((600, 600)), (220, 10, 20))


if __name__ == "__main__":
    unittest.main()
