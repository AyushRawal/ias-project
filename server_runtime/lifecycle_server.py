import json
import logging
import os
import subprocess


class ServerLifeCycleServer:
    def __init__(self, app_dir):
        self.app_dir = app_dir
        self.config = self._load_config()
        self.server_name = self.__class__.__name__
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        self.logger = logging.getLogger(self.server_name)

    def _verify_app_directory(self):
        """Verify that the application directory exists and has required files"""
        if not os.path.exists(self.app_dir):
            self.logger.error(f"Application directory {self.app_dir} does not exist")
            return False
        return True

    def _setup_environment(self):
        """Set up environment variables and dependencies"""
        self.logger.info(f"Setting up environment for {self.server_name}")

        # Set environment variables from config
        for key, value in self.config.get("environment", {}).items():
            os.environ[key] = value

        # Install dependencies if specified
        dependencies = self.config.get("dependencies", [])
        if dependencies:
            self.logger.info(f"Installing dependencies: {', '.join(dependencies)}")
            try:
                subprocess.run(["python", "-m", "venv", "env"], cwd=self.app_dir)
                subprocess.run(
                    ["env/bin/python", "-m", "pip", "install", "-q"] + dependencies,
                    check=True,
                    cwd=self.app_dir,
                )
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Failed to install dependencies: {e}")
                return False

        return True

    def _load_config(self):
        """Load configuration from JSON file"""
        config_path = os.path.join(self.app_dir, "descriptor.json")
        try:
            with open(config_path, "r") as config_file:
                return json.load(config_file)
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            return {}

    def start(self):
        """Start the Lifecycle server"""
        self.logger.info("Starting Server Lifecycle Manager")

        if not self._verify_app_directory() or not self._setup_environment():
            return -1

        # Set up model path and server configuration
        app_module = self.config.get("main_module", "app.py")

        try:
            cmd = [
                "env/bin/python",
                app_module,
            ]

            # Start the server as a subprocess
            self.logger.info(f"Executing: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd, cwd=self.app_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            self.logger.info(f"Server Lifecycle Manager started")
            return proc.pid

        except Exception as e:
            self.logger.error(f"Failed to start Server Lifecycle Manager: {e}")
            return -1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the Server Lifecycle Manager.")
    parser.add_argument(
        "--app-dir", required=True, help="Path to the application directory"
    )
    args = parser.parse_args()

    server = ServerLifeCycleServer(
        app_dir=args.app_dir,
    )

    pid = server.start()
    if pid > 0:
        print(f"Server started with PID: {pid}")
    else:
        print("Failed to start server")
        exit(1)
