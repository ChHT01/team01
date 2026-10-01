#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SmartCamera: распознавание 9 ячеек, без команд движения роботу."""
from __future__ import annotations

import argparse
from collections import deque
import logging
from pathlib import Path
import time

import cv2
import numpy as np
from PIL import Image

from grid_core import (
    COLORS, MODEL_CLASSES, GridAnalyzer, GridGeometry, load_calibration,
    motion_ratio, render_grid, save_calibration, save_snapshot, text, uniform_cells,
)
from smart_input import ImageInput, SmartInput, VideoInput

LOG = logging.getLogger("grid")
CAMERA_WINDOW = "Robot camera - calibration"
GRID_WINDOW = "Jars 3x3 - no robot control"


class BatchClassifier:
    def __init__(self, weights, device="cpu", threshold=0.75):
        if not Path(weights).is_file():
            raise ValueError(f"Не найден файл весов: {weights}")
        from ultralytics import YOLO
        from jar_model import FullImageSquare
        self.model = YOLO(str(weights))
        if self.model.task != "classify":
            raise ValueError("Нужны веса классификации best.pt, а не детекции.")
        if set(self.model.names.values()) != MODEL_CLASSES:
            raise ValueError(f"Ожидаются {sorted(MODEL_CLASSES)}; в модели {self.model.names}")
        self.size = int((self.model.ckpt or {}).get("train_args", {}).get("imgsz", 256))
        self.transform = FullImageSquare(self.size)
        self.device, self.threshold = device, threshold

    def predict_batch(self, crops):
        if not crops:
            return []
        inputs = []
        for crop in crops:
            rgb = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
            square = self.transform(rgb)
            inputs.append(np.ascontiguousarray(np.asarray(square)[:, :, ::-1]))
        results = self.model.predict(
            source=inputs, imgsz=self.size, device=self.device,
            batch=len(inputs), verbose=False,
        )
        answers = []
        for result in results:
            scores = result.probs.data.cpu().tolist()
            best = int(result.probs.top1)
            top_class, confidence = result.names[best], float(scores[best])
            answers.append({
                "label": top_class if confidence >= self.threshold else "unknown",
                "top_class": top_class, "confidence": confidence,
                "scores": {result.names[i]: float(value) for i, value in enumerate(scores)},
            })
        return answers


class Selection:
    def __init__(self):
        self.active = False
        self.points = []
        self.frozen = None
        self.scale = 1.0

    def start(self, frame):
        self.active = True
        self.points = []
        self.frozen = frame.copy()

    def callback(self, event, x, y, flags, parameter):
        if self.active and event == cv2.EVENT_LBUTTONDOWN and len(self.points) < 4:
            height, width = self.frozen.shape[:2]
            self.points.append([min(width - 1, max(0, x / self.scale)),
                                min(height - 1, max(0, y / self.scale))])


def show_camera(image, selection):
    scale = min(1.0, 1280 / image.shape[1], 800 / image.shape[0])
    selection.scale = scale
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale)
    cv2.imshow(CAMERA_WINDOW, image)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", required=True, type=Path)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--ip", default="192.168.2.110")
    source.add_argument("--video", help="Путь видео, RTSP URL или номер USB-камеры")
    source.add_argument("--image", type=Path, help="Фото для проверки без SmartCamera")
    parser.add_argument("--frame-method", help="Известное имя метода SmartCamera, например getImage")
    parser.add_argument("--calibration", type=Path, default=Path("grid_3x3_calibration.npz"))
    parser.add_argument("--empty-image", type=Path, help="Фото ПУСТОГО поля с той же камеры и позы")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--confidence", type=float, default=0.75)
    parser.add_argument("--grid-size", type=int, default=900)
    parser.add_argument("--margin", type=float, default=0.04)
    parser.add_argument("--interval", type=float, default=0.4)
    parser.add_argument("--fps", type=float, default=15)
    parser.add_argument("--stable", type=int, default=3)
    parser.add_argument("--diff", type=int, default=25)
    parser.add_argument("--empty-ratio", type=float, default=0.015)
    parser.add_argument("--occupied-ratio", type=float, default=0.08)
    parser.add_argument("--motion-ratio", type=float, default=0.02)
    parser.add_argument("--frame-timeout", type=float, default=15)
    parser.add_argument("--snapshots", type=Path, default=Path("grid_snapshots"))
    args = parser.parse_args()
    if not 0 <= args.confidence <= 1:
        parser.error("--confidence должен быть от 0 до 1")
    if args.interval <= 0 or args.fps <= 0 or args.frame_timeout <= 0:
        parser.error("--interval, --fps, --frame-timeout должны быть >0")
    if args.stable < 1 or args.grid_size < 192 or args.grid_size % 3:
        parser.error("--stable >=1; --grid-size >=192, кратен 3")
    if not 0 <= args.margin < .25 or not 0 < args.motion_ratio <= 1 or not 1 <= args.diff <= 254:
        parser.error("Некорректные --margin / --motion-ratio / --diff")
    if not 0 <= args.empty_ratio < args.occupied_ratio <= 1:
        parser.error("Нужно 0 <= empty-ratio < occupied-ratio <=1")
    return args


