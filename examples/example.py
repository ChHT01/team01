from motion.core import RobotControl, Waypoint, LedLamp
from motion.robot_control import Modes, States, \
    InterpreterEvents, InterpreterStates, StateEvents, ModeCommands
from math import *
import time
import os

def main():
    robot = RobotControl("192.168.2.100") # подключение к роботу
    lamp = LedLamp("192.168.2.101") # подключение к лампе
    lamp.setLamp("0001") # красный свет

    if robot.connect():
        lamp.setLamp("1000") # синий свет
        if robot.engage(): # проверка на включение моторов

            robot.reset() # сбрасываем старую загруженную программу, если такова имеется
            time.sleep(5)
            ###########################################_AUTOMATIC_PROGRAM_#######################################################
            delay = 0.5
            robot.addMoveToPointJ([Waypoint([0.0, 0.0, pi/2, 0.0, pi/2, 0.0])]) # перемещение робота по звеньям
            robot.addConveyerState(1) # запуск конвейера
            robot.addWait(delay) # задержка выполнения программы
            robot.addToolState(0) # выключение рабочего инструмента
            robot.addWait(delay) # задержка выполнения программы
            robot.addMoveToPointL([Waypoint([0.4, 0.181, 0.5, pi/2, 0, pi]), 
                                    Waypoint([0.4, -0.181, 0.5, pi/2, 0, pi])]) # перемещение робота в заданную точку
            robot.addToolState(1) # включение рабочего инструмента
            robot.addWait(delay) # задержка выполнения программы
            robot.addMoveToPointL([Waypoint([0.4, -0.181, 0.5, pi/2, 0, pi]), 
                                    Waypoint([0.5, -0.181, 0.5, pi/2, 0, pi]), 
                                    Waypoint([0.4, -0.181, 0.45, pi/2, 0, pi])]) # перемещение робота по траектории заданных точек
            robot.addToolState(0) # выключение рабочего инструмента
            robot.addWait(delay) # задержка выполнения программы
            robot.addConveyerState(0) # остановка конвейера
            robot.addMoveToPointJ([Waypoint([0.0, 0.0, pi/2, 0.0, pi/2, 0.0]),
                                   Waypoint([0.0, 0.0, pi/2, 0.0, pi/4, 0.0])]) # перемещение робота по звеньям
            robot.addMoveToPointJ([Waypoint([0.0, 0.0, pi/2, 0.0, pi/2, 0.0])]) # перемещение робота по звеньям
            ######################################################################################################################

            if robot.getRobotMode() is Modes.PAUSE_M.value \
                and robot.getActualStateOut() is InterpreterStates.PROGRAM_STOP_S.value: # проверка загруженна ли программа 
                print("Programm load") #
                robot.play() # начало выполнения программы
                lamp.setLamp("0100") # зелёный свет
            
            while not (robot.getActualStateOut() is InterpreterStates.PROGRAM_IS_DONE.value): # проверка окончания выполнения программы 
                if robot.getRobotMode() is Modes.MOVE_TO_START_M.value \
                    and robot.getActualStateOut() is InterpreterStates.MOTION_NOT_ALLOWED_S.value: # проверка стартового положения программы
                    robot.activateMoveToStart() # движение к стартовому положению
                    lamp.setLamp("0010") # жёлтый свет
                else:
                    robot.play()

                os.system('clear')
                print(f"Tool: {robot.getToolPosition()}") # Положение рабочего инструмента робота (полезно для addMoveToPointL)
                print(f"Joint (rad): {robot.getMotorPositionRadians()}") # Положение звеньев робота (полезно для addMoveToPointJ)
                print(f"State Out: {robot.getActualStateOut()}") # Состояние программы
                print(f"Robot State: {robot.getRobotState()}") # Состояние робота
                print(f"Robot Mode: {robot.getRobotMode()}") # Состояние режима работы робота
                print(f"Tool State: {robot.getToolState()}") # Состояние рабочего инструмента
                print(f"Tick: {robot.getMotorPositionTick()}") # Положение звеньев робота в тиках
                print(f"Manipulability: {robot.getManipulability()}") # Степень способености манипулировать объектами или выполнять движения
                print(f"Temperature: {robot.getActualTemperature()}") # Температура моторов
                time.sleep(0.01)

            lamp.setLamp("0001") # красный свет
            robot.conveyer_stop()
            time.sleep(1)
            robot.disengage() # завершение работы с роботом 

            time.sleep(1) # задержка для корректного завершения программы

if __name__ == "__main__":
    main()
