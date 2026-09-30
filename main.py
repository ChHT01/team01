#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Программа для выполнения Модуля 2.
Управление роботом ARM-IMR-95 через motion-core_API.
"""

import time
import os
from math import pi, radians
from motion.core import RobotControl, Waypoint, LedLamp, SmartCamera
from motion.robot_control import Modes, States, InterpreterStates

# ----------------------------------------------------------------------
# 1. КОНФИГУРАЦИЯ. ЗДЕСЬ ЗАДАЮТСЯ ТОЧКИ КАРТЫ (известные заранее)
# ----------------------------------------------------------------------
ROBOT_IP    = "192.168.2.100"
LAMP_IP     = "192.168.2.101"
CAMERA_IP   = "192.168.2.110"

# Координаты в декартовом пространстве (метры, радианы для ориентации)
# Замените на реальные точки вашей карты!
HOME_POSE   = [0.0, 0.0, pi/2, 0.0, pi/2, 0.0]   # стартовая поза (рад)
PICK_POSES  = [                                   # 3 точки захвата
    [0.30, -0.15, 0.20, pi/2, 0.0, pi],
    [0.30,  0.00, 0.20, pi/2, 0.0, pi],
    [0.30,  0.15, 0.20, pi/2, 0.0, pi],
]
# 3 разгрузочные ячейки, каждая разделена на 4 отсека (итого 12 точек)
PLACE_POSES = [
    # Ячейка 1
    [[0.40, -0.20, 0.25, pi/2, 0.0, pi],
     [0.40, -0.10, 0.25, pi/2, 0.0, pi],
     [0.40,  0.00, 0.25, pi/2, 0.0, pi],
     [0.40,  0.10, 0.25, pi/2, 0.0, pi]],
    # Ячейка 2
    [[0.45, -0.20, 0.25, pi/2, 0.0, pi],
     [0.45, -0.10, 0.25, pi/2, 0.0, pi],
     [0.45,  0.00, 0.25, pi/2, 0.0, pi],
     [0.45,  0.10, 0.25, pi/2, 0.0, pi]],
    # Ячейка 3
    [[0.50, -0.20, 0.25, pi/2, 0.0, pi],
     [0.50, -0.10, 0.25, pi/2, 0.0, pi],
     [0.50,  0.00, 0.25, pi/2, 0.0, pi],
     [0.50,  0.10, 0.25, pi/2, 0.0, pi]],
]

DELAY = 0.5          # пауза между действиями
SAFE_DISTANCE = 0.15 # порог срабатывания защиты (в метрах)

# ----------------------------------------------------------------------
# 2. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (безопасность, логи, индикация)
# ----------------------------------------------------------------------
class SafetySystem:
    """Простая система безопасности: следит за человеком и аварийными состояниями."""
    def __init__(self, camera: SmartCamera, robot: RobotControl, lamp: LedLamp):
        self.camera = camera
        self.robot = robot
        self.lamp = lamp
        self.log_file = "safety_log.txt"

    def _log(self, message: str):
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {message}\n")

    def check(self) -> bool:
        """Возвращает True, если всё безопасно."""
        try:
            person = self.camera.getPerson()
            if person == 1:   # человек в рабочей зоне
                self._emergency_stop("Человек в рабочей зоне")
                return False

            # Проверка выхода за пределы рабочей зоны (пример по Z-координате)
            pos = self.robot.getToolPosition()
            if pos[2] < -0.05 or pos[2] > 0.80:
                self._emergency_stop(f"Выход за пределы зоны: {pos}")
                return False

            # Проверка температуры (аварийный перегрев)
            temps = self.robot.getActualTemperature()
            if any(t > 80.0 for t in temps):
                self._emergency_stop("Перегрев моторов")
                return False

        except Exception as e:
            self._log(f"Ошибка системы безопасности: {e}")
        return True

    def _emergency_stop(self, reason: str):
        self.robot.stop()
        self.robot.disengage()
        self.lamp.setLamp("0001")  # красный
        self._log(f"АВАРИЙНАЯ ОСТАНОВКА: {reason}")
        print(f"[SAFETY] {reason}")

# ----------------------------------------------------------------------
# 3. ОСНОВНАЯ ЛОГИКА МОДУЛЯ 2
# ----------------------------------------------------------------------
def build_program(robot: RobotControl):
    """Добавляет в программу все перемещения, захваты и разгрузку."""
    robot.reset()
    time.sleep(2)

    # --- Возврат в исходную позу (Г-образное положение) ---
    robot.addMoveToPointJ([Waypoint(HOME_POSE)])

    # --- Цикл: 3 объекта ---
    for i in range(3):
        # 1. Подход к точке захвата
        robot.addMoveToPointL([Waypoint(PICK_POSES[i])])
        robot.addWait(DELAY)

        # 2. Включение захвата
        robot.addToolState(1)
        robot.addWait(DELAY)

        # 3. Перемещение к разгрузочной ячейке (в один из отсеков)
        #    Например, в i-ю ячейку, первый отсек
        target = PLACE_POSES[i][0]
        robot.addMoveToPointL([Waypoint(target)])
        robot.addWait(DELAY)

        # 4. Выключение захвата (сброс объекта)
        robot.addToolState(0)
        robot.addWait(DELAY)

        # 5. Возврат в промежуточную точку (безопасная высота)
        robot.addMoveToPointL([Waypoint([target[0], target[1], target[2]+0.10,
                                         target[3], target[4], target[5]])])
        robot.addWait(DELAY)

    # --- Возврат в исходную позу ---
    robot.addMoveToPointJ([Waypoint(HOME_POSE)])

# ----------------------------------------------------------------------
# 4. ЗАПУСК
# ----------------------------------------------------------------------
def main():
    robot = RobotControl(ROBOT_IP)
    lamp = LedLamp(LAMP_IP)
    camera = SmartCamera(CAMERA_IP)

    safety = SafetySystem(camera, robot, lamp)

    # Индикация: красный до подключения
    lamp.setLamp("0001")

    if not robot.connect():
        print("[ERROR] Не удалось подключиться к роботу")
        return

    # Синий — подключение
    lamp.setLamp("1000")

    if not robot.engage():
        print("[ERROR] Не удалось включить двигатели")
        return

    print("[INFO] Robot is Engaged")

    # Формируем программу автоматизации
    build_program(robot)

    # Проверяем, что программа загружена
    if (robot.getRobotMode() is Modes.PAUSE_M.value and
        robot.getActualStateOut() is InterpreterStates.PROGRAM_STOP_S.value):
        print("[INFO] Программа загружена")

        # Переход к стартовой точке
        robot.activateMoveToStart()
        time.sleep(2)

        # Запуск
        robot.play()
        lamp.setLamp("0100")  # зелёный — работа

        # --- Основной цикл с контролем безопасности ---
        while not (robot.getActualStateOut() is InterpreterStates.PROGRAM_IS_DONE.value):
            if not safety.check():
                print("[SAFETY] Программа остановлена")
                break

            # Вывод состояния в терминал
            os.system('clear')
            print(f"Tool position: {robot.getToolPosition()}")
            print(f"Joint (rad):   {robot.getMotorPositionRadians()}")
            print(f"Program state: {robot.getActualStateOut()}")
            print(f"Robot mode:    {robot.getRobotMode()}")
            print(f"Tool state:    {robot.getToolState()}")
            print(f"Temperature:   {robot.getActualTemperature()}")
            print(f"Manipulability:{robot.getManipulability()}")
            print("Нажмите Ctrl+C для выхода")

            time.sleep(0.1)

        # --- Завершение ---
        lamp.setLamp("0001")  # красный
        robot.conveyer_stop()
        time.sleep(1)
        robot.disengage()
        print("[INFO] Работа завершена")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Прервано пользователем")
