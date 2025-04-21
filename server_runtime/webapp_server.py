import json
import logging
import os
import subprocess
from urllib.parse import urljoin
from kafka_utils import KafkaLogger, KafkaOutputRedirector


class WebAppServer:
    def __init__(self, app_dir, port, inference_url, kafka_broker=None, kafka_topic_prefix=None):
        self.app_dir = app_dir
        self.config = self._load_config()
        self.server_name = self.__class__.__name__
        self.inference_url = inference_url
        self.port = port
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

    def _verify_inference_api(self):
        """Verify that the inference API is reachable and functional"""
        import requests

        try:
            import urllib.parse
            response = requests.get(f"{urllib.parse.urljoin(self.inference_url, 'status')}", timeout=5)
            if response.status_code == 200:
                self.logger.info("Inference API is reachable and functional")
                return True
            else:
                self.logger.error(
                    f"Inference API returned status code {response.status_code}"
                )
                return False
        except requests.RequestException as e:
            self.logger.error(f"Failed to verify Inference API: {e}")
            return False

    def _setup_environment(self):
        """Set up environment variables and dependencies"""
        self.logger.info(f"Setting up environment for {self.server_name}")

        # Set environment variables from config
        for key, value in self.config.get("environment", {}).items():
            os.environ[key] = value

        os.environ["INFERENCE_API_URL"] = self.inference_url

        # Install dependencies if specified
        dependencies = self.config.get("dependencies", [])
        web_server = self.config.get("web_server", "flask")
        if web_server.lower() ==  "flask":
            dependencies.append("gunicorn")
        elif web_server.lower()  == "streamlit":
            dependencies.append("streamlit")
        else:
            self.logger.error("Unsupported web server type")
            return False
        if dependencies:
            self.logger.info(f"Installing dependencies: {', '.join(dependencies)}")
            try:
                subprocess.run(["python3", "-m", "venv", "env"], check=True, cwd=self.app_dir)
                subprocess.run(["env/bin/pip", "install", "-q"] + dependencies, check=True, cwd=self.app_dir)
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
        """Start the web application server"""
        self.logger.info("Starting Web Application Server")

        if (
            not self._verify_app_directory()
            or not self._setup_environment()
            or not self._verify_inference_api()
        ):
            return -1

        # Load web app configuration
        # Determine web server type (defaults to Flask)
        web_server = self.config.get("web_server", "flask")

        try:

            os.environ["API_URL"] = self.inference_url

            if web_server.lower() == "flask":
                app_module = self.config.get("app_module", "app:app")
                cmd = ["env/bin/gunicorn", "-b", f"0.0.0.0:{self.port}", app_module]

                # Start the server as a subprocess
                self.logger.info(f"Executing: {' '.join(cmd)}")
                proc = subprocess.Popen(
                    cmd,
                    cwd=self.app_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
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

                self.logger.info(f"Web Application Server started on port {self.port}")
                return proc.pid

            elif web_server.lower() == "streamlit":
                app_file = self.config.get("app_file", "app.py")
                app_path = os.path.join(self.app_dir, app_file)
                cmd = ["env/bin/streamlit", "run", app_path, "--server.port", str(self.port)]

                # Start the server as a subprocess
                self.logger.info(f"Executing: {' '.join(cmd)}")
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.app_dir
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

                self.logger.info(
                    f"Streamlit Web Application Server started on port {self.port}"
                )
                return proc.pid

            else:
                self.logger.error(f"Unsupported web server type: {web_server}")
                return -1

        except Exception as e:
            self.logger.error(f"Failed to start Web Application Server: {e}")
            return -1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the WebAppServer.")
    parser.add_argument(
        "--app-dir", required=True, help="Path to the application directory"
    )
    parser.add_argument(
        "--port", type=int, required=True, help="Port to run the server on"
    )
    parser.add_argument(
        "--inference-url", required=True, help="URL of the inference API"
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

    server = WebAppServer(
        app_dir=args.app_dir,
        port=args.port,
        inference_url=args.inference_url,
        kafka_broker=kafka_broker,
        kafka_topic_prefix=args.kafka_topic_prefix
    )

    pid = server.start()
    if pid > 0:
        print(f"Server started with PID: {pid}")
    else:
        print("Failed to start server")
        exit(1)
