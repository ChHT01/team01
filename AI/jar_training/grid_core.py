"""Геометрия, контроль присутствия объекта и фильтрация результатов сетки 3x3."""
from __future__ import annotations

from collections import deque
from pathlib import Path
import json
import time

import cv2
import numpy as np

LABELS = {
    "blue": "BLUE", "pink": "PINK", "green_white": "GREEN",
    "defect": "DEFECT", "empty": "EMPTY", "unknown": "UNKNOWN",
    "unstable": "WAIT", "uncertain": "CHECK OCCUPANCY",
    "edge": "MOVE TO CENTER", "motion": "MOTION",
    "person": "PERSON SIGNAL", "no_frame": "NO FRAME",
    "no_background": "SET EMPTY GRID: B", "scene_change": "SCENE CHANGED",
    "error": "MODEL ERROR", "uncalibrated": "CALIBRATE: C",
}
COLORS = {
    "blue": (255, 120, 30), "pink": (190, 90, 255),
    "green_white": (60, 210, 70), "defect": (20, 20, 255),
    "empty": (150, 150, 150),
}
MODEL_CLASSES = {"blue", "pink", "green_white", "defect"}


def validate_corners(points, width, height):
    corners = np.asarray(points, dtype=np.float32)
    if corners.shape != (4, 2) or not np.isfinite(corners).all():
        raise ValueError("Нужны 4 корректные точки: верх-лево, верх-право, низ-право, низ-лево.")
    if np.any(corners[:, 0] < 0) or np.any(corners[:, 0] >= width):
        raise ValueError("Углы должны находиться внутри изображения.")
    if np.any(corners[:, 1] < 0) or np.any(corners[:, 1] >= height):
        raise ValueError("Углы должны находиться внутри изображения.")
    contour = corners.reshape(-1, 1, 2)
    if not cv2.isContourConvex(contour):
        raise ValueError("Четырёхугольник пересекается или невыпуклый. Повторите выбор.")
    area = cv2.contourArea(contour, oriented=True)
    if area < max(400, width * height * 0.01):
        raise ValueError("Слишком маленькая сетка или неверный порядок углов.")
    if min(np.linalg.norm(corners[i] - corners[(i + 1) % 4]) for i in range(4)) < 20:
        raise ValueError("Углы слишком близко друг к другу.")
    return corners


class GridGeometry:
    def __init__(self, corners, frame_shape, size=900, margin=0.04):
        if size < 192 or size % 3:
            raise ValueError("Размер сетки должен быть >=192 и делиться на 3.")
        if not 0 <= margin < 0.25:
            raise ValueError("margin должен быть в пределах [0, 0.25).")
        self.height, self.width = frame_shape[:2]
        self.corners = validate_corners(corners, self.width, self.height)
        self.size = int(size)
        self.margin = margin
        target = np.float32([[0, 0], [size - 1, 0], [size - 1, size - 1], [0, size - 1]])
        self.matrix = cv2.getPerspectiveTransform(self.corners, target)
        self.inverse = np.linalg.inv(self.matrix)

    def warp(self, frame):
        if frame.shape[:2] != (self.height, self.width):
            raise ValueError("Разрешение камеры изменилось. Нужна новая калибровка (C).")
        return cv2.warpPerspective(frame, self.matrix, (self.size, self.size))

    def rect(self, index, inner=True):
        if not 0 <= index < 9:
            raise ValueError("Индекс ячейки должен быть 0..8")
        row, col = divmod(index, 3)
        step = self.size // 3
        padding = round(step * self.margin) if inner else 0
        return col * step + padding, row * step + padding, (col + 1) * step - padding, (row + 1) * step - padding

    def crop(self, warped, index):
        x1, y1, x2, y2 = self.rect(index)
        return warped[y1:y2, x1:x2].copy()

    def polygon(self, index):
        x1, y1, x2, y2 = self.rect(index, inner=False)
        xy = np.float32([[[x1, y1], [min(x2, self.size - 1), y1],
                          [min(x2, self.size - 1), min(y2, self.size - 1)],
                          [x1, min(y2, self.size - 1)]]])
        return cv2.perspectiveTransform(xy, self.inverse)[0].round().astype(np.int32)


