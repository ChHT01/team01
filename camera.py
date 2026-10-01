#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Камера робота: вывод видео + getPerson() + автофото при появлении руки.
"""

import os
import time
import cv2
from motion.core import SmartCamera

# ----------------------------------------------------------------------
# КОНФИГУРАЦИЯ
# ----------------------------------------------------------------------
CAMERA_IP     = "192.168.2.110"
WINDOW_TITLE  = "Robot Camera"
FPS           = 15

# Как часто опрашивать getPerson() (в секундах)
PERSON_CHECK_INTERVAL = 0.5

# Папка, куда сохраняются снимки
SAVE_DIR = "person_photos"

# Минимальный интервал между снимками (в секундах),
# чтобы не сохранять по 15 фото в секунду
PHOTO_COOLDOWN = 2.0

# ----------------------------------------------------------------------
# ПОЛУЧЕНИЕ КАДРА
# ----------------------------------------------------------------------
def grab_frame(camera):
    """Пытается получить кадр из SmartCamera. Перебирает методы API."""
    for method_name in ("get_frame", "read", "getImage", "get_image", "capture"):
        if hasattr(camera, method_name):
            try:
                result = getattr(camera, method_name)()
                if result is not None:
                    return result
            except Exception:
                pass

    for attr in ("frame", "image", "last_frame", "current_frame"):
        if hasattr(camera, attr):
            try:
                result = getattr(camera, attr)
                if result is not None:
                    return result
            except Exception:
                pass

    return None

# ----------------------------------------------------------------------
# ПРОВЕРКА ЧЕЛОВЕКА
# ----------------------------------------------------------------------
def check_person(camera) -> int:
    """
    Возвращает:
      1  — человек обнаружен,
      0  — человек не обнаружен,
     -1  — ошибка / метод недоступен.
    """
    if not hasattr(camera, "getPerson"):
        return -1
    try:
        result = camera.getPerson()
        if result is None:
            return -1
        return 1 if int(result) > 0 else 0
    except Exception as e:
        print(f"[CAM] getPerson() ошибка: {e}")
        return -1

# ----------------------------------------------------------------------
# СОХРАНЕНИЕ КАДРА
# ----------------------------------------------------------------------
def save_frame(frame, counter: int) -> str:
    """Сохраняет кадр в SAVE_DIR и возвращает путь к файлу."""
    os.makedirs(SAVE_DIR, exist_ok=True)
    filename = time.strftime("person_%Y-%m-%d_%H-%M-%S_") + f"{counter:04d}.jpg"
    path = os.path.join(SAVE_DIR, filename)
    try:
        cv2.imwrite(path, frame)
        return path
    except Exception as e:
        print(f"[CAM] Не удалось сохранить кадр: {e}")
        return ""

# ----------------------------------------------------------------------
# ОСНОВНАЯ ЛОГИКА
# ----------------------------------------------------------------------
def main():
    print(f"[INFO] Подключение к камере {CAMERA_IP}...")
    camera = SmartCamera(CAMERA_IP)

    if hasattr(camera, "connect"):
        try:
            ok = camera.connect()
            print(f"[INFO] connect() -> {ok}")
        except Exception as e:
            print(f"[WARN] connect(): {e}")

    if hasattr(camera, "getPerson"):
        print("[INFO] Метод getPerson() доступен")
    else:
        print("[WARN] Метод getPerson() НЕ найден")

    os.makedirs(SAVE_DIR, exist_ok=True)
    print(f"[INFO] Снимки сохраняются в: {os.path.abspath(SAVE_DIR)}")
    print("[INFO] Видео запущено. 'q' — выход.")

    interval = 1.0 / FPS
    last_person_check = 0.0
    last_photo_time   = 0.0
    person_state      = -1
    photo_counter     = 0

    try:
        while True:
            t0 = time.time()

            # --- Получить кадр ---
            frame = grab_frame(camera)
            if frame is not None:
                # Индикация в окне
                if person_state == 1:
                    cv2.putText(frame, "PERSON DETECTED", (20, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                                (0, 0, 255), 2)
                elif person_state == 0:
                    cv2.putText(frame, "no person", (20, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                                (0, 255, 0), 2)

                try:
                    cv2.imshow(WINDOW_TITLE, frame)
                except Exception as e:
                    print(f"[CAM] Не удалось показать кадр: {e}")
                    break

            # --- Периодическая проверка getPerson ---
            now = time.time()
            if now - last_person_check >= PERSON_CHECK_INTERVAL:
                last_person_check = now
                person_state = check_person(camera)

                if person_state == 1:
                    print("[CAM] Рука/человек обнаружен!")
                elif person_state == 0:
                    print("[CAM] Никого нет в зоне видимости.")
                else:
                    print("[CAM] getPerson() недоступен или вернул ошибку.")

            # --- Фото, если рука в кадре и кадр получен ---
            if (person_state == 1
                and frame is not None
                and now - last_photo_time >= PHOTO_COOLDOWN):
                path = save_frame(frame, photo_counter)
                if path:
                    photo_counter += 1
                    last_photo_time = now
                    print(f"[CAM] Фото сохранено: {path}")

            # --- Выход по 'q' ---
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("[INFO] Выход по 'q'")
                break

            elapsed = time.time() - t0
            time.sleep(max(0, interval - elapsed))

    except KeyboardInterrupt:
        print("\n[INFO] Прервано пользователем")

    finally:
        cv2.destroyAllWindows()
        if hasattr(camera, "disconnect"):
            try:
                camera.disconnect()
            except Exception:
                pass
        print(f"[INFO] Камера отключена. Всего фото: {photo_counter}")


if __name__ == "__main__":
    main()