
from motion.core import RobotControl, Waypoint, LedLamp
from motion.robot_control import Modes, InterpreterStates
from math import pi, sqrt, isfinite
import time


ROBOT_IP = "192.168.2.100"
LAMP_IP = "192.168.2.101"

# True: команды насоса и чтение его состояния отключены.
SIMULATION_MODE = True

# Скорость 10 % и штатное ускорение задаются в контроллере.
# Проверка траектории не выполняется.

HOME = [0.5, -0.12, 0.3, pi, 0.0, pi / 2]
HOME_JOINTS = [v * pi / 180 for v in (0, 15, 27, 47, 90, 0)]

ORIENTATION = [pi, 0.0, pi / 2]
Z_PLACE = 0.03
Z_TRANSFER = 0.20

GRIP_DELAY = 0.5
RELEASE_DELAY = 0.5
PROGRAM_TIMEOUT = 120.0

POSITION_TOLERANCE = 0.01
ANGLE_TOLERANCE = 0.1 * pi / 180
TOTAL_PACKAGES = 6

SOURCE = {
    "I":    (0.59, -0.100),
    "II":   (0.59,  0.005),
    "III":  (0.59,  0.110),
    "IV":   (0.50, -0.100),
    "V":    (0.50,  0.005),
    "VI":   (0.50,  0.110),
    "VII":  (0.41, -0.100),
    "VIII": (0.41,  0.005),
    "IX":   (0.41,  0.110),
}

DESTINATION = {
    1:  (0.60,  0.350),
    2:  (0.60,  0.460),
    3:  (0.60,  0.570),
    4:  (0.50,  0.350),
    5:  (0.50,  0.460),
    6:  (0.50,  0.570),
    7:  (0.40,  0.350),
    8:  (0.40,  0.460),
    9:  (0.40,  0.570),

    10: (0.59, -0.570),
    11: (0.59, -0.455),
    12: (0.59, -0.340),
    13: (0.50, -0.570),
    14: (0.50, -0.455),
    15: (0.50, -0.340),
    16: (0.41, -0.570),
    17: (0.41, -0.455),
    18: (0.41, -0.340),
}

COLUMNS = {
    1: [10, 13, 16],
    2: [11, 14, 17],
    3: [12, 15, 18],
}

DEFAULT_COLORS = ["зелёный", "розовый", "синий"]

LED = {
    "start": "0001",
    "checking": "1000",
    "moving": "0010",
    "ready": "0100",
    "error": "0001",
}


class ProgramError(RuntimeError):
    pass


def confirm(text):
    return input(f"{text} [да/нет]: ").strip().lower() == "да"


def ask_integer(text, maximum):
    while True:
        try:
            value = int(input(text))
            if 0 <= value <= maximum:
                return value
        except ValueError:
            pass

        print(f"Введите целое число от 0 до {maximum}.")


def normalize_color(text):
    return text.strip().lower().replace("ё", "е")


class Indicator:
    def __init__(self):
        self.lamp = None
        self.available = True
        self.without_lamp_allowed = False

    def set(self, state):
        if not self.available:
            return

        try:
            if self.lamp is None:
                self.lamp = LedLamp(LAMP_IP)

            if self.lamp.setLamp(LED[state]) is False:
                raise ProgramError("Команда лампы отклонена")

        except Exception as exc:
            self.available = False
            print(f"[ПОДСВЕТКА] Недоступна: {exc}")

    def request_permission(self):
        if self.available or self.without_lamp_allowed:
            return

        if not confirm("Продолжить без подсветки?"):
            raise ProgramError("Работа отменена оператором")

        self.without_lamp_allowed = True