def main():
    args = parse_args()
    classifier = BatchClassifier(args.weights, args.device, args.confidence)
    if args.image:
        source, tag = ImageInput(args.image), "image"
    elif args.video is not None:
        source, tag = VideoInput(args.video), f"video:{args.video}"
    else:
        source, tag = SmartInput(args.ip, args.frame_method), f"smart:{args.ip}"
    geometry = analyzer = None
    cells = uniform_cells("uncalibrated")
    selection = Selection()
    calibration_checked = False
    last_frame_time, last_analysis, last_person_check = time.monotonic(), 0., 0.
    person_state = -1
    recent_empty = deque(maxlen=15)
    snapshot = None
    last_signature = None
    note = ""

    def create_analyzer(geom, background=None):
        return GridAnalyzer(geom, classifier, background, args.stable, args.diff,
                            args.empty_ratio, args.occupied_ratio, args.motion_ratio)

    try:
        cv2.namedWindow(CAMERA_WINDOW, cv2.WINDOW_AUTOSIZE)
        cv2.namedWindow(GRID_WINDOW, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(CAMERA_WINDOW, selection.callback)
        LOG.info("C: выбрать углы; Enter: подтвердить; B: запомнить ПУСТОЕ поле; S: снимок; Q: выход.")
        LOG.info("Порядок: верхний левый -> верхний правый -> нижний правый -> нижний левый.")
        LOG.warning("Только индикация. getPerson и нейросеть НЕ являются системой безопасности.")
        while True:
            started = time.monotonic()
            frame = source.read()
            now = time.monotonic()
            if frame is None:
                snapshot = None
                cells = analyzer.invalidate("no_frame") if analyzer else uniform_cells("no_frame")
                recent_empty.clear()
                canvas = np.zeros((450, 800, 3), np.uint8)
                text(canvas, "NO FRAME - predictions cleared", (25, 80))
                cv2.imshow(CAMERA_WINDOW, canvas)
                cv2.imshow(GRID_WINDOW, canvas)
                if (cv2.waitKey(30) & 255) in (ord("q"), 27):
                    break
                if now - last_frame_time > args.frame_timeout:
                    raise RuntimeError("Камера не отдаёт кадры. Смотрите диагностику методов в терминале.")
                continue
            last_frame_time = now
            if now - last_person_check >= .5:
                person_state = source.person()
                last_person_check = now
            if not calibration_checked:
                calibration_checked = True
                if args.calibration.is_file():
                    try:
                        geometry, bg = load_calibration(
                            args.calibration, frame.shape, args.grid_size, args.margin, tag
                        )
                        analyzer = create_analyzer(geometry, bg)
                        LOG.info("Калибровка загружена: %s. Проверяйте совпадение сетки с реальным полем.",
                                 args.calibration)
                    except (ValueError, OSError, KeyError) as exc:
                        LOG.warning("Калибровка не принята: %s", exc)
                if geometry is None:
                    selection.start(frame)
            if geometry and frame.shape[:2] != (geometry.height, geometry.width):
                LOG.warning("Разрешение изменилось. Калибровка и фон сброшены.")
                geometry = analyzer = None
                snapshot = None
                recent_empty.clear()
                selection.start(frame)
            elif selection.active and selection.frozen.shape[:2] != frame.shape[:2]:
                selection.start(frame)

            warped = geometry.warp(frame) if geometry else None
            if selection.active:
                cells = uniform_cells("uncalibrated")
                snapshot = None
                recent_empty.clear()
                preview = selection.frozen.copy()
                for i, point in enumerate(selection.points):
                    xy = tuple(np.int32(point))
                    cv2.circle(preview, xy, 6, (0, 255, 255), -1)
                    text(preview, str(i + 1), (xy[0] + 8, xy[1] - 8))
                if len(selection.points) > 1:
                    cv2.polylines(preview, [np.int32(selection.points)], len(selection.points) == 4,
                                  (0, 255, 255), 2)
                text(preview, "Click: TL -> TR -> BR -> BL | Enter: accept | R: reset", (15, 28))
                grid_view = np.zeros((600, 600, 3), np.uint8)
                text(grid_view, "Calibrate in the camera window", (20, 70))
            else:
                preview = frame.copy()
                if geometry:
                    if person_state != 1:
                        recent_empty.append(warped.copy())
                    else:
                        recent_empty.clear()
                        cells = analyzer.invalidate("person")
                        snapshot = None
                    if now - last_analysis >= args.interval:
                        cells = analyzer.analyze(warped, person_state == 1)
                        last_analysis = time.monotonic()
                        snapshot = (frame.copy(), warped.copy(), [dict(c) for c in cells], person_state)
                        signature = tuple(c["label"] for c in cells)
                        if signature != last_signature:
                            LOG.info("Ячейки 1..9: %s", ", ".join(signature))
                            last_signature = signature
                    for i in range(9):
                        polygon = geometry.polygon(i)
                        color = COLORS.get(cells[i]["label"], (0, 190, 255))
                        cv2.polylines(preview, [polygon], True, color, 2)
                        center = np.mean(polygon, axis=0).astype(int)
                        text(preview, str(i + 1), tuple(center), color, .8)
                    grid_view = render_grid(warped, geometry, cells)
                else:
                    grid_view = np.zeros((600, 600, 3), np.uint8)
                    text(grid_view, "Press C to calibrate", (20, 70))
                person_text = "PERSON=1" if person_state == 1 else (
                    "PERSON=0" if person_state == 0 else "PERSON UNKNOWN - no safety guarantee"
                )
                text(preview, person_text, (15, 28), (0, 180, 255))
                text(preview, "C: corners | B: EMPTY background | S: snapshot | Q: exit", (15, 55))
                if analyzer and analyzer.background is None:
                    text(preview, "REMOVE ALL JARS AND HANDS, hold still, then press B", (15, 82), (0, 180, 255))
                if note:
                    text(preview, note, (15, 109), (0, 180, 255), .48)
                if last_analysis:
                    text(preview, f"Last analysis: {time.monotonic() - last_analysis:.1f}s ago",
                         (15, 136), (200, 200, 200), .48)
            show_camera(preview, selection)
            if grid_view.shape[0] > 750:
                grid_view = cv2.resize(grid_view, (750, 750))
            cv2.imshow(GRID_WINDOW, grid_view)
            key = cv2.waitKey(1) & 255
            if key in (ord("q"), 27):
                break
            if key == ord("c"):
                selection.start(frame)
                snapshot = None
                if analyzer:
                    analyzer.invalidate("uncalibrated")
                note = ""
            elif key == ord("r") and selection.active:
                selection.points.clear()
            elif key in (10, 13) and selection.active:
                try:
                    geometry = GridGeometry(selection.points, frame.shape, args.grid_size, args.margin)
                    bg = None
                    if args.empty_image:
                        bg_frame = ImageInput(args.empty_image).read()
                        bg = geometry.warp(bg_frame)
                        LOG.warning("Фон взят из --empty-image. Проверьте отсутствие банок и совпадение камеры.")
                    analyzer = create_analyzer(geometry, bg)
                    save_calibration(args.calibration, geometry, bg, tag)
                    selection.active = False
                    recent_empty.clear()
                    last_analysis = 0
                    note = "Corners saved. Empty grid -> B" if bg is None else "Empty reference loaded."
                    LOG.info("Углы сохранены. Ячейки идут по строкам: 1 2 3 / 4 5 6 / 7 8 9.")
                except (ValueError, OSError) as exc:
                    LOG.error("%s", exc)
                    note = "Invalid corners or background. See terminal."
            elif key == ord("b") and not selection.active and analyzer:
                if person_state == 1:
                    LOG.warning("Фон не записан: getPerson()=1. Уберите руку/человека.")
                    note = "Background NOT saved: PERSON SIGNAL"
                elif len(recent_empty) < 15 or any(
                    motion_ratio(x, recent_empty[0]) > .01 for x in recent_empty
                ):
                    LOG.warning("Фон не записан: подождите неподвижную сцену не менее 15 кадров.")
                    note = "Hold EMPTY grid still, then press B again"
                else:
                    background = np.median(np.stack(recent_empty), axis=0).astype(np.uint8)
                    analyzer = create_analyzer(geometry, background)
                    save_calibration(args.calibration, geometry, background, tag)
                    cells = uniform_cells("unstable")
                    snapshot = None
                    last_analysis = 0
                    note = "Empty background saved. Place one jar per cell."
                    LOG.warning("Пустой фон сохранён ПО ВАШЕМУ ПОДТВЕРЖДЕНИЮ (B). "
                                "Программа сама не доказывает отсутствие объектов.")
            elif key == ord("s") and snapshot and geometry and not selection.active:
                raw, rectified, saved_cells, saved_person = snapshot
                directory = save_snapshot(args.snapshots, raw, rectified, geometry,
                                          saved_cells, tag, saved_person)
                LOG.info("Сохранён последний проанализированный кадр: %s", directory)
                note = "Snapshot saved (last analyzed frame)"
            try:
                if cv2.getWindowProperty(CAMERA_WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
            except cv2.error:
                break
            time.sleep(max(0., 1 / args.fps - (time.monotonic() - started)))
    finally:
        source.close()
        cv2.destroyAllWindows()
        LOG.info("Видео закрыто. Команд движения роботу не отправлялось.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    try:
        main()
    except KeyboardInterrupt:
        print("\nВыход.")
    except Exception:
        LOG.exception("Работа остановлена. Сохранённые веса не изменены.")
        raise SystemExit(1)