def background_arrays(crop, reference, threshold):
    """Сравнение с пустой ячейкой; НЕ модель детекции и не контроль безопасности."""
    small = cv2.GaussianBlur(cv2.resize(crop, (96, 96)), (5, 5), 0)
    base = cv2.GaussianBlur(cv2.resize(reference, (96, 96)), (5, 5), 0)
    difference = np.max(cv2.absdiff(small, base), axis=2)
    mask = np.uint8(difference > threshold) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return mask


def inspect_occupancy(crop, reference, diff_threshold=25, empty_ratio=0.015, occupied_ratio=0.08):
    mask = background_arrays(crop, reference, diff_threshold)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    cleaned = np.zeros_like(mask)
    for idx in range(1, n):
        if stats[idx, cv2.CC_STAT_AREA] >= 16:
            cleaned[labels == idx] = 255
    ratio = float(np.count_nonzero(cleaned) / cleaned.size)
    if ratio <= empty_ratio:
        return "empty", ratio, None
    if ratio < occupied_ratio:
        return "uncertain", ratio, None
    ys, xs = np.where(cleaned != 0)
    x1, x2, y1, y2 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    # Не классифицируем объект, обрезанный границей внутренней области ячейки.
    if x1 <= 1 or y1 <= 1 or x2 >= 95 or y2 >= 95:
        return "edge", ratio, None
    width, height = crop.shape[1], crop.shape[0]
    pad = max(3, int(max(x2 - x1, y2 - y1) * 0.10))
    bbox = (
        max(0, int((x1 - pad) * width / 96)),
        max(0, int((y1 - pad) * height / 96)),
        min(width, int(np.ceil((x2 + pad) * width / 96))),
        min(height, int(np.ceil((y2 + pad) * height / 96))),
    )
    return "occupied", ratio, bbox


def motion_ratio(current, previous, threshold=20):
    if previous is None or previous.shape != current.shape:
        return 1.0
    a = cv2.GaussianBlur(cv2.resize(current, (180, 180)), (5, 5), 0)
    b = cv2.GaussianBlur(cv2.resize(previous, (180, 180)), (5, 5), 0)
    return float(np.mean(np.max(cv2.absdiff(a, b), axis=2) > threshold))


class StableResults:
    def __init__(self, samples=3):
        if samples < 1:
            raise ValueError("samples должен быть >=1")
        self.samples = samples
        self.history = [deque(maxlen=samples) for _ in range(9)]

    def clear(self):
        for history in self.history:
            history.clear()

    def push(self, cells):
        output = []
        for index, cell in enumerate(cells):
            cell = dict(cell)
            label = cell["label"]
            if label not in MODEL_CLASSES | {"empty"}:
                self.history[index].clear()
            else:
                self.history[index].append(label)
                if len(self.history[index]) < self.samples or len(set(self.history[index])) != 1:
                    cell["candidate"] = label
                    cell["label"] = "unstable"
            cell["stable"] = cell["label"] in MODEL_CLASSES | {"empty"}
            output.append(cell)
        return output


def uniform_cells(label):
    return [{"cell": i + 1, "row": i // 3 + 1, "column": i % 3 + 1,
             "label": label, "confidence": None, "stable": False} for i in range(9)]


class GridAnalyzer:
    def __init__(self, geometry, classifier, background=None, stable_samples=3,
                 diff_threshold=25, empty_ratio=0.015, occupied_ratio=0.08,
                 motion_limit=0.02):
        if not 0 <= empty_ratio < occupied_ratio <= 1:
            raise ValueError("Нужно 0 <= empty_ratio < occupied_ratio <= 1")
        self.geometry, self.classifier = geometry, classifier
        self.background = background
        self.stabilizer = StableResults(stable_samples)
        self.previous = None
        self.diff_threshold = diff_threshold
        self.empty_ratio, self.occupied_ratio = empty_ratio, occupied_ratio
        self.motion_limit = motion_limit

    def invalidate(self, label):
        self.stabilizer.clear()
        self.previous = None
        return uniform_cells(label)

    def analyze(self, warped, person=False):
        if person:
            self.previous = warped.copy()
            self.stabilizer.clear()
            return uniform_cells("person")
        if self.background is None:
            return self.invalidate("no_background")
        changed = motion_ratio(warped, self.previous)
        self.previous = warped.copy()
        if changed > self.motion_limit:
            self.stabilizer.clear()
            return uniform_cells("motion")
        cells, inputs, indices = [], [], []
        for index in range(9):
            crop = self.geometry.crop(warped, index)
            ref = self.geometry.crop(self.background, index)
            state, ratio, bbox = inspect_occupancy(
                crop, ref, self.diff_threshold, self.empty_ratio, self.occupied_ratio
            )
            cell = uniform_cells(state)[index]
            cell["changed_fraction"] = ratio
            cell["object_bbox_in_cell_roi"] = list(bbox) if bbox else None
            cells.append(cell)
            if state == "occupied":
                x1, y1, x2, y2 = bbox
                inputs.append(crop[y1:y2, x1:x2].copy())
                indices.append(index)
        # Массовое изменение почти всего поля чаще означает свет/сдвиг камеры.
        if sum(c["changed_fraction"] > 0.70 for c in cells) >= 7:
            self.stabilizer.clear()
            return uniform_cells("scene_change")
        if inputs:
            answers = self.classifier.predict_batch(inputs)
            if len(answers) != len(inputs):
                raise RuntimeError("Модель вернула неверное число результатов.")
            for index, answer in zip(indices, answers):
                cells[index].update(answer)
        return self.stabilizer.push(cells)