class SortingProgram:
    def __init__(self):
        self.robot = RobotControl(ROBOT_IP)
        self.indicator = Indicator()

        self.motion_uncertain = False
        self.completed = []
        self.occupied = set()

    def set_vacuum(self, enabled):
        if SIMULATION_MODE:
            return

        self.robot.addToolState(1 if enabled else 0)

    def check_vacuum_off(self):
        if SIMULATION_MODE:
            return

        if self.robot.getToolState() != 0:
            raise ProgramError(
                "Выключение инструмента не подтверждено"
            )

    def pose(self):
        pose = [float(v) for v in self.robot.getToolPosition()]

        if len(pose) != 6 or not all(isfinite(v) for v in pose):
            raise ProgramError(f"Некорректная поза TCP: {pose}")

        return pose

    @staticmethod
    def point(xy, z):
        return [xy[0], xy [bsuir](https://www.bsuir.by/m/12_101523_1_108313.pdf), z] + ORIENTATION

    def verify_pose(self, target):
        actual = self.pose()

        distance = sqrt(sum(
            (actual[i] - target[i]) ** 2
            for i in range(3)
        ))

        angles = [
            abs((actual[i] - target[i] + pi) % (2 * pi) - pi)
            for i in range(3, 6)
        ]

        if distance > POSITION_TOLERANCE:
            raise ProgramError(
                f"Отклонение положения: {distance * 1000:.2f} мм"
            )

        if any(v > ANGLE_TOLERANCE for v in angles):
            raise ProgramError(
                "Отклонение ориентации, градусы: "
                f"{[round(v * 180 / pi, 4) for v in angles]}"
            )

    def reset_program(self):
        if self.motion_uncertain:
            raise ProgramError(
                "Очистка программы запрещена: "
                "завершение предыдущего движения не подтверждено"
            )

        self.robot.reset()
        time.sleep(5)

    def execute(self, description):
        mode = self.robot.getRobotMode()
        state = self.robot.getActualStateOut()

        if (
            mode != Modes.PAUSE_M.value
            or state != InterpreterStates.PROGRAM_STOP_S.value
        ):
            raise ProgramError(
                "Программа не готова к выполнению: "
                f"режим={mode}, состояние={state}"
            )

        self.indicator.set("moving")
        self.indicator.request_permission()

        print(f"[ДВИЖЕНИЕ] {description}")

        self.motion_uncertain = True
        self.robot.play()

        deadline = time.monotonic() + PROGRAM_TIMEOUT

        while True:
            state = self.robot.getActualStateOut()
            mode = self.robot.getRobotMode()

            if state == InterpreterStates.PROGRAM_IS_DONE.value:
                self.motion_uncertain = False
                return

            if state == InterpreterStates.PROGRAM_STOP_S.value:
                raise ProgramError("Программа остановлена")

            if state == InterpreterStates.MOTION_NOT_ALLOWED_S.value:
                raise ProgramError(
                    "Движение запрещено контроллером: "
                    f"режим={mode}, состояние={state}. "
                    "Автоматический выход к стартовой позе отключён."
                )

            if time.monotonic() >= deadline:
                raise ProgramError(
                    f"Превышено время выполнения: {description}"
                )

            self.pose()
            time.sleep(0.1)

    def startup(self):
        print("\n=== ЗАПУСК ARM95 ===")

        if SIMULATION_MODE:
            print("[СИМУЛЯТОР] Насос полностью игнорируется.")
        else:
            print("[ОБОРУДОВАНИЕ] Управление насосом включено.")

        self.indicator.set("start")
        self.indicator.request_permission()

        if not self.robot.connect():
            raise ProgramError("Нет связи с роботом")

        self.indicator.set("checking")
        self.indicator.request_permission()

        print("[TCP]", self.pose())
        print(
            "[СОЧЛЕНЕНИЯ]",
            self.robot.getMotorPositionRadians()
        )
        print(
            "[ТЕМПЕРАТУРЫ]",
            self.robot.getActualTemperature()
        )
        print("[СОСТОЯНИЕ]", self.robot.getRobotState())

        if not confirm(
            "Робот остановлен, скорость 10 %, ускорение штатное, "
            "маршруты проверены в симуляторе. Разрешить запуск?"
        ):
            raise ProgramError("Запуск отменён")

        if not self.robot.engage():
            raise ProgramError("Не удалось включить приводы")

        self.reset_program()

        self.set_vacuum(False)
        self.robot.addWait(RELEASE_DELAY)
        self.robot.addMoveToPointJ([
            Waypoint(HOME_JOINTS)
        ])

        self.execute("Выход в HOME по сочленениям")
        self.verify_pose(HOME)
        self.check_vacuum_off()

        self.indicator.set("ready")
        self.indicator.request_permission()

        print("[ГОТОВ] Запуск завершён")

    def transfer(self, source_id, destination_id):
        if destination_id in self.occupied:
            raise ProgramError(
                f"Приёмная ячейка {destination_id} уже занята"
            )

        source_xy = SOURCE[source_id]
        destination_xy = DESTINATION[destination_id]

        current = self.pose()
        lift = current.copy()
        lift [robot.bmstu](http://robot.bmstu.ru/lab/part1.htm) = max(current [robot.bmstu](http://robot.bmstu.ru/lab/part1.htm), Z_TRANSFER)

        source_above = self.point(source_xy, Z_TRANSFER)
        source_pick = self.point(source_xy, Z_PLACE)

        destination_above = self.point(
            destination_xy, Z_TRANSFER
        )
        destination_place = self.point(
            destination_xy, Z_PLACE
        )

        self.reset_program()

        self.set_vacuum(False)

        self.robot.addMoveToPointL([
            Waypoint(current),
            Waypoint(lift),
            Waypoint(source_above),
            Waypoint(source_pick),
        ])

        self.set_vacuum(True)
        self.robot.addWait(GRIP_DELAY)

        self.robot.addMoveToPointL([
            Waypoint(source_pick),
            Waypoint(source_above),
            Waypoint(destination_above),
            Waypoint(destination_place),
        ])

        self.set_vacuum(False)
        self.robot.addWait(RELEASE_DELAY)

        self.robot.addMoveToPointL([
            Waypoint(destination_place),
            Waypoint(destination_above),
        ])

        self.execute(f"{source_id} → {destination_id}")
        self.verify_pose(destination_above)
        self.check_vacuum_off()

        self.occupied.add(destination_id)
        self.completed.append((source_id, destination_id))

        if SIMULATION_MODE:
            print(
                f"[СИМУЛЯЦИЯ ВЫПОЛНЕНА] "
                f"{source_id} → {destination_id}"
            )
        else:
            print(
                f"[КОМАНДЫ ПЕРЕНОСА ВЫПОЛНЕНЫ] "
                f"{source_id} → {destination_id}"
            )

    def return_home(self):
        self.reset_program()

        self.set_vacuum(False)
        self.robot.addMoveToPointJ([
            Waypoint(HOME_JOINTS)
        ])

        self.execute("Возврат в HOME")
        self.verify_pose(HOME)
        self.check_vacuum_off()

        self.indicator.set("ready")
        self.indicator.request_permission()

    def report_error(self, exc):
        self.indicator.set("error")

        print(f"\n[ОШИБКА] {exc or 'Прерывание оператором'}")
        print("[ВЫПОЛНЕННЫЕ ОПЕРАЦИИ]", self.completed)

        if self.motion_uncertain:
            print(
                "Завершение движения не подтверждено. "
                "Команда остановки в этом коде не реализована."
            )
            print(
                "При работе на оборудовании при необходимости "
                "используйте аварийную кнопку."
            )

        print(
            "Автоматическое возобновление отключено. "
            "Перед повторным запуском проверьте состояние робота "
            "и фактическое расположение упаковок."
        )


def ask_colors():
    while True:
        colors = []

        for column, default in enumerate(DEFAULT_COLORS, 1):
            value = input(
                f"Цвет для столбца {column} "
                f"[Enter — {default}]: "
            ).strip()

            colors.append(normalize_color(value or default))

        if (
            len(set(colors)) == 3
            and not any(
                color in ("брак", "остальные")
                for color in colors
            )
        ):
            return colors

        print(
            "Цвета должны различаться и не называться "
            "«брак» или «остальные»."
        )


def ask_inventory(colors):
    categories = ["брак"] + colors + ["остальные"]

    while True:
        counts = {}

        for category in categories:
            maximum = (
                3 if category in colors
                else TOTAL_PACKAGES
            )

            counts[category] = ask_integer(
                f"Количество «{category}»: ",
                maximum,
            )

        if sum(counts.values()) == TOTAL_PACKAGES:
            break

        print(
            f"Суммарно должно быть {TOTAL_PACKAGES} упаковок. "
            "Бракованные не учитываются повторно среди цветных."
        )

    inventory = {}
    used = set()

    for category in categories:
        count = counts[category]

        if count == 0:
            inventory[category] = []
            continue

        while True:
            values = input(
                f"Ячейки «{category}» — {count} шт., "
                "через пробел (I–IX): "
            ).upper().replace(",", " ").split()

            valid = (
                len(values) == count
                and len(set(values)) == count
                and all(value in SOURCE for value in values)
                and not used.intersection(values)
            )

            if valid:
                inventory[category] = values
                used.update(values)
                break

            print(
                "Неверные номера, количество "
                "или повтор исходной ячейки."
            )

    return inventory


def build_plan(colors, inventory):
    plan = []

    for destination, source in enumerate(
        inventory["брак"], 1
    ):
        plan.append(("брак", source, destination))

    for column, color in enumerate(colors, 1):
        for source, destination in zip(
            inventory[color],
            COLUMNS[column],
        ):
            plan.append((color, source, destination))

    return plan


def main():
    program = SortingProgram()

    try:
        program.startup()

        print("\n=== НАСТРОЙКА СОРТИРОВКИ ===")

        colors = ask_colors()
        inventory = ask_inventory(colors)
        plan = build_plan(colors, inventory)

        print("\n=== ПЛАН ОПЕРАЦИЙ ===")

        for category, source, destination in plan:
            print(
                f"{category}: {source} → {destination}"
            )

        print(
            "Оставить на месте:",
            inventory["остальные"],
        )

        if not plan:
            print("Переносов нет. Робот остаётся в HOME.")
            return

        if not confirm(
            "Приёмные секции 1–9 и 10–18 пустые. "
            "Выполнить план?"
        ):
            print(
                "Сортировка отменена. "
                "Робот остаётся готовым."
            )
            return

        for category, source, destination in plan:
            print(f"\n[СОРТИРОВКА] {category}")
            program.transfer(source, destination)

        program.return_home()

        print("\n[ГОТОВ] Сортировка завершена")
        print(
            "Выполнено операций:",
            len(program.completed),
        )

        if SIMULATION_MODE:
            print(
                "Насос не использовался. "
                "Физический перенос упаковок не подтверждается."
            )
        else:
            print(
                "Инструмент выключен. "
                "Захват датчиком не проверялся."
            )

        print("Приводы остаются включёнными.")

    except (Exception, KeyboardInterrupt) as exc:
        program.report_error(exc)

    finally:
        print("Завершение консольной программы.")
        # Приводы автоматически не отключаем.


if __name__ == "__main__":
    main()