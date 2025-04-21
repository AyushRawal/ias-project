import json
import os
import subprocess
import logging
from kafka_utils import KafkaLogger, KafkaOutputRedirector


class ServerLifeCycleServer:
    def __init__(self, app_dir, kafka_broker=None, kafka_topic_prefix=None):
        self.app_dir = app_dir
        self.config = self._load_config()
        self.server_name = self.__class__.__name__
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        self.logger = logging.getLogger(self.server_name)
        self.kafka_broker = kafka_broker
        self.kafka_topic_prefix = kafka_topic_prefix
        self.kafka_logger = None
        self.output_redirector = None

        # Initialize Kafka logger if broker is provided
        if self.kafka_broker:
            self.kafka_logger = KafkaLogger(
                server_name=self.server_name,
                broker=self.kafka_broker,
                topic_prefix=self.kafka_topic_prefix or "server_logs",
                logger=self.logger
            )

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
                subprocess.run(["env/bin/python", "-m", "pip", "install", "-q"] + dependencies, check=True, cwd=self.app_dir)
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
        """Start the inference API server"""
        self.logger.info("Starting Server Lifecycle Manager")

        if not self._verify_app_directory() or not self._setup_environment():
            return -1

        # Set up model path and server configuration
        api_module = self.config.get("api_module", "api:app")
        port = self.config.get("port", 8000)
        workers = self.config.get("workers", 1)

        try:
            cmd = [
                "env/bin/uvicorn",
                api_module,
                "--host",
                "0.0.0.0",
                "--port",
                str(port),
                "--workers",
                str(workers),
            ]

            # Start the server as a subprocess
            self.logger.info(f"Executing: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd, cwd=self.app_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            # Set up Kafka output redirection if Kafka logger is available
            if self.kafka_logger:
                self.output_redirector = KafkaOutputRedirector(
                    server_name=self.server_name,
                    process=proc,
                    kafka_logger=self.kafka_logger
                )
                self.output_redirector.start_redirection()
                self.logger.info("Process output being redirected to Kafka")

            self.logger.info(f"Server Lifecycle Manager started on port {port}")
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
    parser.add_argument(
        "--kafka-broker",
        default="10.1.37.28:9092",
        help="Kafka broker address for output redirection"
    )
    parser.add_argument(
        "--kafka-topic-prefix",
        default="server_logs",
        help="Prefix for Kafka topics"
    )
    parser.add_argument(
        "--no-kafka",
        action="store_true",
        help="Disable Kafka output redirection"
    )

    args = parser.parse_args()

    # Only use Kafka if not explicitly disabled
    kafka_broker = None if args.no_kafka else args.kafka_broker

    server = ServerLifeCycleServer(
        app_dir=args.app_dir,
        kafka_broker=kafka_broker,
        kafka_topic_prefix=args.kafka_topic_prefix,
    )

    pid = server.start()
    if pid > 0:
        print(f"Server started with PID: {pid}")
    else:
        print("Failed to start server")
        exit(1)
