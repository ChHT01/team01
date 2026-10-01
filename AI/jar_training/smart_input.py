"""Адаптер SmartCamera по методам из исходного пользовательского скрипта."""
from __future__ import annotations

import logging
import time

import cv2
import numpy as np
from PIL import Image

LOG = logging.getLogger("camera")


def normalize_frame(result):
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], (bool, np.bool_)):
        ok, result = result
        if not ok:
            return None
    if result is None:
        return None
    if isinstance(result, Image.Image):
        return cv2.cvtColor(np.asarray(result.convert("RGB")), cv2.COLOR_RGB2BGR)
    if isinstance(result, (bytes, bytearray, memoryview)):
        result = cv2.imdecode(np.frombuffer(result, np.uint8), cv2.IMREAD_COLOR)
        if result is None:
            return None
    if not isinstance(result, np.ndarray) or result.dtype != np.uint8 or result.size == 0:
        return None
    if result.ndim == 1:
        result = cv2.imdecode(result, cv2.IMREAD_COLOR)
        if result is None:
            return None
    if result.ndim == 2:
        result = cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)
    elif result.ndim == 3 and result.shape[2] == 4:
        result = cv2.cvtColor(result, cv2.COLOR_BGRA2BGR)
    if result.ndim != 3 or result.shape[2] != 3:
        return None
    return np.ascontiguousarray(result).copy()


class SmartInput:
    def __init__(self, ip, frame_method=None):
        # Библиотека управления роботом не требуется для --image / --video.
        from motion.core import SmartCamera
        self.camera = SmartCamera(ip)
        self.selected = None
        self.last_warning = 0.0
        self.candidates = [("method", frame_method)] if frame_method else (
            [("method", m) for m in ("get_frame", "read", "getImage", "get_image", "capture")] +
            [("attr", m) for m in ("frame", "image", "last_frame", "current_frame")]
        )
        connect = getattr(self.camera, "connect", None)
        if callable(connect):
            try:
                result = connect()
                LOG.info("connect() -> %r", result)
            except Exception:
                # Некоторые SDK подключаются в конструкторе. Проверка кадров решит, работает ли доступ.
                LOG.warning("connect() завершился ошибкой; проверяю получение кадра.", exc_info=True)

    def read(self):
        errors = []
        candidates = [self.selected] if self.selected else self.candidates
        for kind, name in candidates:
            try:
                value = getattr(self.camera, name)
                result = value() if kind == "method" else value
                frame = normalize_frame(result)
                if frame is not None:
                    if self.selected is None:
                        LOG.info("Кадры: SmartCamera.%s (%s)", name, kind)
                        self.selected = (kind, name)
                    return frame
                errors.append(f"{name}: нет корректного uint8 кадра")
            except AttributeError:
                errors.append(f"{name}: отсутствует")
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
        if time.monotonic() - self.last_warning > 5:
            LOG.warning("Не получен кадр. %s", "; ".join(errors))
            self.last_warning = time.monotonic()
        return None

    def person(self):
        try:
            method = getattr(self.camera, "getPerson", None)
            if not callable(method):
                return -1
            value = method()
            if value is None:
                return -1
            return 1 if int(value) > 0 else 0
        except Exception:
            return -1

    def close(self):
        for name in ("disconnect", "release", "close"):
            method = getattr(self.camera, name, None)
            if callable(method):
                try:
                    method()
                    return
                except Exception:
                    LOG.warning("%s() завершился ошибкой.", name, exc_info=True)


class VideoInput:
    def __init__(self, source):
        value = int(source) if str(source).isdigit() else str(source)
        self.camera = cv2.VideoCapture(value)
        if not self.camera.isOpened():
            self.camera.release()
            raise ValueError(f"Не удалось открыть видео: {source}")

    def read(self):
        return normalize_frame(self.camera.read())

    def person(self):
        return -1

    def close(self):
        self.camera.release()


class ImageInput:
    def __init__(self, path):
        with Image.open(path) as image:
            self.frame = normalize_frame(image)

    def read(self):
        return self.frame.copy()

    def person(self):
        return -1

    def close(self):
        pass
