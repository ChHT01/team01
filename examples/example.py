#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль 2. Сортировка банок с выбором ряда под цвет.
Хорошие → синий, розовый, зеленый.
Плохие  → только номер ячейки (цвет "red" в логах).
"""

import time
import os
import sys
from math import pi, radians, degrees
from motion.core import RobotControl, Waypoint, LedLamp, SmartCamera
from motion.robot_control import Modes, States, InterpreterStates

# ----------------------------------------------------------------------
# 1. КОНФИГУРАЦИЯ
# ----------------------------------------------------------------------
ROBOT_IP  = "192.168.2.100"
LAMP_IP   = "192.168.2.101"
CAMERA_IP = "192.168.2.110"

DELAY = 0.5

# ----------------------------------------------------------------------
# 2. ДОМАШНЯЯ ПОЗА
# ----------------------------------------------------------------------
HOME_JOINT = [
    radians(0),
    radians(15.28),
    radians(27.65),
    radians(47.08),
    radians(90),
    radians(0),
]

HOME_CART = [
    0.489, -0.135, 0.569,
    radians(-180), radians(0), radians(90),
]

# ----------------------------------------------------------------------
# 3. ЯЩИКИ
# ----------------------------------------------------------------------
BOX_GOOD = {
    "1": [0.6, 0.35, 0.03, pi/2, 0.0, pi],
    "2": [0.6, 0.46, 0.03, pi/2, 0.0, pi],
    "3": [0.6, 0.57, 0.03, pi/2, 0.0, pi],
    "4": [0.5, 0.35, 0.03, pi/2, 0.0, pi],
    "5": [0.5, 0.46, 0.03, pi/2, 0.0, pi],
    "6": [0.5, 0.57, 0.03, pi/2, 0.0, pi],
    "7": [0.6, 0.35, 0.03, pi/2, 0.0, pi],
    "8": [0.6, 0.46, 0.03, pi/2, 0.0, pi],
    "9": [0.6, 0.57, 0.03, pi/2, 0.0, pi],
}

BOX_BAD = {
    "1": [0.59, -0.34,  0.03, pi/2, 0.0, pi],
    "2": [0.59, -0.455, 0.03, pi/2, 0.0, pi],
    "3": [0.59, -0.57,  0.03, pi/2, 0.0, pi],
    "4": [0.5,  -0.34,  0.03, pi/2, 0.0, pi],
    "5": [0.5,  -0.455, 0.03, pi/2, 0.0, pi],
    "6": [0.5,  -0.57,  0.03, pi/2, 0.0, pi],
    "7": [0.41, -0.34,  0.03, pi/2, 0.0, pi],
    "8": [0.41, -0.455, 0.03, pi/2, 0.0, pi],
    "9": [0.41, -0.57,  0.03, pi/2, 0.0, pi],
}

# ----------------------------------------------------------------------
# 4. ТОЧКИ ЗАХВАТА
# ----------------------------------------------------------------------
PICK_POINTS = {
    "1": [0.59,  0.110, 0.03, pi/2, 0.0, pi],
    "2": [0.59,  0.005, 0.03, pi/2, 0.0, pi],
    "3": [0.59,  -0.1,  0.03, pi/2, 0.0, pi],
    "4": [0.5,   0.011, 0.03, pi/2, 0.0, pi],
    "5": [0.5,   0.005, 0.03, pi/2, 0.0, pi],
    "6": [0.5,   -0.1,  0.03, pi/2, 0.0, pi],
    "7": [0.41,  0.011, 0.03, pi/2, 0.0, pi],
    "8": [0.41,  0.005, 0.03, pi/2, 0.0, pi],
    "9": [0.41, -0.01,  0.03, pi/2, 0.0, pi],
}

# ----------------------------------------------------------------------
# 5. РЯДЫ
# ----------------------------------------------------------------------
ROWS = {
    "1": ["1", "2", "3"],
    "2": ["4", "5", "6"],
    "3": ["7", "8", "9"],
}

COLOR_TO_ROW = {}
COLOR_TO_CELLS = {}

# ----------------------------------------------------------------------
# 6. ВВОД РЯДОВ
# ----------------------------------------------------------------------
def input_rows() -> dict:
    print("\n=== Настройка рядов под цвета ===")
    for row_num, cells in ROWS.items():
        print(f"  Ряд {row_num} → ячейки {', '.join(cells)}")
    print("Формат: ЦВЕТ1 РЯД1, ЦВЕТ2 РЯД2, ЦВЕТ3 РЯД3")
    print("Пример: синий 1, розовый 2, зеленый 3")
    print("Пустая строка — по умолчанию (синий→1, розовый→2, зеленый→3)\n")

    mapping = {}

    if not sys.stdin.isatty():
        mapping = {"синий": "1", "розовый": "2", "зеленый": "3"}
        print(f"[WARN] stdin недоступен, использую: {mapping}")
        return _fill_color_cells(mapping)

    raw = input("Ряды (цвет ряд, ...): ").strip()
    if not raw:
        mapping = {"синий": "1", "розовый": "2", "зеленый": "3"}
        print(f"[INFO] По умолчанию: {mapping}")
        return _fill_color_cells(mapping)

    parts = [p.strip() for p in raw.split(",")]
    used_rows = set()

    for part in parts:
        tokens = part.replace(",", " ").split()
        if len(tokens) != 2:
            print(f"[!] Неверный формат: '{part}'")
            continue
        color, row = tokens[0].lower(), tokens[1]
        if row not in ROWS:
            print(f"[!] Ряда '{row}' нет.")
            continue
        if row in used_rows:
            print(f"[!] Ряд {row} уже занят.")
            continue
        mapping[color] = row
        used_rows.add(row)

    free_rows = [r for r in ROWS if r not in used_rows]
    for color in ["синий", "розовый", "зеленый"]:
        if color not in mapping and free_rows:
            mapping[color] = free_rows.pop(0)
            print(f"[INFO] '{color}' → ряд {mapping[color]}")

    print(f"[INFO] Итог: {mapping}")
    return _fill_color_cells(mapping)

def _fill_color_cells(mapping: dict) -> dict:
    global COLOR_TO_ROW, COLOR_TO_CELLS
    COLOR_TO_ROW = dict(mapping)
    COLOR_TO_CELLS = {color: ROWS[row] for color, row in mapping.items()}

    # Синий остаётся, красный → розовый
    aliases = {
        "blue":    "синий",   "siniy":   "синий",
        "pink":    "розовый", "rose":    "розовый",
        "rozovyi": "розовый", "rozovyy": "розовый",
        "красный": "розовый",
        "red":     "розовый",
        "krasnyi": "розовый",
        "green":   "зеленый", "zelenyi": "зеленый",
    }
    for alias, ru in aliases.items():
        if ru in COLOR_TO_CELLS:
            COLOR_TO_CELLS[alias] = COLOR_TO_CELLS[ru]
    return mapping

# ----------------------------------------------------------------------
# 7. ВВОД ХОРОШИХ
# ----------------------------------------------------------------------
def input_good(box: dict) -> list:
    print("\n=== Ввод 'ХОРОШИЕ' банок ===")
    print("Введите: ЦВЕТ [номер_ячейки]")
    print(f"Ряды: {COLOR_TO_ROW}")
    print("Пустая строка — завершить.\n")

    items = []
    idx = 1
    used_cells = set()

    if not sys.stdin.isatty():
        preset = [("синий", None), ("розовый", None), ("зеленый", None)]
        print(f"[WARN] stdin недоступен, использую: {preset}")
        for color, _ in preset:
            chosen = _pick_cell_for_color(color, used_cells)
            if chosen:
                used_cells.add(chosen)
                items.append((chosen, color, box[chosen]))
        return items

    while True:
        try:
            raw = input(f"ХОРОШИЕ #{idx} (цвет [ячейка]): ").strip()
        except EOFError:
            break
        if not raw:
            break

        parts = raw.replace(",", " ").split()

        if len(parts) == 1:
            color = parts[0].lower()
            cell = _pick_cell_for_color(color, used_cells)
            if cell is None:
                print(f"[!] Нет цвета '{color}' или нет свободных ячеек.")
                continue
            used_cells.add(cell)
            items.append((cell, color, box[cell]))
            print(f"  → цвет {color}: ячейка {cell}")
            idx += 1

        elif len(parts) == 2:
            color = parts[0].lower()
            cell = parts[1]
            if cell not in box:
                print(f"[!] Ячейки '{cell}' нет.")
                continue
            if cell in used_cells:
                print(f"[!] Ячейка {cell} занята.")
                continue
            used_cells.add(cell)
            items.append((cell, color, box[cell]))
            idx += 1

        else:
            print("[!] Формат: ЦВЕТ или ЦВЕТ ЯЧЕЙКА")

    return items

def _pick_cell_for_color(color: str, used: set):
    cells = COLOR_TO_CELLS.get(color)
    if not cells:
        return None
    for c in cells:
        if c not in used:
            return c
    return None

# ----------------------------------------------------------------------
# 8. ВВОД ПЛОХИХ
# ----------------------------------------------------------------------
def input_bad(box: dict) -> list:
    print("\n=== Ввод 'ПЛОХИЕ' банок ===")
    print(f"Доступные ячейки: {', '.join(sorted(box.keys()))}")
    print("Введите: НОМЕР_ЯЧЕЙКИ")
    print("Пустая строка — завершить.\n")

    items = []
    idx = 1
    used_cells = set()

    if not sys.stdin.isatty():
        preset = ["1", "2"]
        print(f"[WARN] stdin недоступен, использую: {preset}")
        for cell in preset:
            if cell in box and cell not in used_cells:
                used_cells.add(cell)
                items.append((cell, "red", box[cell]))
        return items

    while True:
        try:
            raw = input(f"ПЛОХИЕ #{idx} (ячейка): ").strip()
        except EOFError:
            break
        if not raw:
            break

        cell = raw.replace(",", " ").split()[0]
        if cell not in box:
            print(f"[!] Ячейки '{cell}' нет.")
            continue
        if cell in used_cells:
            print(f"[!] Ячейка {cell} занята.")
            continue

        used_cells.add(cell)
        items.append((cell, "red", box[cell]))
        idx += 1

    return items

# ----------------------------------------------------------------------
# 9. ПОДКЛЮЧЕНИЕ
# ----------------------------------------------------------------------
def connect_devices():
    robot  = RobotControl(ROBOT_IP)
    lamp   = LedLamp(LAMP_IP)
    camera = SmartCamera(CAMERA_IP)

    lamp.setLamp("0001")
    print("[INFO] Подключение к роботу...")
    if not robot.connect():
        print("[ERROR] Не удалось подключиться")
        return None, None, None

    lamp.setLamp("1000")
    print("[INFO] Подключение успешно")

    if not robot.engage():
        print("[ERROR] Не удалось включить двигатели")
        return None, None, None

    print("[INFO] Robot is Engaged")
    return robot, lamp, camera

# ----------------------------------------------------------------------
# 10. БЕЗОПАСНОСТЬ
# ----------------------------------------------------------------------
class SafetySystem:
    def __init__(self, camera, robot, lamp):
        self.camera = camera
        self.robot = robot
        self.lamp = lamp
        self.log_file = "safety_log.txt"

    def _log(self, message: str):
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {message}\n")

    def check(self) -> bool:
        try:
            if self.camera.getPerson() == 1:
                self._emergency_stop("Человек в рабочей зоне")
                return False

            pos = self.robot.getToolPosition()
            if pos[2] < -0.10 or pos[2] > 1.20:
                self._emergency_stop(f"Выход за пределы зоны: {pos}")
                return False

            if any(t > 80.0 for t in self.robot.getActualTemperature()):
                self._emergency_stop("Перегрев моторов")
                return False
        except Exception as e:
            self._log(f"Ошибка безопасности: {e}")
        return True

    def _emergency_stop(self, reason: str):
        self.robot.stop()
        self.robot.disengage()
        self.lamp.setLamp("0001")
        self._log(f"АВАРИЙНАЯ ОСТАНОВКА: {reason}")
        print(f"[SAFETY] {reason}")

# ----------------------------------------------------------------------
# 11. ПОСТРОЕНИЕ ПРОГРАММЫ
# ----------------------------------------------------------------------
def build_program(robot, good_items, bad_items):
    robot.reset()
    time.sleep(2)

    all_items = [("good", x) for x in good_items] + [("bad", x) for x in bad_items]
    pick_numbers = sorted(PICK_POINTS.keys())

    for i, (kind, (cell, color, place)) in enumerate(all_items):
        if i >= len(pick_numbers):
            print(f"[WARN] Нет точки захвата для #{i+1}")
            continue

        pick_name = pick_numbers[i]
        pick = PICK_POINTS[pick_name]

        print(f"[PROG] {kind.upper()} '{pick_name}' (цвет {color}) → ячейка {cell}")

        robot.addMoveToPointL([Waypoint(pick)])
        robot.addWait(DELAY)
        robot.addToolState(1)
        robot.addWait(DELAY)

        robot.addMoveToPointL([Waypoint([pick[0], pick[1], pick[2] + 0.10,
                                         pick[3], pick[4], pick[5]])])
        robot.addWait(DELAY)

        robot.addMoveToPointL([Waypoint(place)])
        robot.addWait(DELAY)

        robot.addToolState(0)
        robot.addWait(DELAY)

        robot.addMoveToPointL([Waypoint([place[0], place[1], place[2] + 0.10,
                                         place[3], place[4], place[5]])])
        robot.addWait(DELAY)

# ----------------------------------------------------------------------
# 12. ОСНОВНАЯ ЛОГИКА
# ----------------------------------------------------------------------
def main():
    print("=" * 60)
    print(" МОДУЛЬ 2. СОРТИРОВКА БАНОК")
    print("=" * 60)

    input_rows()

    good_items = input_good(BOX_GOOD)
    bad_items  = input_bad(BOX_BAD)

    print("\n=== ИТОГ ===")
    print("Хорошие:")
    for i, (cell, color, pose) in enumerate(good_items, 1):
        print(f"  {i}. ячейка {cell}, цвет {color}")
    print("Плохие:")
    for i, (cell, color, pose) in enumerate(bad_items, 1):
        print(f"  {i}. ячейка {cell}, цвет {color}")

    if not good_items and not bad_items:
        print("[!] Нет банок.")
        return

    input("\nНажмите Enter для подключения к роботу...")

    robot, lamp, camera = connect_devices()
    if robot is None:
        return

    safety = SafetySystem(camera, robot, lamp)

    print(f"\n[DEBUG] До build_program: mode={robot.getRobotMode()}, state={robot.getActualStateOut()}")
    print(f"[DEBUG] HOME_JOINT (град): {[round(degrees(a), 2) for a in HOME_JOINT]}")
    print(f"[DEBUG] Текущие углы (град): {[round(degrees(a), 2) for a in robot.getMotorPositionRadians()]}")
    print(f"[DEBUG] Tool position: {robot.getToolPosition()}")

    print("\n[INFO] Построение программы...")
    build_program(robot, good_items, bad_items)

    time.sleep(1)

    mode = robot.getRobotMode()
    state = robot.getActualStateOut()
    print(f"\n[DEBUG] После build_program: mode={mode}, state={state}")

    if not (mode is Modes.PAUSE_M.value and state is InterpreterStates.PROGRAM_STOP_S.value):
        print(f"[ERROR] Программа не загружена. mode={mode}, state={state}")
        print("  Ожидалось: mode=PAUSE_M(5), state=PROGRAM_STOP_S(2)")

    print("\n[INFO] Перевод в HOME по суставам...")
    lamp.setLamp("0010")

    robot.moveToInitialPose()
    time.sleep(3)

    start_timeout = time.time() + 30
    while robot.getRobotMode() is Modes.MOVE_TO_START_M.value:
        robot.activateMoveToStart()
        time.sleep(0.2)
        print(f"\r[INFO] Ждём старт... mode={robot.getRobotMode()}", end="")
        if time.time() > start_timeout:
            print("\n[ERROR] Тайм-аут ожидания старта")
            lamp.setLamp("0001")
            try:
                robot.disengage()
            except Exception:
                pass
            return

    print("\n[INFO] Робот в стартовой позиции")

    robot.play()
    lamp.setLamp("0100")
    print("[INFO] Программа запущена")

    while not (robot.getActualStateOut() is InterpreterStates.PROGRAM_IS_DONE.value):
        if not safety.check():
            print("[SAFETY] Остановлено")
            break

        os.system('clear')
        print(f"Tool position: {robot.getToolPosition()}")
        print(f"Program state: {robot.getActualStateOut()}")
        print(f"Robot mode:    {robot.getRobotMode()}")
        print(f"Tool state:    {robot.getToolState()}")
        print(f"Temperature:   {robot.getActualTemperature()}")
        print("Ctrl+C — выход")

        time.sleep(0.2)

    print("[INFO] Программа выполнена")

    lamp.setLamp("0001")
    try:
        robot.conveyer_stop()
    except Exception as e:
        print(f"[WARN] conveyer_stop: {e}")
    time.sleep(1)
    try:
        robot.disengage()
    except Exception as e:
        print(f"[WARN] disengage: {e}")
    print("[INFO] Робот отключён")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Прервано пользователем")