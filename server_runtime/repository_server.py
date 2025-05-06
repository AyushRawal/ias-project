import os
import json
import logging
import subprocess

class RepositoryServer:
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
        path = os.path.join(self.app_dir, "descriptor.json")
        try:
            return json.load(open(path))
        except Exception as e:
            self.logger.error(f"Could not load descriptor.json: {e}")
            return {}

    def _setup_env(self):
        self.logger.info(f"Setting up {self.server_name}")
        for k,v in self.config.get("environment", {}).items():
            os.environ[k] = v

        deps = self.config.get("dependencies", [])
        if deps:
            self.logger.info(f"Installing dependencies: {deps}")
            subprocess.run(["python","-m","venv","env"], cwd=self.app_dir, check=True)
            subprocess.run(
                ["env/bin/python","-m","pip","install","-q"] + deps,
                cwd=self.app_dir,
                check=True
            )
        return True

    def start(self):
        self.logger.info("Starting RepositoryServer")
        if not self._setup_env():
            return -1, 0

        # No init_module (our descriptor.json has it null), so skip.

        # Launch via Gunicorn
        port = self.config.get("port", 5002)
        appmod = self.config.get("app_module", "app:app")
        cmd = ["env/bin/gunicorn", "-b", f"0.0.0.0:{port}", appmod]
        self.logger.info(f"Executing: {' '.join(cmd)}")
        proc = subprocess.Popen(cmd, cwd=self.app_dir)
        self.logger.info(f"RepositoryServer started on port {port} (PID={proc.pid})")
        return proc.pid, port
