"""Проверка датасета и разделение по группам, без зависимости от PyTorch."""
from __future__ import annotations

import csv
import hashlib
import random
import re
from collections import Counter
from pathlib import Path

from PIL import Image

CLASSES = ("blue", "defect", "green_white", "pink")
EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def source_id(path: Path) -> str | None:
    match = re.search(r"(?:^|_)src(\d+)(?:_|$)", path.stem)
    return f"src{int(match.group(1))}" if match else None


def scan_classes(root: Path) -> list[tuple[Path, str]]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Нет папки: {root}")
    actual = {p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")}
    if actual != set(CLASSES):
        raise ValueError(
            f"В {root} нужны ровно папки {CLASSES}.\n"
            f"Найдены: {sorted(actual)}. Папку green можно переименовать в green_white."
        )
    result = []
    for label in CLASSES:
        files = sorted(p for p in (root / label).rglob("*") if p.suffix.lower() in EXTENSIONS)
        if not files:
            raise ValueError(f"Пустой класс: {root / label}")
        for path in files:
            try:
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    image.convert("RGB").load()
            except Exception as exc:
                raise ValueError(f"Повреждённое изображение {path}: {exc}") from exc
            result.append((path, label))
    return result


def pixel_hash(path: Path) -> str:
    with Image.open(path) as image:
        image = image.convert("RGB")
        return hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()


def check_overlap(splits: dict[str, list[tuple[Path, str]]]) -> None:
    """Ищет точные совпадения пикселей и одинаковые srcNN между выборками."""
    hashes: dict[str, tuple[str, Path]] = {}
    sources: dict[str, str] = {}
    for split, items in splits.items():
        for path, _ in items:
            digest = pixel_hash(path)
            if digest in hashes and hashes[digest][0] != split:
                raise ValueError(f"Утечка данных: одинаковые изображения {path} и {hashes[digest][1]}")
            hashes[digest] = split, path
            src = source_id(path)
            if src and src in sources and sources[src] != split:
                raise ValueError(f"Утечка данных: {src} есть в {sources[src]} и {split}")
            if src:
                sources[src] = split


def validate_ready(root: Path) -> dict:
    splits = {s: scan_classes(root / s) for s in ("train", "val")}
    if (root / "test").is_dir():
        splits["test"] = scan_classes(root / "test")
    check_overlap(splits)
    return {s: dict(Counter(label for _, label in rows)) for s, rows in splits.items()}


def load_groups(
    items: list[tuple[Path, str]],
    root: Path,
    manifest: Path | None,
    group_column: str,
    independent: bool,
) -> dict[Path, str]:
    """Manifest: image_path,class,scene_group (или другая --group-column)."""
    if manifest:
        with manifest.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"image_path", "class", group_column}
            if not required <= set(reader.fieldnames or []):
                raise ValueError(f"В {manifest} нужны столбцы {sorted(required)}")
            rows = list(reader)
        by_path = {}
        for row in rows:
            key = (manifest.parent / row["image_path"].replace("\\", "/")).resolve()
            if key in by_path:
                raise ValueError(f"Повтор image_path в manifest: {key}")
            by_path[key] = row
        groups = {}
        for path, label in items:
            row = by_path.get(path.resolve())
            if row is None or row["class"] != label or not row[group_column].strip():
                raise ValueError(f"Нет корректной строки manifest для {path}")
            groups[path] = row[group_column].strip()
        return groups
    if independent:
        return {p: p.relative_to(root).as_posix() for p, _ in items}
    groups = {p: source_id(p) for p, _ in items}
    if any(group is None for group in groups.values()):
        raise ValueError(
            "Не удалось определить группы исходников. Укажите --manifest с image_path,class,scene_group "
            "или --independent-images, только если все фотографии действительно независимы."
        )
    return groups


def grouped_split(items, groups, fraction=0.2, seed=42):
    if not 0 < fraction < 1:
        raise ValueError("--val-fraction должен быть между 0 и 1")
    ids = sorted(set(groups.values()))
    if len(ids) < 2:
        raise ValueError("Для разделения нужны минимум две независимые группы.")
    for label in CLASSES:
        if len({groups[p] for p, cls in items if cls == label}) < 2:
            raise ValueError(f"Класс {label}: меньше двух групп. Добавьте независимую валидацию.")
    count = min(len(ids) - 1, max(1, round(len(ids) * fraction)))
    rng = random.Random(seed)
    totals = Counter(label for _, label in items)
    best = None
    # Общие группы для всех классов: одна сцена не может уйти в разные выборки.
    for _ in range(1000):
        selected = set(rng.sample(ids, count))
        val_counts = Counter(label for p, label in items if groups[p] in selected)
        if any(val_counts[c] == 0 or val_counts[c] == totals[c] for c in CLASSES):
            continue
        score = sum(abs(val_counts[c] / totals[c] - fraction) for c in CLASSES)
        if best is None or score < best[0]:
            best = score, selected
    if best is None:
        raise ValueError("Не удалось разделить группы с наличием всех классов. Нужна отдельная val.")
    val_ids = best[1]
    return {
        "train": [(p, c) for p, c in items if groups[p] not in val_ids],
        "val": [(p, c) for p, c in items if groups[p] in val_ids],
    }
