#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Дообучение YOLO11n-cls: blue, pink, green_white, defect."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from multiprocessing import freeze_support
from pathlib import Path
import platform

from dataset_utils import validate_ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("dataset_ready"))
    parser.add_argument("--model", default="yolo11n-cls.pt", help="Предобученные веса или локальный .pt")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--imgsz", type=int, default=256)
    parser.add_argument("--device", default="auto", help="auto, cpu, 0 (первая NVIDIA), mps")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--project", type=Path, default=Path("runs_jars"))
    parser.add_argument("--name", default=datetime.now().strftime("jars_%Y%m%d_%H%M%S"))
    parser.add_argument("--resume", type=Path, help="last.pt прерванного обучения")
    parser.add_argument("--check-only", action="store_true", help="Только проверить данные, без обучения")
    args = parser.parse_args()
    if args.epochs < 1 or args.batch < 1 or args.imgsz < 32 or args.imgsz % 32:
        raise ValueError("epochs и batch > 0; imgsz >= 32 и кратен 32.")
    data = args.data.resolve()
    counts = validate_ready(data)
    print("Количество изображений:", json.dumps(counts, ensure_ascii=False))
    if args.check_only:
        print("Проверка пройдена. Это не проверка правильности разметки.")
        return

    import torch
    import ultralytics
    from ultralytics import YOLO
    from jar_model import JarTrainer, JarValidator

    device = ("0" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
    if device.isdigit() and not torch.cuda.is_available():
        raise ValueError("CUDA недоступна. Используйте --device cpu или установите PyTorch с CUDA.")
    print(f"Устройство: {device}; PyTorch: {torch.__version__}; Ultralytics: {ultralytics.__version__}")
    if args.resume:
        if not args.resume.is_file():
            raise ValueError(f"Не найден checkpoint: {args.resume}")
        model = YOLO(str(args.resume.resolve()))
        if model.task != "classify":
            raise ValueError("Нужен checkpoint классификатора.")
        saved_data = model.ckpt.get("train_args", {}).get("data")
        if saved_data and Path(saved_data).resolve() != data:
            raise ValueError(f"Для resume используйте исходный --data: {saved_data}")
        model.train(resume=True, trainer=JarTrainer, device=device, workers=args.workers)
    else:
        model = YOLO(args.model)
        if model.task != "classify":
            raise ValueError("Нужна модель классификации, например yolo11n-cls.pt.")
        model.train(
            trainer=JarTrainer, data=str(data),
            epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
            device=device, workers=args.workers, patience=args.patience,
            project=str(args.project.resolve()), name=args.name, exist_ok=False,
            optimizer="AdamW", lr0=0.001, weight_decay=0.0005,
            seed=args.seed, deterministic=True, pretrained=True,
            cache=False, plots=True, save=True, val=True,
            # JarDataset дополнительно заменяет стандартные аугментации целиком.
            auto_augment=None, erasing=0.0, hsv_h=0.0, hsv_s=0.0,
            hsv_v=0.0, fliplr=0.0, flipud=0.0,
            amp=device not in {"cpu", "mps"},
        )
    run_dir = Path(model.trainer.save_dir)
    best = run_dir / "weights" / "best.pt"
    if not best.is_file():
        raise RuntimeError(f"Обучение не создало {best}. Смотрите журнал ошибок.")
    trained = YOLO(str(best))
    # При resume берём размер из фактических аргументов продолженного запуска.
    size = int(model.trainer.args.imgsz)
    evaluation = {}
    for split in ("val", "test"):
        if split == "test" and not (data / split).is_dir():
            continue
        metrics = trained.val(
            validator=JarValidator, data=str(data), split=split,
            imgsz=size, batch=args.batch, device=device, workers=args.workers,
            project=str(run_dir), name=f"evaluation_{split}", plots=True,
        )
        matrix = metrics.confusion_matrix.matrix
        per_class = {}
        for i, label in trained.names.items():
            correct = float(matrix[i, i])
            predicted = float(matrix[i, :].sum())
            actual = float(matrix[:, i].sum())
            precision = correct / predicted if predicted else 0.0
            recall = correct / actual if actual else 0.0
            per_class[label] = {
                "precision": precision, "recall": recall,
                "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
                "support": int(actual),
            }
        evaluation[split] = {
            "top1": float(metrics.top1), "per_class": per_class,
            "confusion_matrix_predicted_rows_true_columns": matrix.tolist(),
        }
    metadata = {
        "model": str(best.resolve()), "task": "classify", "imgsz": size,
        "names": trained.names, "counts": counts, "metrics": evaluation,
        "preprocessing": "jar_model.FullImageSquare + ToTensor, no normalization",
        "python": platform.python_version(), "torch": torch.__version__,
        "ultralytics": ultralytics.__version__,
        "scope": "Одна банка на изображении/ROI. Без локализации, руки и управления роботом.",
    }
    (run_dir / "training_summary.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nГОТОВО. Лучшие веса: {best.resolve()}")
    print(f"Метрики и параметры: {run_dir / 'training_summary.json'}")
    print("Качество на реальной камере нужно проверить отдельно на новых банках.")


if __name__ == "__main__":
    freeze_support()
    try:
        main()
    except KeyboardInterrupt:
        print("\nОбучение прервано. Если last.pt уже создан, можно использовать --resume.")
        raise SystemExit(130)
    except (ValueError, OSError) as exc:
        raise SystemExit(f"ОШИБКА: {exc}")
