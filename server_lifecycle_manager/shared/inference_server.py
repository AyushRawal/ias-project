import json
import logging
import os
import subprocess

# from kafka_utils import KafkaLogger, KafkaOutputRedirector


class InferenceAPIServer:
    def __init__(
        self,
        app_dir,
        model_path,
        workers=1,
    ):
        self.app_dir = app_dir
        self.config = self._load_config()
        self.server_name = self.__class__.__name__
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        self.logger = logging.getLogger(self.server_name)
        self.model_path = model_path
        self.port = 0
        self.workers = workers
        # self.kafka_broker = kafka_broker
        # self.kafka_topic_prefix = "logs"
        # self.kafka_logger = None
        # self.output_redirector = None

        # Initialize Kafka logger if broker is provided
        # if self.kafka_broker:
        #     self.kafka_logger = KafkaLogger(
        #         server_name=self.server_name,
        #         broker=self.kafka_broker,
        #         topic_prefix=self.kafka_topic_prefix or "server_logs",
        #         logger=self.logger,
        #     )

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
        api_module = self.config.get("api_module", "api:app")
        if "fastapi" in api_module.lower():
            dependencies.append("uvicorn")
        else:
            dependencies.append("gunicorn")
        if dependencies:
            self.logger.info(f"Installing dependencies: {', '.join(dependencies)}")
            try:
                subprocess.run(
                    ["python3", "-m", "venv", "env"], cwd=self.app_dir, check=True
                )
                subprocess.run(
                    ["env/bin/pip", "--no-cache-dir", "install", "-q"] + dependencies,
                    cwd=self.app_dir,
                    check=True,
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

    def _get_actual_port(self, stdout):
        """Retrieve the actual port from the server's stdout."""
        for line in iter(stdout.readline, b""):
            decoded_line = line.decode("utf-8").strip()
            if "Uvicorn running on" in decoded_line or "Listening at" in decoded_line:
                # Extract the port from the log line
                return int(decoded_line.split(":")[-1].split("/")[0])
        return None

    def start(self):
        """Start the inference API server"""
        self.logger.info("Starting Inference API Server")

        if not self._verify_app_directory() or not self._setup_environment():
            return -1, 0

        # Set up model path and server configuration
        api_module = self.config.get("api_module", "api:app")

        try:
            # Export model path as environment variable for the API
            os.environ["MODEL_PATH"] = self.model_path

            # Start the API server with gunicorn for production or uvicorn for FastAPI
            if "fastapi" in api_module.lower():
                cmd = [
                    "env/bin/uvicorn",
                    api_module,
                    "--host",
                    "0.0.0.0",
                    "--port",
                    str(self.port),
                    "--workers",
                    str(self.workers),
                ]
            else:
                cmd = [
                    "env/bin/gunicorn",
                    "-b",
                    f"0.0.0.0:{self.port}",
                    "-w",
                    str(self.workers),
                    api_module,
                ]

            # Start the server as a subprocess
            self.logger.info(f"Executing: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd, cwd=self.app_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            self.port = self._get_actual_port(proc.stdout)

            # Set up Kafka output redirection if Kafka logger is available
            # if self.kafka_logger:
            #     self.output_redirector = KafkaOutputRedirector(
            #         server_name=self.server_name,
            #         process=proc,
            #         kafka_logger=self.kafka_logger,
            #     )
            #     self.output_redirector.start_redirection()
            #     self.logger.info("Process output being redirected to Kafka")

            self.logger.info(f"Inference API Server started on port {self.port}")
            return proc.pid, self.port

        except Exception as e:
            self.logger.error(f"Failed to start Inference API Server: {e}")
            return -1, 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the Inference API Server.")
    parser.add_argument(
        "--app-dir", required=True, help="Path to the application directory"
    )
    parser.add_argument(
        "--workers", type=int, default=1, help="Number of worker processes"
    )
    args = parser.parse_args()

    # Only use Kafka if not explicitly disabled
    kafka_broker = None if args.no_kafka else args.kafka_broker

    server = InferenceAPIServer(
        app_dir=args.app_dir,
        model_path=args.model_path,
        workers=args.workers,
    )

    pid, port = server.start()
    if pid > 0:
        print(f"Server started with PID: {pid}")
    else:
        print("Failed to start server")
        exit(1)
