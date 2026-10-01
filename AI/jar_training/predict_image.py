#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Распознавание одной банки; можно импортировать JarClassifier в код камеры."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from ultralytics import YOLO

from jar_model import FullImageSquare

RUSSIAN = {
    "blue": "синяя банка", "pink": "розовая банка",
    "green_white": "зелёная / зелёно-белая банка", "defect": "банка с дефектом",
    "unknown": "неуверенный результат",
}


class JarClassifier:
    def __init__(self, weights, device="cpu", threshold=0.75, imgsz=None):
        if not 0 <= threshold <= 1:
            raise ValueError("threshold должен быть от 0 до 1")
        if not Path(weights).is_file():
            raise ValueError(f"Нет файла весов: {weights}")
        self.model = YOLO(str(weights))
        if self.model.task != "classify":
            raise ValueError("Нужны веса классификации, не детекции.")
        saved_size = (self.model.ckpt or {}).get("train_args", {}).get("imgsz", 256)
        self.imgsz = int(imgsz or saved_size)
        self.transform = FullImageSquare(self.imgsz)
        self.device = device
        self.threshold = threshold

    def predict_pil(self, image):
        square = self.transform(image)
        # Ultralytics принимает ndarray как BGR. Вход уже квадратный, обрезки нет.
        bgr = np.ascontiguousarray(np.asarray(square)[:, :, ::-1])
        result = self.model.predict(
            source=bgr, imgsz=self.imgsz, device=self.device, verbose=False
        )[0]
        scores = result.probs.data.cpu().tolist()
        best = int(result.probs.top1)
        label = result.names[best]
        confidence = float(scores[best])
        accepted = label if confidence >= self.threshold else "unknown"
        return {
            "label": accepted, "label_ru": RUSSIAN.get(accepted, accepted),
            "top_class": label, "confidence": confidence,
            "scores": {result.names[i]: float(p) for i, p in enumerate(scores)},
        }

    def predict_bgr(self, roi):
        """На вход: OpenCV BGR uint8, вырезка ОДНОЙ банки, без текста поверх."""
        if not isinstance(roi, np.ndarray) or roi.ndim != 3 or roi.shape[2] != 3 or roi.size == 0:
            raise ValueError("Нужен непустой BGR-кадр H x W x 3")
        if roi.dtype != np.uint8:
            raise ValueError("Нужен кадр uint8")
        return self.predict_pil(Image.fromarray(roi[:, :, ::-1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path, help="Фото одной банки")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--threshold", type=float, default=0.75)
    args = parser.parse_args()
    classifier = JarClassifier(args.weights, device=args.device, threshold=args.threshold)
    with Image.open(args.image) as image:
        print(json.dumps(classifier.predict_pil(image), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
