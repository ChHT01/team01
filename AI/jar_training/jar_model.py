"""Общие преобразования для обучения, валидации и распознавания."""
from PIL import Image, ImageOps
import torchvision.transforms as T

from ultralytics.data.dataset import ClassificationDataset
from ultralytics.models.yolo.classify import ClassificationTrainer, ClassificationValidator


class FullImageSquare:
    """Вписывает ВСЁ изображение в квадрат: без обрезки и изменения пропорций."""

    def __init__(self, size):
        self.size = int(size)

    def __call__(self, image):
        return ImageOps.pad(
            ImageOps.exif_transpose(image).convert("RGB"),
            (self.size, self.size),
            method=Image.Resampling.BILINEAR, color=(114, 114, 114),
        )


class JarDataset(ClassificationDataset):
    def __init__(self, root, args, augment=False, prefix=""):
        super().__init__(root, args, augment, prefix)
        # Исходный набор уже аугментирован. Не меняем оттенок и не вырезаем дефекты.
        self.torch_transforms = T.Compose([FullImageSquare(args.imgsz), T.ToTensor()])


class JarTrainer(ClassificationTrainer):
    def build_dataset(self, img_path, mode="train", batch=None):
        return JarDataset(img_path, self.args, augment=mode == "train", prefix=mode)


class JarValidator(ClassificationValidator):
    def build_dataset(self, img_path):
        return JarDataset(img_path, self.args, augment=False, prefix=self.args.split)
