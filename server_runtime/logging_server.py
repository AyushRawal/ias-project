import json
import logging
import os
import subprocess


class LoggingServer:
    def __init__(self, app_dir):
        self.server_name = self.__class__.__name__
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        self.logger = logging.getLogger(self.server_name)
        self.app_dir = app_dir
        self.config = self._load_config()

    def _load_config(self):
        cfg_path = os.path.join(self.app_dir, "descriptor.json")
        try:
            with open(cfg_path) as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Could not load descriptor: {e}")
            return {}

    def _setup_environment(self):
        self.logger.info(f"Setting up {self.server_name}")
        # env vars
        for k, v in self.config.get("environment", {}).items():
            os.environ[k] = v

        deps = self.config.get("dependencies", [])
        if deps:
            self.logger.info(f"Installing dependencies: {deps}")
            try:
                subprocess.run(
                    ["python", "-m", "venv", "env"], cwd=self.app_dir, check=True
                )
                subprocess.run(
                    ["env/bin/python", "-m", "pip", "install", "-q"] + deps,
                    cwd=self.app_dir,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Dependency install failed: {e}")
                return False

        return True

    def start(self):
        self.logger.info("Starting LoggingService")

        if not self._setup_environment():
            return -1

        # 1) init_module
        init_mod = self.config.get("init_module")
        if init_mod:
            pkg, fn = init_mod.split(":")
            cmd = ["env/bin/python", "-c", f"import {pkg}; {fn}()"]
            try:
                subprocess.run(cmd, cwd=self.app_dir, check=True)
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Init failed: {e}")
                return -1

        # 2) run the main app
        app_mod = self.config.get("app_module", "app:run")
        pkg, fn = app_mod.split(":")
        cmd = ["env/bin/python", "-u", "-c", f"import {pkg}; {fn}()"]
        self.logger.info(f"Launching consumer: {' '.join(cmd)}")
        proc = subprocess.Popen(cmd, cwd=self.app_dir)

        self.logger.info(f"LoggingService started, PID={proc.pid}")
        return proc.pid
