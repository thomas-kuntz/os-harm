from __future__ import annotations

import os
import subprocess
import time
import uuid
import platform
from typing import List

import gymnasium as gym
import requests

from desktop_env.controllers.python import PythonController
from desktop_env.controllers.setup import SetupController
from desktop_env.evaluators import eval_funcs


def _execute_command(command: List[str]) -> None:
    if command[:4] == ["vmrun", "-T", "ws", "start"]:
        p = subprocess.Popen(command)
        p.wait()
    else:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, text=True)
        if result.returncode != 0:
            raise Exception("\033[91m" + result.stdout + result.stderr + "\033[0m")
        return result.stdout


class DesktopEnv(gym.Env):
    """DesktopEnv with OpenAI Gym interface."""

    def __init__(
            self,
            path_to_vm: str,
            snapshot_path: str = "base",
            instruction: str = None,
            config: dict = None,
            evaluator: dict = None,
            action_space: str = "computer_13",
    ):
        # Initialize environment variables
        self.path_to_vm = path_to_vm
        self.snapshot_path = snapshot_path  # todo: handling the logic of snapshot directory

        # Initialize emulator and controller
        print("Initializing...")
        self._start_emulator()
        self.host = f"http://{self._get_vm_ip()}:5000"
        self.controller = PythonController(http_server=self.host)
        self.setup_controller = SetupController(http_server=self.host)
        self.instruction = instruction
        self.config = config
        self.evaluator = evaluator

        # mode: human or machine
        assert action_space in ["computer_13", "pyautogui"]
        self.action_space = action_space
        # todo: define the action space and the observation space as gym did, or extend theirs

    def _start_emulator(self):
        while True:
            try:
                output = subprocess.check_output(f"vmrun -T ws list", shell=True, stderr=subprocess.STDOUT)
                output = output.decode()
                if self.path_to_vm.lstrip("~/") in output:
                    print("VM is running.")
                    break
                else:
                    print("Starting VM...")
                    _execute_command(["vmrun", "-T", "ws", "start", self.path_to_vm])
                    time.sleep(3)
            except subprocess.CalledProcessError as e:
                print(f"Error executing command: {e.output.decode().strip()}")

    def _get_vm_ip(self):
        max_retries = 10
        print("Getting IP Address...")
        for _ in range(max_retries):
            try:
                output = _execute_command(["vmrun", "-T", "ws", "getGuestIPAddress", self.path_to_vm]).strip()
                print(f"IP address: {output}")
                return output
            except:
                time.sleep(5)
                print("Retrying...")
        raise Exception("Failed to get VM IP address!")

    def _save_state(self):
        _execute_command(["vmrun", "-T", "ws" "snapshot", self.path_to_vm, self.snapshot_path])

    def _get_screenshot(self):
        random_uuid = str(uuid.uuid4())
        os.makedirs(os.path.join("tmp", random_uuid), exist_ok=True)
        image_path = os.path.join("tmp", random_uuid, "screenshot.png")

        # Get the screenshot and save to the image_path
        screenshot = self.controller.get_screenshot()
        with open(image_path, "wb") as f:
            f.write(screenshot)

        return image_path

    def _get_obs(self):
        screenshot_image_path = self._get_screenshot()
        return screenshot_image_path

    def reset(self, seed=None, options=None):
        print("Resetting environment...")

        print("Reverting to snapshot to {}...".format(self.snapshot_path))
        _execute_command(["vmrun", "-T", "ws", "revertToSnapshot", self.path_to_vm, self.snapshot_path])
        time.sleep(5)

        print("Starting emulator...")
        self._start_emulator()
        print("Emulator started.")

        print("Setting up environment...")
        self.setup_controller.setup(self.config)

        time.sleep(5)
        print("Environment setup complete.")

        observation = self._get_obs()
        return observation

    def step(self, action, pause=0.5):
        # fixme: add reminding logic here, decide if the action is valid for the current action_space
        if self.action_space == "computer_13":
            # the set of all possible actions defined in the action representation
            self.controller.execute_action(action)
        elif self.action_space == "pyautogui":
            # the set of all possible python commands insides `pyautogui`
            self.controller.execute_python_command(action)

        # todo: maybe for the better here we need to add a logic to wait until the rendering is done
        time.sleep(pause)
        observation = {
            "screenshot": self._get_obs(),
            "instruction": self.instruction
        }
        reward = 0  # todo: Define reward calculation for each example
        done = False  # todo: Define episode termination condition for each example
        info = {}
        return observation, reward, done, info

    def evaluate(self):
        """
        Evaluate whether the task is successfully completed.
        """
        def copy_file_to_local(_file_info):
            random_uuid = str(uuid.uuid4())
            os.makedirs(os.path.join("tmp", random_uuid), exist_ok=True)
            _path = os.path.join("tmp", random_uuid, "tmp.xlsx")
            if _file_info["type"] == "cloud_file":
                url = _file_info["path"]
                response = requests.get(url, stream=True)
                response.raise_for_status()

                with open(_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            elif _file_info["type"] == "vm_file":
                # fixme: stream this part maybe as well
                file = self.controller.get_file(_file_info["path"])
                with open(_path, "wb") as f:
                    f.write(file)
            else:
                raise NotImplementedError

            return _path

        # todo: make this more flexible by refactoring
        eval_func = eval_funcs[self.evaluator["func"]]
        eval_func_vars = {}

        for var_name, file_info in self.evaluator["paths"].items():
            path = copy_file_to_local(file_info)
            eval_func_vars[var_name] = path

        return eval_func(**eval_func_vars)

    def render(self, mode='rgb_array'):
        if mode == 'rgb_array':
            return self._get_obs()
        else:
            raise ValueError('Unsupported render mode: {}'.format(mode))

    def close(self):
        _execute_command(["vmrun", "stop", self.path_to_vm])
