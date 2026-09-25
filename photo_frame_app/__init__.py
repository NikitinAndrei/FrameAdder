"""Приложение для пакетного добавления цветной рамки к изображениям."""

from .image_processor import ImageProcessor
from .models import FrameSettings, ProcessingJob, ProcessingResult

__all__ = ["FrameSettings", "ImageProcessor", "ProcessingJob", "ProcessingResult"]
