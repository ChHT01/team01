#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Подготавливает train/val, не перемещая и не изменяя исходные фотографии."""
from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

from dataset_utils import (
    CLASSES, check_overlap, grouped_split, load_groups, scan_classes, validate_ready,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, type=Path, help="Папка с четырьмя классами")
    parser.add_argument("--out", type=Path, default=Path("dataset_ready"))
    parser.add_argument("--manifest", type=Path, help="CSV; пути image_path относительно CSV")
    parser.add_argument("--group-column", default="scene_group")
    parser.add_argument("--val-raw", type=Path, help="Предпочтительно: новые независимые снимки по классам")
    parser.add_argument("--independent-images", action="store_true",
                        help="Разрешить разделение по файлам, если НЕТ вариантов исходников")
    parser.add_argument("--val-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    root, output = args.raw.resolve(), args.out.resolve()
    if output.exists():
        raise ValueError(f"Папка уже существует: {output}. Укажите новый --out; перезаписи нет.")
    if output == root or root in output.parents:
        raise ValueError("--out должен находиться вне --raw.")
    items = scan_classes(root)
    manifest = args.manifest.resolve() if args.manifest else None
    if manifest is None and (root.parent / "manifest.csv").is_file():
        manifest = root.parent / "manifest.csv"
    if args.val_raw:
        val_root = args.val_raw.resolve()
        if output == val_root or val_root in output.parents:
            raise ValueError("--out должен находиться вне --val-raw.")
        splits = {"train": items, "val": scan_classes(val_root)}
        groups = {}
        mode = "external_validation_user_declared"
    else:
        groups = load_groups(items, root, manifest, args.group_column, args.independent_images)
        splits = grouped_split(items, groups, args.val_fraction, args.seed)
        mode = f"manifest:{args.group_column}" if manifest else (
            "independent_images_user_declared" if args.independent_images else "source_filename"
        )
    check_overlap(splits)
    output.mkdir(parents=True)
    rows = []
    for split, entries in splits.items():
        for label in CLASSES:
            (output / split / label).mkdir(parents=True)
        for index, (source, label) in enumerate(entries):
            # Сохраняем srcNN для повторной проверки перед обучением.
            destination = output / split / label / f"{index:06d}_{source.name}"
            shutil.copy2(source, destination)
            rows.append({
                "image_path": destination.relative_to(output).as_posix(),
                "class": label, "split": split,
                "group": groups.get(source, "external"), "original": str(source),
            })
    with (output / "split_manifest.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    counts = validate_ready(output)
    report = {"mode": mode, "seed": args.seed, "counts": counts,
              "train_groups": sorted({groups[p] for p, _ in splits["train"]}) if groups else [],
              "val_groups": sorted({groups[p] for p, _ in splits["val"]}) if groups else [],
              "warning": "Разные исходники/сцены могут изображать одни и те же физические банки. "
                         "Для оценки качества нужны новые банки и съёмочные сессии."}
    (output / "preparation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nГотово: {output}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        raise SystemExit(f"ОШИБКА: {exc}")