def save_calibration(path, geometry, background, source_tag):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("wb") as stream:
        np.savez_compressed(
            stream, corners=geometry.corners,
            shape=np.array([geometry.height, geometry.width]),
            size=np.array(geometry.size), source=np.array(source_tag),
            background=background if background is not None else np.empty((0,), dtype=np.uint8),
        )
    temp.replace(path)


def load_calibration(path, frame_shape, size, margin, source_tag):
    with np.load(path, allow_pickle=False) as data:
        if str(data["source"].item()) != source_tag:
            raise ValueError("Калибровка сохранена для другого источника.")
        if tuple(data["shape"].tolist()) != tuple(frame_shape[:2]):
            raise ValueError("Изменилось разрешение кадра. Перекалибруйте сетку.")
        if int(data["size"]) != size:
            raise ValueError("Изменился --grid-size. Перекалибруйте сетку.")
        geometry = GridGeometry(data["corners"], frame_shape, size, margin)
        background = data["background"].copy()
        if background.size == 0:
            background = None
        elif background.shape != (size, size, 3) or background.dtype != np.uint8:
            raise ValueError("Некорректный фон в файле калибровки.")
    return geometry, background


def text(image, message, origin, color=(255, 255, 255), scale=0.58):
    cv2.putText(image, message, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(image, message, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def render_grid(warped, geometry, cells):
    image = warped.copy()
    for i, cell in enumerate(cells):
        x1, y1, x2, y2 = geometry.rect(i, inner=False)
        color = COLORS.get(cell["label"], (0, 190, 255))
        cv2.rectangle(image, (x1, y1), (x2 - 1, y2 - 1), color, 2)
        ix1, iy1, ix2, iy2 = geometry.rect(i)
        cv2.rectangle(image, (ix1, iy1), (ix2 - 1, iy2 - 1), (100, 100, 100), 1)
        bbox = cell.get("object_bbox_in_cell_roi")
        if bbox:
            a, b, c, d = bbox
            cv2.rectangle(image, (ix1 + a, iy1 + b), (ix1 + c, iy1 + d), color, 1)
        label = LABELS.get(cell["label"], cell["label"])
        text(image, f"{i + 1}: {label}", (x1 + 8, y1 + 25), color, 0.53)
        if cell.get("confidence") is not None:
            text(image, f"score {cell['confidence']:.2f}", (x1 + 8, y1 + 49), color, 0.49)
    return image


def save_snapshot(root, frame, warped, geometry, cells, source_tag, person_state):
    from datetime import datetime
    directory = Path(root) / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    directory.mkdir(parents=True, exist_ok=False)
    images = {"frame.png": frame, "grid_clean.png": warped,
              "grid_result.png": render_grid(warped, geometry, cells)}
    for index in range(9):
        images[f"cell_{index + 1:02d}.png"] = geometry.crop(warped, index)
    for filename, image in images.items():
        if not cv2.imwrite(str(directory / filename), image):
            raise OSError(f"Не удалось сохранить {directory / filename}")
    report = {
        "saved_at_unix": time.time(), "source": source_tag, "person_signal": person_state,
        "corners": geometry.corners.tolist(), "cells": cells,
        "note": "Снимки соответствуют сохранённому анализу. Предсказания не являются ручной разметкой.",
    }
    (directory / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return directory
