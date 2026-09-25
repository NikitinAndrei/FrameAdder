"""Подготовка актуального предпросмотра в одном потоке, без обращения к Tkinter."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .models import FrameSettings, PreviewData

PreviewBuilder = Callable[[Path, FrameSettings], PreviewData]


@dataclass(frozen=True, slots=True)
class PreviewEvent:
    preview: PreviewData | None = None
    error: Exception | None = None


class PreviewWorker:
    """Считает одно превью; из ожидающих запросов оставляет только последний."""

    def __init__(self, build_preview: PreviewBuilder) -> None:
        self._build_preview = build_preview
        self._condition = threading.Condition()
        self._generation = 0
        self._pending: tuple[int, Path, FrameSettings] | None = None
        self._result: PreviewEvent | None = None
        self._closed = False
        self._thread = threading.Thread(
            target=self._run, name="preview-worker", daemon=True
        )
        self._thread.start()

    @staticmethod
    def _discard(event: PreviewEvent | None) -> None:
        if event is not None and event.preview is not None:
            event.preview.image.close()

    def invalidate(self) -> None:
        """Отменить результат сразу при вводе, ещё до задержки обновления UI."""

        with self._condition:
            self._generation += 1
            self._pending = None
            self._discard(self._result)
            self._result = None

    def submit(self, source: Path, settings: FrameSettings) -> None:
        with self._condition:
            if self._closed:
                return
            self._generation += 1
            self._pending = (self._generation, source, settings)
            self._discard(self._result)
            self._result = None
            self._condition.notify()

    def poll(self) -> PreviewEvent | None:
        """Забрать готовый результат; вызывается из потока интерфейса."""

        with self._condition:
            result = self._result
            self._result = None
            return result

    def close(self) -> None:
        """Не ждать декодирования изображения при закрытии окна."""

        with self._condition:
            self._closed = True
            self._pending = None
            self._discard(self._result)
            self._result = None
            self._condition.notify()

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._closed or self._pending is not None
                )
                if self._closed:
                    return
                request = self._pending
                self._pending = None
            if request is None:
                continue
            generation, source, settings = request
            try:
                result = PreviewEvent(preview=self._build_preview(source, settings))
            except Exception as error:
                result = PreviewEvent(error=error)
            with self._condition:
                if self._closed or generation != self._generation:
                    self._discard(result)
                else:
                    self._result = result
