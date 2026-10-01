"""Проверка без камеры: uv run python -m unittest -v test_grid"""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from grid_core import (
    GridAnalyzer, GridGeometry, StableResults, inspect_occupancy,
    load_calibration, motion_ratio, render_grid, save_calibration, save_snapshot,
    uniform_cells, validate_corners,
)
from smart_input import normalize_frame, SmartInput


class FakeClassifier:
    def __init__(self):
        self.calls = []

    def predict_batch(self, crops):
        self.calls.append(crops)
        return [{"label": "blue", "confidence": .9, "top_class": "blue",
                 "scores": {"blue": .9, "pink": .03, "green_white": .03, "defect": .04}}
                for _ in crops]


def geometry():
    return GridGeometry([[0, 0], [599, 0], [599, 599], [0, 599]], (600, 600, 3), size=600)


class GridTests(unittest.TestCase):
    def test_numbering_and_crops(self):
        grid = geometry()
        image = np.zeros((600, 600, 3), np.uint8)
        for i in range(9):
            x1, y1, x2, y2 = grid.rect(i, inner=False)
            image[y1:y2, x1:x2] = 20 * (i + 1)
        warped = grid.warp(image)
        for i in range(9):
            self.assertTrue(np.all(grid.crop(warped, i) == 20 * (i + 1)))
        self.assertEqual(grid.rect(8, inner=False), (400, 400, 600, 600))

    def test_perspective(self):
        corners = [[100, 50], [700, 70], [600, 550], [150, 500]]
        grid = GridGeometry(corners, (600, 800, 3), size=600)
        mapped = cv2.perspectiveTransform(np.float32([corners]), grid.matrix)[0]
        np.testing.assert_allclose(mapped, [[0, 0], [599, 0], [599, 599], [0, 599]], atol=.001)

    def test_bad_corners(self):
        for corners in (
            [[0, 0], [599, 599], [599, 0], [0, 599]],
            [[0, 0], [0, 599], [599, 599], [599, 0]],
            [[-1, 0], [599, 0], [599, 599], [0, 599]],
            [[0, 0], [1, 0], [1, 1], [0, 1]],
        ):
            with self.assertRaises(ValueError):
                validate_corners(corners, 600, 600)

    def test_outside_grid_ignored(self):
        grid = GridGeometry([[100, 100], [699, 100], [699, 699], [100, 699]],
                            (800, 800, 3), size=600)
        first = np.full((800, 800, 3), 130, np.uint8)
        second = first.copy()
        second[:70] = (255, 0, 0)
        second[:, 740:] = (0, 0, 255)
        np.testing.assert_array_equal(grid.warp(first), grid.warp(second))

    def test_empty(self):
        reference = np.full((200, 200, 3), 140, np.uint8)
        label, ratio, bbox = inspect_occupancy(reference, reference)
        self.assertEqual(label, "empty")
        self.assertEqual(ratio, 0)
        self.assertIsNone(bbox)

    def test_object_bbox(self):
        reference = np.full((200, 200, 3), 140, np.uint8)
        current = reference.copy()
        cv2.circle(current, (100, 100), 48, (255, 20, 20), -1)
        state, ratio, bbox = inspect_occupancy(current, reference)
        self.assertEqual(state, "occupied")
        self.assertGreater(ratio, .08)
        self.assertLess(bbox[0], 53)
        self.assertGreater(bbox[2], 147)

    def test_edge_abstention(self):
        reference = np.full((200, 200, 3), 140, np.uint8)
        current = reference.copy()
        cv2.rectangle(current, (0, 0), (100, 110), (255, 0, 0), -1)
        self.assertEqual(inspect_occupancy(current, reference)[0], "edge")

    def test_stability_and_clear(self):
        stable = StableResults(3)
        cells = uniform_cells("blue")
        self.assertEqual(stable.push(cells)[0]["label"], "unstable")
        self.assertEqual(stable.push(cells)[0]["label"], "unstable")
        self.assertEqual(stable.push(cells)[0]["label"], "blue")
        self.assertEqual(stable.push(uniform_cells("unknown"))[0]["label"], "unknown")
        self.assertEqual(stable.push(cells)[0]["label"], "unstable")
        stable.clear()
        self.assertEqual(len(stable.history[0]), 0)

    def test_no_classification_empty_person_and_missing_background(self):
        grid, fake = geometry(), FakeClassifier()
        blank = np.full((600, 600, 3), 140, np.uint8)
        analyzer = GridAnalyzer(grid, fake, blank, stable_samples=1)
        analyzer.analyze(blank)
        self.assertEqual(analyzer.analyze(blank)[0]["label"], "empty")
        self.assertFalse(fake.calls)
        self.assertEqual(analyzer.analyze(blank, person=True)[0]["label"], "person")
        self.assertFalse(fake.calls)
        analyzer.background = None
        self.assertEqual(analyzer.analyze(blank)[0]["label"], "no_background")
        self.assertFalse(fake.calls)

    def test_nine_occupied_batch(self):
        grid, fake = geometry(), FakeClassifier()
        blank = np.full((600, 600, 3), 140, np.uint8)
        jars = blank.copy()
        for row in range(3):
            for col in range(3):
                cv2.circle(jars, (col * 200 + 100, row * 200 + 100), 50, (255, 20, 20), -1)
        analyzer = GridAnalyzer(grid, fake, blank, stable_samples=1)
        self.assertEqual(analyzer.analyze(jars)[0]["label"], "motion")
        result = analyzer.analyze(jars)
        self.assertEqual([x["label"] for x in result], ["blue"] * 9)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(len(fake.calls[0]), 9)
        self.assertEqual([x["cell"] for x in result], list(range(1, 10)))
        self.assertEqual(analyzer.invalidate("no_frame")[0]["label"], "no_frame")
        self.assertEqual(analyzer.analyze(jars)[0]["label"], "motion")

    def test_global_lighting_change(self):
        grid, fake = geometry(), FakeClassifier()
        blank = np.full((600, 600, 3), 140, np.uint8)
        current = np.full_like(blank, 210)
        analyzer = GridAnalyzer(grid, fake, blank, stable_samples=1)
        analyzer.analyze(current)
        self.assertEqual(analyzer.analyze(current)[0]["label"], "scene_change")
        self.assertFalse(fake.calls)

    def test_calibration_and_snapshot(self):
        grid = geometry()
        background = np.full((600, 600, 3), 140, np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calibration.npz"
            save_calibration(path, grid, background, "test")
            loaded, ref = load_calibration(path, background.shape, 600, .04, "test")
            np.testing.assert_array_equal(ref, background)
            np.testing.assert_allclose(loaded.corners, grid.corners)
            with self.assertRaises(ValueError):
                load_calibration(path, background.shape, 600, .04, "wrong_camera")
            with self.assertRaises(ValueError):
                load_calibration(path, (700, 600, 3), 600, .04, "test")
            save_calibration(path, grid, None, "test")
            self.assertIsNone(load_calibration(path, background.shape, 600, .04, "test")[1])
            dest = save_snapshot(tmp, background, background, grid,
                                 uniform_cells("empty"), "test", -1)
            self.assertTrue((dest / "results.json").is_file())
            self.assertEqual(len(list(dest.glob("cell_*.png"))), 9)
            result = render_grid(background, grid, uniform_cells("empty"))
            self.assertEqual(result.shape, background.shape)
            self.assertTrue(np.all(background == 140))  # подписи не меняют исходник

    def test_frame_formats(self):
        frame = np.zeros((20, 30, 3), np.uint8)
        frame[:] = (200, 10, 50)
        np.testing.assert_array_equal(normalize_frame((True, frame)), frame)
        self.assertIsNone(normalize_frame((False, frame)))
        self.assertIsNone(normalize_frame(None))
        self.assertIsNone(normalize_frame("unsupported path"))
        self.assertIsNone(normalize_frame(frame.astype(np.float32)))
        self.assertEqual(normalize_frame(np.zeros((20, 30), np.uint8)).shape, frame.shape)
        success, encoded = cv2.imencode(".png", frame)
        self.assertTrue(success)
        np.testing.assert_array_equal(normalize_frame(encoded.tobytes()), frame)
        pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        np.testing.assert_array_equal(normalize_frame(pil), frame)
        converted = normalize_frame(frame)
        converted[:] = 0
        self.assertTrue(np.any(frame))

    def test_smart_reader_selection_with_fake_sdk(self):
        class FakeCamera:
            def read(self):
                return True, np.full((20, 20, 3), 15, np.uint8)
            def getPerson(self):
                return 1
        camera = SmartInput.__new__(SmartInput)
        camera.camera = FakeCamera()
        camera.selected = None
        camera.last_warning = 0
        camera.candidates = [("method", "get_frame"), ("method", "read")]
        self.assertEqual(camera.read().shape, (20, 20, 3))
        self.assertEqual(camera.selected, ("method", "read"))
        self.assertEqual(camera.person(), 1)

    def test_motion(self):
        black = np.zeros((600, 600, 3), np.uint8)
        self.assertEqual(motion_ratio(black, black), 0)
        self.assertEqual(motion_ratio(black, None), 1)
        self.assertGreater(motion_ratio(black + 255, black), .99)

    def test_ui_flow_with_mocked_windows(self):
        """Полный цикл Enter/B/S/Q без дисплея и без камеры."""
        import camera_grid_3x3 as app
        class Frames:
            def __init__(self):
                self.count = 0
                self.closed = False
            def read(self):
                self.count += 1
                result = np.full((600, 600, 3), 140, np.uint8)
                if self.count >= 19:
                    cv2.circle(result, (300, 300), 50, (255, 20, 20), -1)
                return result
            def person(self):
                return -1
            def close(self):
                self.closed = True
        source, classifier = Frames(), FakeClassifier()
        events = {"callback": None, "count": 0}
        def mouse_callback(window, callback):
            events["callback"] = callback
        def wait_key(delay):
            events["count"] += 1
            count = events["count"]
            if count == 1:
                for x, y in ((0, 0), (599, 0), (599, 599), (0, 599)):
                    events["callback"](cv2.EVENT_LBUTTONDOWN, x, y, 0, None)
                return 13
            if count == 17:
                return ord("b")
            if count == 26:
                return ord("s")
            return ord("q") if count >= 28 else -1
        with tempfile.TemporaryDirectory() as tmp:
            calibration = Path(tmp) / "calibration.npz"
            snapshots = Path(tmp) / "snapshots"
            argv = ["camera_grid_3x3.py", "--weights", "fake.pt", "--image", "fake.png",
                    "--grid-size", "600", "--interval", "0.000001", "--stable", "1",
                    "--calibration", str(calibration), "--snapshots", str(snapshots)]
            with patch("sys.argv", argv), \
                 patch.object(app, "BatchClassifier", return_value=classifier), \
                 patch.object(app, "ImageInput", return_value=source), \
                 patch.object(app.cv2, "namedWindow"), \
                 patch.object(app.cv2, "imshow"), \
                 patch.object(app.cv2, "setMouseCallback", side_effect=mouse_callback), \
                 patch.object(app.cv2, "waitKey", side_effect=wait_key), \
                 patch.object(app.cv2, "getWindowProperty", return_value=1), \
                 patch.object(app.cv2, "destroyAllWindows"), \
                 patch.object(app.time, "sleep"):
                app.main()
            self.assertTrue(calibration.is_file())
            self.assertTrue(source.closed)
            reports = list(snapshots.glob("*/results.json"))
            self.assertEqual(len(reports), 1)
            report = json.loads(reports[0].read_text())
            self.assertEqual(report["cells"][4]["label"], "blue")
            self.assertEqual(report["cells"][0]["label"], "empty")


if __name__ == "__main__":
    unittest.main()
