from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path

from PIL import Image

from photo_frame_app.models import FrameSettings, PreviewData
from photo_frame_app.preview_worker import PreviewWorker


class PreviewWorkerTests(unittest.TestCase):
    def test_publishes_only_the_latest_preview_from_a_background_thread(self) -> None:
        first_started = threading.Event()
        allow_first_to_finish = threading.Event()
        build_threads: list[threading.Thread] = []

        def build_preview(source: Path, _settings: FrameSettings) -> PreviewData:
            build_threads.append(threading.current_thread())
            if source.name == "first.png":
                first_started.set()
                allow_first_to_finish.wait(timeout=1)
            return PreviewData(
                image=Image.new("RGB", (1, 1)),
                source_file=source,
                source_size=(1, 1),
                output_size=(1, 1),
                total_files=1,
            )

        worker = PreviewWorker(build_preview)
        self.addCleanup(worker.close)
        worker.submit(Path("first.png"), FrameSettings())
        self.assertTrue(first_started.wait(timeout=1))
        worker.submit(Path("second.png"), FrameSettings())
        allow_first_to_finish.set()

        deadline = time.monotonic() + 1
        event = None
        while event is None and time.monotonic() < deadline:
            event = worker.poll()
            if event is None:
                time.sleep(0.01)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertIsNone(event.error)
        assert event.preview is not None
        self.addCleanup(event.preview.image.close)
        self.assertEqual(event.preview.source_file, Path("second.png"))
        self.assertTrue(build_threads)
        self.assertIsNot(build_threads[0], threading.current_thread())


if __name__ == "__main__":
    unittest.main()
