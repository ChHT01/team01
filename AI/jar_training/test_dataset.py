"""Запуск: python -m unittest -v test_dataset"""
import csv
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from dataset_utils import (
    CLASSES, check_overlap, grouped_split, load_groups, scan_classes, source_id, validate_ready,
)


class DatasetTests(unittest.TestCase):
    def test_source_id(self):
        self.assertEqual(source_id(Path("000001_blue_0005_src00.jpg")), "src0")
        self.assertIsNone(source_id(Path("blue_0005.jpg")))

    def test_group_isolation(self):
        items, groups = [], {}
        for cls in CLASSES:
            for scene in range(4):
                for variant in range(3):
                    path = Path(cls) / f"s{scene}_v{variant}.jpg"
                    items.append((path, cls))
                    groups[path] = f"scene{scene}"
        result = grouped_split(items, groups)
        train = {groups[p] for p, _ in result["train"]}
        val = {groups[p] for p, _ in result["val"]}
        self.assertFalse(train & val)
        self.assertEqual(len(result["train"]) + len(result["val"]), len(items))
        self.assertEqual({c for _, c in result["val"]}, set(CLASSES))
        self.assertEqual(result, grouped_split(items, groups))

    def test_too_few_groups(self):
        items = [(Path(cls + ".jpg"), cls) for cls in CLASSES]
        with self.assertRaises(ValueError):
            grouped_split(items, {p: "only" for p, _ in items})

    def test_unknown_provenance_requires_confirmation(self):
        items = [(Path("/tmp/raw/blue/x.jpg"), "blue")]
        with self.assertRaises(ValueError):
            load_groups(items, Path("/tmp/raw"), None, "scene_group", False)

    def test_duplicate_pixels_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.png", Path(tmp) / "b.png"
            Image.new("RGB", (16, 16), "blue").save(a)
            Image.new("RGB", (16, 16), "blue").save(b)
            with self.assertRaises(ValueError):
                check_overlap({"train": [(a, "blue")], "val": [(b, "blue")]})

    def test_same_original_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a_src07.png", Path(tmp) / "b_src07.png"
            Image.new("RGB", (16, 16), "blue").save(a)
            Image.new("RGB", (16, 16), "pink").save(b)
            with self.assertRaises(ValueError):
                check_overlap({"train": [(a, "blue")], "val": [(b, "blue")]})

    def test_ready_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for s, split in enumerate(("train", "val", "test")):
                for c, cls in enumerate(CLASSES):
                    directory = root / split / cls
                    directory.mkdir(parents=True)
                    Image.new("RGB", (16, 16), (s * 60, c * 50, 80)).save(directory / "a.png")
            counts = validate_ready(root)
            self.assertEqual(counts["val"]["defect"], 1)

    def test_corrupt_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for cls in CLASSES:
                (root / cls).mkdir()
                Image.new("RGB", (16, 16), "blue").save(root / cls / "a.png")
            (root / "blue" / "a.png").write_bytes(b"not an image")
            with self.assertRaises(ValueError):
                scan_classes(root)

    def test_manifest_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "dataset" / "blue" / "a.jpg"
            manifest = root / "manifest.csv"
            with manifest.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["image_path", "class", "scene_group"])
                writer.writeheader()
                writer.writerow({"image_path": "dataset/blue/a.jpg", "class": "blue", "scene_group": "scene1"})
            groups = load_groups([(path, "blue")], root / "dataset", manifest, "scene_group", False)
            self.assertEqual(groups[path], "scene1")


if __name__ == "__main__":
    unittest.main()
