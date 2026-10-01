import time
from math import sqrt,pi,isfinite
from motion.core import RobotControl,Waypoint,LedLamp
from motion.robot_control import Modes,InterpreterStates
import config as c

class Backend:
    def __init__(self,log,ask):
        self.log,self.ask=log,ask
        self.robot=None;self.lamp=None
        self.no_lamp=False;self.ready=False;self.uncertain=False
        self.completed=[]

    def light(self,state):
        if self.no_lamp:return
        try:
            if self.lamp is None:self.lamp=LedLamp(c.LAMP_IP)
            if self.lamp.setLamp(c.LED[state]) is False:
                raise RuntimeError("Команда лампы отклонена")
        except Exception as exc:
            self.log(f"Лампа недоступна: {exc}")
            if not self.ask("Продолжить без подсветки?"):
                raise RuntimeError("Работа отменена оператором")
            self.no_lamp=True

    def pose(self):
        p=[float(v) for v in self.robot.getToolPosition()]
        if len(p)!=6 or not all(isfinite(v) for v in p):
            raise RuntimeError("Некорректная поза TCP")
        return p

    def verify(self,target):
        p=self.pose()
        d=sqrt(sum((p[i]-target[i])**2 for i in range(3)))
        angles=[abs((p[i]-target[i]+pi)%(2*pi)-pi) for i in range(3,6)]
        if d>c.POSITION_TOLERANCE or any(a>c.ANGLE_TOLERANCE for a in angles):
            raise RuntimeError(f"Цель не достигнута: {d*1000:.2f} мм; углы {[round(a*180/pi,4) for a in angles]}°")

    def reset(self):
        if self.uncertain:raise RuntimeError("Остановка/завершение движения не подтверждены")
        self.robot.reset();time.sleep(c.RESET_DELAY)

    def execute(self,label):
        mode=self.robot.getRobotMode();state=self.robot.getActualStateOut()
        if mode!=Modes.PAUSE_M.value or state!=InterpreterStates.PROGRAM_STOP_S.value:
            raise RuntimeError(f"Программа не готова: режим={mode}, состояние={state}")
        self.light("moving");self.log(label)
        self.uncertain=True
        self.robot.play()
        deadline=time.monotonic()+c.TIMEOUT
        while True:
            state=self.robot.getActualStateOut()
            if state==InterpreterStates.PROGRAM_IS_DONE.value:
                self.uncertain=False;return
            if state in (InterpreterStates.PROGRAM_STOP_S.value,InterpreterStates.MOTION_NOT_ALLOWED_S.value):
                raise RuntimeError(f"Останов или запрет движения: {state}")
            if time.monotonic()>deadline:raise RuntimeError("Тайм-аут движения")
            self.pose();time.sleep(c.POLL_INTERVAL)

    def home(self):
        self.reset()
        self.robot.addToolState(0)
        self.robot.addWait(c.RELEASE_DELAY)
        self.robot.addMoveToPointJ([Waypoint(c.HOME_JOINTS)])
        self.execute("Выход в HOME по сочленениям")
        self.verify(c.HOME)

    def startup(self):
        if self.uncertain:raise RuntimeError("Повтор заблокирован до внешней проверки остановки")
        self.ready=False
        self.light("start")
        self.robot=RobotControl(c.ROBOT_IP)
        if not self.robot.connect():raise RuntimeError("Нет связи с роботом")
        self.light("checking")
        self.log(f"TCP: {self.pose()}")
        if not self.ask("Робот остановлен; скорость 10 % и штатное ускорение настроены; TCP, выход вакуума и маршруты проверены. Включить приводы и выйти в HOME?"):
            raise RuntimeError("Запуск отменён")
        if not self.robot.engage():raise RuntimeError("Не удалось включить приводы")
        self.home();self.light("ready");self.ready=True
        self.log("ГОТОВ. Приводы включены")

    def transfer(self,src,dst):
        if src not in c.SOURCE or dst not in c.TARGET:raise ValueError("Неизвестная ячейка")
        p=self.pose();lift=p.copy();lift[2]=max(p[2],c.Z_TRANSFER)
        def point(xy,z):return [*xy,z,*c.ORIENTATION]
        sa=point(c.SOURCE[src],c.Z_TRANSFER);sp=point(c.SOURCE[src],c.Z_PLACE)
        da=point(c.TARGET[dst],c.Z_TRANSFER);dp=point(c.TARGET[dst],c.Z_PLACE)
        self.reset()
        self.robot.addToolState(0)
        self.robot.addMoveToPointL([Waypoint(v) for v in (p,lift,sa,sp)])
        self.robot.addToolState(1);self.robot.addWait(c.GRIP_DELAY)
        self.robot.addMoveToPointL([Waypoint(v) for v in (sp,sa,da,dp)])
        self.robot.addToolState(0);self.robot.addWait(c.RELEASE_DELAY)
        self.robot.addMoveToPointL([Waypoint(dp),Waypoint(da)])
        self.execute(f"Перенос {src} → {dst}")
        self.verify(da)

    def run(self,plan):
        if not self.ready:raise RuntimeError("Сначала выполните запуск")
        if not 1<=len(plan)<=c.TOTAL_PACKAGES:raise ValueError("Неверное число переносов")
        if len({r[0] for r in plan})!=len(plan) or len({r[2] for r in plan})!=len(plan):
            raise ValueError("Повтор исходной или приёмной ячейки")
        self.ready=False;self.completed=[]
        for src,category,dst in plan:
            self.transfer(src,dst)
            self.completed.append((src,category,dst))
            self.log(f"Команды выполнены: {src} / {category} → {dst}")
        self.home();self.light("ready");self.ready=True

    def fail(self,exc):
        self.ready=False;self.log(f"ОШИБКА: {exc}")
        try:
            if self.lamp is not None and not self.no_lamp:self.lamp.setLamp(c.LED["error"])
        except Exception:pass
        if self.uncertain:self.log("Остановка НЕ подтверждена. При необходимости используйте аппаратную аварийную кнопку.")
