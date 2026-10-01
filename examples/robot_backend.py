import time
from math import sqrt, pi, isfinite
from motion.core import RobotControl, Waypoint, LedLamp
from motion.robot_control import Modes, InterpreterStates
import config as c

class Backend:

    def __init__(self, log, ask):
        self.log, self.ask = (log, ask)
        self.robot = None
        self.lamp = None
        self.no_lamp = False
        self.ready = False
        self.uncertain = False
        self.completed = []

    def light(self, state):
        if self.no_lamp:
            return
        try:
            if self.lamp is None:
                self.lamp = LedLamp(c.LAMP_IP)
            if self.lamp.setLamp(c.LED[state]) is False:
                raise RuntimeError('Команда лампы отклонена')
        except Exception as exc:
            self.log(f'Лампа недоступна: {exc}')
            if not self.ask('Продолжить без подсветки?'):
                raise RuntimeError('Работа отменена оператором')
            self.no_lamp = True

    def pose(self):
        p = [float(v) for v in self.robot.getToolPosition()]
        if len(p) != 6 or not all((isfinite(v) for v in p)):
            raise RuntimeError('Некорректная поза TCP')
        return p

    def verify(self, target):
        p = self.pose()
        d = sqrt(sum(((p[i] - target[i]) ** 2 for i in range(3))))
        angles = [abs((p[i] - target[i] + pi) % (2 * pi) - pi) for i in range(3, 6)]
        if d > c.POSITION_TOLERANCE or any((a > c.ANGLE_TOLERANCE for a in angles)):
            raise RuntimeError(f'Цель не достигнута: {d * 1000:.2f} мм; углы {[round(a * 180 / pi, 4) for a in angles]}°')

    def reset(self):
        if self.uncertain:
            raise RuntimeError('Остановка/завершение движения не подтверждены')
        self.robot.reset()
        time.sleep(c.RESET_DELAY)

    def execute(self, label):
        mode = self.robot.getRobotMode()
        state = self.robot.getActualStateOut()
        if mode != Modes.PAUSE_M.value or state != InterpreterStates.PROGRAM_STOP_S.value:
            raise RuntimeError(f'Программа не готова: режим={mode}, состояние={state}')
        start_timeout = float(getattr(c, 'START_TIMEOUT', 5.0))
        if not isfinite(start_timeout) or start_timeout <= 0:
            raise ValueError('START_TIMEOUT должен быть положительным')
        self.light('moving')
        self.log(label)
        self.uncertain = True
        started = False
        last_state = None
        t0 = time.monotonic()
        self.robot.play()
        while True:
            state = self.robot.getActualStateOut()
            now = time.monotonic()
            if state != last_state:
                self.log(f'Состояние программы: {state}')
                last_state = state
            if state == InterpreterStates.PROGRAM_IS_DONE.value:
                self.uncertain = False
                self.log('Контроллер сообщил о завершении программы')
                return
            if state == InterpreterStates.MOTION_NOT_ALLOWED_S.value:
                raise RuntimeError('Запрет движения: состояние=3')
            if state == InterpreterStates.PROGRAM_PAUSE_S.value:
                raise RuntimeError('Программа на паузе: состояние=2')
            if state == InterpreterStates.PROGRAM_RUN_S.value:
                started = True
            elif state == InterpreterStates.PROGRAM_STOP_S.value:
                if started:
                    raise RuntimeError('Останов после начала выполнения: состояние=0')
            elif state != InterpreterStates.IN_TRANSITION.value:
                raise RuntimeError(f'Неизвестное состояние: {state}')
            if not started and now - t0 >= start_timeout:
                raise RuntimeError(f'Запуск не подтверждён: режим={self.robot.getRobotMode()}, состояние={state}')
            if now - t0 >= c.TIMEOUT:
                raise RuntimeError(f'Тайм-аут выполнения: состояние={state}')
            self.pose()
            time.sleep(c.POLL_INTERVAL)

    def home(self):
        self.reset()
        self.robot.addToolState(0)
        self.robot.addWait(c.RELEASE_DELAY)
        self.robot.addMoveToPointJ([Waypoint(c.HOME_JOINTS)])
        self.execute('Выход в HOME по сочленениям')
        self.verify_home_joints()
        self.log(f'TCP после HOME: {self.pose()}')

    def startup(self):
        if self.uncertain:
            raise RuntimeError('Повтор заблокирован до внешней проверки остановки')
        self.ready = False
        self.light('start')
        self.robot = RobotControl(c.ROBOT_IP)
        if not self.robot.connect():
            raise RuntimeError('Нет связи с роботом')
        self.light('checking')
        self.log(f'TCP: {self.pose()}')
        if not self.ask('Робот остановлен; скорость 10 % и штатное ускорение настроены; TCP, выход вакуума и маршруты проверены. Включить приводы и выйти в HOME?'):
            raise RuntimeError('Запуск отменён')
        if not self.robot.engage():
            raise RuntimeError('Не удалось включить приводы')
        self.home()
        self.light('ready')
        self.ready = True
        self.log('ГОТОВ. Приводы включены')

    def transfer(self, src, dst):
        if src not in c.SOURCE or dst not in c.TARGET:
            raise ValueError("Неизвестная ячейка")

        p = self.pose()

        # Одна ориентация TCP для всех точек переноса.
        orientation = p[3:6].copy()

        lift = p.copy()
        lift[2] = max(p[2], c.Z_TRANSFER)

        def point(xy, z):
            return [
                float(xy[0]),
                float(xy[1]),
                float(z),
                *orientation,
            ]

        source_above = point(c.SOURCE[src], c.Z_TRANSFER)
        source_place = point(c.SOURCE[src], c.Z_PLACE)

        target_above = point(c.TARGET[dst], c.Z_TRANSFER)
        target_place = point(c.TARGET[dst], c.Z_PLACE)

        self.log(
            "Ориентация TCP для переноса, градусы: "
            f"{[round(v * 180 / pi, 4) for v in orientation]}"
        )

        self.reset()

        self.robot.addToolState(0)

        self.robot.addMoveToPointL([
            Waypoint(v)
            for v in (
                p,
                lift,
                source_above,
                source_place,
            )
        ])

        self.robot.addToolState(1)
        self.robot.addWait(c.GRIP_DELAY)

        self.robot.addMoveToPointL([
            Waypoint(v)
            for v in (
                source_place,
                source_above,
                target_above,
                target_place,
            )
        ])

        self.robot.addToolState(0)
        self.robot.addWait(c.RELEASE_DELAY)

        self.robot.addMoveToPointL([
            Waypoint(target_place),
            Waypoint(target_above),
        ])

        self.execute(f"Перенос {src} → {dst}")
        self.verify(target_above)

    def run(self, plan):
        if not self.ready:
            raise RuntimeError('Сначала выполните запуск')
        if not 1 <= len(plan) <= c.TOTAL_PACKAGES:
            raise ValueError('Неверное число переносов')
        if len({r[0] for r in plan}) != len(plan) or len({r[2] for r in plan}) != len(plan):
            raise ValueError('Повтор исходной или приёмной ячейки')
        self.ready = False
        self.completed = []
        for src, category, dst in plan:
            self.transfer(src, dst)
            self.completed.append((src, category, dst))
            self.log(f'Команды выполнены: {src} / {category} → {dst}')
        self.home()
        self.light('ready')
        self.ready = True

    def fail(self, exc):
        self.ready = False
        self.log(f'ОШИБКА: {exc}')
        try:
            if self.lamp is not None and (not self.no_lamp):
                self.lamp.setLamp(c.LED['error'])
        except Exception:
            pass
        if self.uncertain:
            self.log('Остановка НЕ подтверждена. При необходимости используйте аппаратную аварийную кнопку.')

    def verify_home_joints(self):
        actual = [float(v) for v in self.robot.getMotorPositionRadians()]
        target = [float(v) for v in c.HOME_JOINTS]
        if len(actual) != 6 or len(target) != 6 or (not all((isfinite(v) for v in actual + target))):
            raise RuntimeError('Некорректные суставные координаты HOME')
        tolerance = float(getattr(c, 'HOME_JOINT_TOLERANCE', pi / 180))
        if not isfinite(tolerance) or tolerance <= 0:
            raise ValueError('HOME_JOINT_TOLERANCE должен быть положительным')
        errors = [abs(a - b) for a, b in zip(actual, target)]
        errors_deg = [round(v * 180 / pi, 4) for v in errors]
        self.log(f'Отклонения суставов HOME: {errors_deg}°')
        if any((v > tolerance for v in errors)):
            raise RuntimeError(f'Суставной HOME не достигнут: {errors_deg}°')
