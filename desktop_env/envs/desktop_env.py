from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from typing import Callable, Any, Optional, Tuple
# import uuid
# import platform
from typing import List, Dict, Union

import gymnasium as gym

from desktop_env.controllers.python import PythonController
from desktop_env.controllers.setup import SetupController
# from desktop_env.evaluators import eval_funcs
from desktop_env.evaluators import metrics, getters

# import requests

logger = logging.getLogger("desktopenv.env")

Metric = Callable[[Any, Any], float]
Getter = Callable[[gym.Env, Dict[str, Any]], Any]


def _execute_command(command: List[str]) -> None:
    def _is_contained_in(a, b):
        for v in set(a):
            if a.count(v) > b.count(v):
                return False
        return True

    # Specially handled for the `vmrun` command in Windows
    if _is_contained_in(["vmrun", "-T", "ws", "start"], command):
        p = subprocess.Popen(command)
        p.wait()
    else:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, text=True,
                                encoding="utf-8")
        if result.returncode != 0:
            raise Exception("\033[91m" + result.stdout + result.stderr + "\033[0m")
        return result.stdout


class DesktopEnv(gym.Env):
    """
    DesktopEnv with OpenAI Gym interface.
    Fixme: refactor the logic when implementing the multi-process version
    """

    def __init__(
            self,
            path_to_vm: str,
            action_space: str = "computer_13",
            task_config: Dict[str, Any] = None,
            tmp_dir: str = "tmp",
            cache_dir: str = "cache",
            screen_size: Tuple[int] = (1920, 1080),
            headless: bool = False
    ):
        """
        Args:
            path_to_vm (str): path to .vmx file
            action_space (str): "computer_13" | "pyautogui"

            task_config (Dict[str, Any]): manages task configs integratedly,
              including
              * base snapshot
              * task id (uuid)
              * instruction
              * setup config
              * evaluator config

            tmp_dir (str): temporary directory to store trajectory stuffs like
              the extracted screenshots
            cache_dir (str): cache directory to cache task-related stuffs like
              reference file for evaluation
        """

        # Initialize environment variables
        self.path_to_vm = os.path.abspath(os.path.expandvars(os.path.expanduser(path_to_vm)))
        self.tmp_dir_base: str = tmp_dir
        self.cache_dir_base: str = cache_dir
        self.vm_screen_size = screen_size
        self.headless = headless

        os.makedirs(self.tmp_dir_base, exist_ok=True)

        # task-aware stuffs
        # todo: handling the logic of snapshot directory
        self._set_task_info(task_config)

        # Initialize emulator and controller
        logger.info("Initializing...")
        self._start_emulator()
        self.vm_ip = self._get_vm_ip()
        self.controller = PythonController(vm_ip=self.vm_ip)
        self.setup_controller = SetupController(vm_ip=self.vm_ip, cache_dir=self.cache_dir)

        # Meta info of the VM, move to the reset() function
        self.vm_platform: str = ""  # self.controller.get_vm_platform()

        # mode: human or machine
        assert action_space in ["computer_13", "pyautogui"]
        self.action_space = action_space
        # todo: define the action space and the observation space as gym did, or extend theirs

        # episodic stuffs, like tmp dir and counters, will be updated or reset
        # when calling self.reset()
        self.tmp_dir: str = self.tmp_dir_base  # just an init value, updated during reset
        self._traj_no: int = -1
        self._step_no: int = 0
        self.action_history: List[Dict[str, any]] = []

    def _start_emulator(self):
        while True:
            try:
                output = subprocess.check_output("vmrun -T ws list", shell=True, stderr=subprocess.STDOUT)
                output = output.decode()
                output: List[str] = output.splitlines()
                # if self.path_to_vm.lstrip("~/") in output:
                if self.path_to_vm in output:
                    logger.info("VM is running.")
                    break
                else:
                    logger.info("Starting VM...")
                    _execute_command(["vmrun", "-T", "ws", "start", self.path_to_vm]) if not self.headless \
                        else _execute_command(["vmrun", "-T", "ws", "start", self.path_to_vm, "nogui"])
                    time.sleep(3)
            except subprocess.CalledProcessError as e:
                logger.error(f"Error executing command: {e.output.decode().strip()}")

    def _get_vm_ip(self):
        max_retries = 20
        logger.info("Getting IP Address...")
        for _ in range(max_retries):
            try:
                output = _execute_command(["vmrun", "-T", "ws", "getGuestIPAddress", self.path_to_vm, "-wait"]).strip()
                logger.info(f"IP address: {output}")
                return output
            except Exception as e:
                print(e)
                time.sleep(5)
                logger.info("Retrying...")
        raise Exception("Failed to get VM IP address!")

    def _save_state(self):
        _execute_command(["vmrun", "-T", "ws" "snapshot", self.path_to_vm, self.snapshot_path])

    def _get_screenshot(self):
        # random_uuid = str(uuid.uuid4())
        # os.makedirs(os.path.join("tmp", random_uuid), exist_ok=True)
        # image_path = os.path.join("tmp", random_uuid, "screenshot.png")
        image_path: str = os.path.join(self.tmp_dir, "screenshots", "{:d}.png".format(self._step_no))

        # Get the screenshot and save to the image_path
        screenshot = self.controller.get_screenshot()
        with open(image_path, "wb") as f:
            f.write(screenshot)

        return image_path

    def _get_obs(self):
        screenshot_image_path = self._get_screenshot()
        return screenshot_image_path

    def _set_task_info(self, task_config: Dict[str, Any]):
        self.snapshot_path = task_config["snapshot"] # todo: save the snapshot when first start the environment, and then revert to it when reset
        self.task_id: str = task_config["id"]
        self.cache_dir: str = os.path.join(self.cache_dir_base, self.task_id)
        os.makedirs(self.cache_dir, exist_ok=True)
        self.instruction = task_config["instruction"]
        self.config = task_config["config"] if "config" in task_config else []

        # evaluator dict
        # func -> metric function string, or list of metric function strings
        # conj -> conjunction of multiple metrics if func is a list with length > 1, "and"/"or"
        # result -> result getter config, or list of result getter configs
        # expected (optional) -> expected getter config, or list of expected getter configs
        # options (optional) -> metric options, or list of metric options
        # if func is a str list, then result, expected (if exists), options (if exists) should also be lists of the same length
        # even if one of the metrics does not need expected or options field, it should be included in the list with None
        self.evaluator = task_config["evaluator"]
        self.metric: Metric = [getattr(metrics, func) for func in self.evaluator["func"]] \
            if isinstance(self.evaluator["func"], list) \
            else getattr(metrics, self.evaluator["func"])
        self.metric_conj: str = self.evaluator.get("conj", "and")  # take conjunction of multiple metrics
        if "result" in self.evaluator:
            self.result_getter: Getter = [getattr(getters, "get_{:}".format(res["type"])) for res in
                                          self.evaluator["result"]] \
                if isinstance(self.evaluator["result"], list) \
                else getattr(getters, "get_{:}".format(self.evaluator["result"]["type"]))
        else:
            self.result_getter = [None] * len(self.metric) \
                if isinstance(self.metric, list) \
                else None

        if "expected" in self.evaluator:
            self.expected_getter: Getter = [getattr(getters, "get_{:}".format(exp["type"])) if exp else None for exp in
                                            self.evaluator["expected"]] \
                if isinstance(self.evaluator["expected"], list) \
                else getattr(getters, "get_{:}".format(self.evaluator["expected"]["type"]))
        else:
            self.expected_getter = [None] * len(self.metric) \
                if isinstance(self.metric, list) \
                else None
        self.metric_options: Union[List[Dict[str, Any]], Dict[str, Any]] = [opt if opt else {} for opt in
                                                                            self.evaluator["options"]] \
            if isinstance(self.evaluator.get("options", {}), list) \
            else self.evaluator["options"] \
            if "options" in self.evaluator \
            else [{}] * len(self.metric) \
            if isinstance(self.metric, list) \
            else {}

        assert (not isinstance(self.evaluator["func"], list)
                or (len(self.metric) == len(self.result_getter) == len(self.expected_getter) == len(
                    self.metric_options)))

    def reset(self, task_config: Optional[Dict[str, Any]] = None, seed=None, options=None) -> Dict[str, Any]:
        logger.info("Resetting environment...")

        logger.info("Switching task...")
        if task_config is not None:
            self._set_task_info(task_config)
            self.setup_controller.reset_cache_dir(self.cache_dir)

        logger.info("Setting counters...")
        self._traj_no += 1
        self._step_no = 0
        self.action_history.clear()

        logger.info("Setup new temp dir...")
        self.tmp_dir = tempfile.mkdtemp(
            prefix="{:d}.{:}.".format(self._traj_no, self.task_id),
            dir=self.tmp_dir_base
        )
        os.makedirs(os.path.join(self.tmp_dir, "screenshots"))

        logger.info("Reverting to snapshot to {}...".format(self.snapshot_path))
        _execute_command(["vmrun", "-T", "ws", "revertToSnapshot", self.path_to_vm, self.snapshot_path])
        time.sleep(5)

        print(self.vm_screen_size)
        logger.info("Starting emulator...")
        self._start_emulator()
        logger.info("Emulator started.")

        logger.info("Get meta info of the VM...")
        self.vm_platform = self.controller.get_vm_platform()
        self.vm_screen_size = self.controller.get_vm_screen_size()
        print(self.vm_screen_size)

        logger.info("Setting up environment...")
        self.setup_controller.setup(self.config)

        time.sleep(5)
        logger.info("Environment setup complete.")

        observation = {
            "screenshot": self._get_obs(),
            "accessibility_tree": self.controller.get_accessibility_tree(),
        }
        return observation

    def step(self, action, pause=0.5):
        self._step_no += 1
        self.action_history.append(action)

        reward = 0  # todo: Define reward calculation for each example
        done = False  # todo: Define episode termination condition for each example
        info = {}

        # handle the special actions
        if action in ['WAIT', 'FAIL', 'DONE']:
            if action == 'WAIT':
                time.sleep(pause)
            elif action == 'FAIL':
                done = True
                info = {"fail": True}
            elif action == 'DONE':
                done = True
                info = {"done": True}

        # fixme: add reminding logic here, decide if the action is valid for the current action_space
        if self.action_space == "computer_13":
            # the set of all possible actions defined in the action representation
            self.controller.execute_action(action)
        elif self.action_space == "pyautogui":
            if action in ['WAIT', 'FAIL', 'DONE']:
                self.controller.execute_action(action)
            else:
                # the set of all possible python commands insides `pyautogui`
                self.controller.execute_python_command(action)

        observation = {
            "screenshot": self._get_obs(),
            "accessibility_tree": self.controller.get_accessibility_tree(),
            "terminal": self.controller.get_terminal_output(),
            "instruction": self.instruction
        }

        return observation, reward, done, info

    def evaluate(self):
        """
        Evaluate whether the task is successfully completed.
        """

        self.setup_controller.setup(self.evaluator.get("postconfig", []))

        if self.evaluator['func'] == "infeasible":
            if len(self.action_history) > 0 and self.action_history[-1] == "FAIL":
                return 1
            else:
                return 0
        else:
            if len(self.action_history) > 0 and self.action_history[-1] == "FAIL":
                return 0

        if type(self.metric) == list:
            results = []
            for idx, metric in enumerate(self.metric):
                try:
                    config = self.evaluator["result"][idx]
                    result_state = self.result_getter[idx](self, config)
                except FileNotFoundError:
                    logger.error("File not found!")
                    if self.metric_conj == 'and':
                        return 0

                expected = self.evaluator["expected"][idx]
                expected_state = self.expected_getter[idx](self, expected) if expected else None

                metric: int = metric(result_state, expected_state,
                                     **self.metric_options[idx]) if expected_state is not None \
                    else metric(result_state, **self.metric_options[idx])

                if self.metric_conj == 'and' and float(metric) == 0.0:
                    return 0
                elif self.metric_conj == 'or' and float(metric) == 1.0:
                    return 1
                else:
                    results.append(metric)
            return sum(results) / len(results) if self.metric_conj == 'and' else max(results)
        else:
            try:
                result_state = self.result_getter(self, self.evaluator["result"])
            except FileNotFoundError:
                logger.error("File not found!")
                return 0

            expected_state = self.expected_getter(self, self.evaluator["expected"]) if "expected" in self.evaluator \
                else None

            metric: float = self.metric(result_state, expected_state,
                                        **self.metric_options) if expected_state is not None \
                else self.metric(result_state, **self.metric_options)

        return metric

    def render(self, mode='rgb_array'):
        if mode == 'rgb_array':
            return self._get_obs()
        else:
            raise ValueError('Unsupported render mode: {}'.format(mode))

    def close(self):
        _execute_command(["vmrun", "stop", self.path_to_vm])
