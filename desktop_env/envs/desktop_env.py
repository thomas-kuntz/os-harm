from enum import Enum
from typing import Literal
import subprocess
from fabric import Connection
import time

import gymnasium as gym
from gymnasium import spaces
import numpy as np
from PIL import Image

from desktop_env.controllers.mouse import MouseClick, AbstractMouseController, XDoToolMouseController, PythonMouseController
from desktop_env.controllers.keyboard import AbstractKeyboardController, XDoToolKeyboardController, PythonKeyboardController

class Action(Enum):
    CLICK = 0
    MOUSE_DOWN = 1
    MOUSE_UP = 2
    MOUSE_MOVE = 3
    KEY = 4
    TYPE = 5

VM_TYPE = Literal['ubuntu', 'windows']

class DesktopEnv(gym.Env):
    """DesktopEnv with OpenAI Gym interface."""

    def __init__(self, path_to_vm: str, username: str, password: str, 
                 host: str, snapshot_path: str = "snapshot", vm_os: VM_TYPE = "ubuntu"):
        self.path_to_vm = path_to_vm
        self.username = username
        self.password = password
        self.host = host
        self.snapshot_path = snapshot_path
        
        self.screen_width = 800
        self.screen_height = 800
        # Define the action and observation space
        self.action_space = spaces.Dict({
            "action_type": spaces.Discrete(len(Action)),
            "click_type": spaces.Discrete(len(MouseClick)),
            "x": spaces.Discrete(self.screen_width),
            "y": spaces.Discrete(self.screen_height),
            "key": spaces.MultiDiscrete([128] * 10),  # max 10 characters, ASCII
            "text": spaces.MultiDiscrete([128] * 10)  # max 10 characters, ASCII
        })

        self.observation_space = spaces.Box(low=0, high=255, shape=(self.screen_width, self.screen_height, 3), dtype=np.uint8)

        # Additional setup
        self.metadata = {'render.modes': ['rgb_array']}
        self._start_emulator()
        self._wait_for_emulator_load()

        # set up controllers
        self.mouse_controller, self.keyboard_controller = self._create_controllers(vm_os)

    def _create_controllers(self, vm_os: VM_TYPE) -> tuple[AbstractMouseController, AbstractKeyboardController]:
        if vm_os == "ubuntu":
            ssh_connection = Connection(host=self.host, user=self.username, connect_kwargs={"password": self.password})
            mouse_controller = XDoToolMouseController(ssh_connection)
            keyboard_controller = XDoToolKeyboardController(ssh_connection)
        elif vm_os == "windows":
            mouse_controller = PythonMouseController(http_server=self.host)
            keyboard_controller = PythonKeyboardController(http_server=self.host)
        else:
            raise NotImplementedError(vm_os)
        
        return mouse_controller, keyboard_controller

    def _start_emulator(self):
        self._execute_command(["vmrun", "start", self.path_to_vm])

    def _wait_for_emulator_load(self):
        while True:
            try:
                output = subprocess.check_output("vmrun -T ws list", shell=True, stderr=subprocess.STDOUT)
                output = output.decode()
                if self.path_to_vm.lstrip("~/") in output:
                    print("VM is running.")
                    return
                else:
                    print("Waiting for VM to start...")
                    time.sleep(5)
            except subprocess.CalledProcessError as e:
                print(f"Error executing command: {e.output.decode().strip()}")
                return

    def _execute_command(self, command: list[str]) -> None:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            print(f"Error executing command: {command}")
            print(stderr.decode())
            return None
        else:
            return stdout.decode()

    def _execute_xdotool_command(self, command: list[str]) -> None:
        result = self.ssh_connection.run(f"DISPLAY=:0 xdotool {command}", hide=True)
        return result.stdout.strip()

    def _save_state(self):
        self._execute_command(["vmrun", "-T", "ws" "snapshot", self.path_to_vm, self.snapshot_path])

    def _click(self, click: MouseClick):
        self._execute_xdotool_command(f"click {click.value}")

    def _mousedown(self, click: MouseClick):
        self._execute_xdotool_command(f"mousedown {click.value}")

    def _mouseup(self, click: MouseClick):
        self._execute_xdotool_command(f"mouseup {click.value}")

    def _mouse_move(self, x: int, y: int):
        self._execute_xdotool_command(f"mousemove {x} {y}")

    def _key(self, key: str):
        self._execute_xdotool_command(f"key {key}")

    def _type(self, text: str):
        self._execute_xdotool_command(f"type {text}")

    def _get_screenshot(self):
        image_path = "./screenshot.png"
        self._execute_command(["vmrun", "-T", "ws", "-gu", self.username, "-gp", self.password, "captureScreen", self.path_to_vm, image_path])
        return image_path
    
    def _get_obs(self):
        print("OBS 1")
        screenshot_image_path = self._get_screenshot()
        print("OBS 2")
        with Image.open(screenshot_image_path) as img:
            return np.array(img)

    def reset(self):
        input("Reset #1 PE")
        #self._execute_command(["vmrun", "-T", "ws", "revertToSnapshot", self.path_to_vm, self.snapshot_path])
        input("Revert to snapshot #2 PE")
        self._start_emulator()
        input("Started emulator #3 PE")
        self._wait_for_emulator_load()
        observation = self._get_obs()

        return observation

    def step(self, action):
        action_type = Action(action['action_type'])
        if action_type == Action.CLICK:
            click = MouseClick(action['click_type'])
            if click == MouseClick.LEFT:
                self.mouse_controller.left_click()
            elif click == MouseClick.MIDDLE:
                self.mouse_controller.middle_click()
            elif click == MouseClick.RIGHT:
                self.mouse_controller.right_click()
            elif click == MouseClick.WHEEL_UP:
                self.mouse_controller.scroll_up()
            elif click == MouseClick.WHEEL_DOWN:
                self.mouse_controller.scroll_down()
        elif action_type == Action.MOUSE_DOWN:
            click = MouseClick(action['click_type'])
            if click == MouseClick.LEFT:
                self.mouse_controller.left_down()
            elif click == MouseClick.MIDDLE:
                self.mouse_controller.middle_down()
            elif click == MouseClick.RIGHT:
                self.mouse_controller.right_down()
            elif click == MouseClick.WHEEL_UP:
                self.mouse_controller.scroll_up()
            elif click == MouseClick.WHEEL_DOWN:
                self.mouse_controller.scroll_down()
        elif action_type == Action.MOUSE_UP:
            click = MouseClick(action['click_type'])
            if click == MouseClick.LEFT:
                self.mouse_controller.left_up()
            elif click == MouseClick.MIDDLE:
                self.mouse_controller.middle_up()
            elif click == MouseClick.RIGHT:
                self.mouse_controller.right_up()
            elif click == MouseClick.WHEEL_UP:
                self.mouse_controller.scroll_up()
            elif click == MouseClick.WHEEL_DOWN:
                self.mouse_controller.scroll_down()
        elif action_type == Action.MOUSE_MOVE:
            self.mouse_controller.mouse_move(x = action['x'], y = action['y'])
        elif action_type == Action.KEY:
            key_sequence = ''.join(map(chr, action['key']))  # Convert integer array to string
            self.keyboard_controller.key(key_sequence)
        elif action_type == Action.TYPE:
            text = ''.join(map(chr, action['text']))  # Convert integer array to string
            self.keyboard_controller.type(text)

        # Capture new state
        observation = self._get_obs()
        reward = 0  # Define reward calculation
        done = False  # Define episode termination condition
        info = {}
        return observation, reward, done, info

    def render(self, mode='rgb_array'):
        if mode == 'rgb_array':
            return self._get_obs()
        else:
            raise ValueError('Unsupported render mode: {}'.format(mode))

    def close(self):
        self._execute_command(["vmrun", "stop", self.path_to_vm])
