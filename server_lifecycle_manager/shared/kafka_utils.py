"""
Kafka utility module for server output redirection
"""

import json
import logging
import threading
import time
from typing import Optional, Any, Dict, List
import subprocess

try:
    from kafka import KafkaProducer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False

# Default Kafka configuration
DEFAULT_KAFKA_BROKER = "10.1.37.28:9092"
DEFAULT_KAFKA_TOPIC_PREFIX = "server_logs"

class KafkaLogger:
    """
    A utility class to handle Kafka logging functionality
    for server output redirection.
    """

    def __init__(
        self,
        server_name: str,
        broker: str = DEFAULT_KAFKA_BROKER,
        topic_prefix: str = DEFAULT_KAFKA_TOPIC_PREFIX,
        logger: Optional[logging.Logger] = None
    ):
        self.server_name = server_name
        self.broker = broker
        self.topic = f"{topic_prefix}.{server_name.lower()}"
        self.logger = logger or logging.getLogger(f"KafkaLogger.{server_name}")
        self.producer = None
        self._initialize_producer()

    def _initialize_producer(self) -> bool:
        """Initialize the Kafka producer"""
        if not KAFKA_AVAILABLE:
            self.logger.warning("Kafka library not available. Install with 'pip install kafka-python'")
            return False

        try:
            self.producer = KafkaProducer(
                bootstrap_servers=self.broker,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            self.logger.info(f"Kafka producer initialized for topic {self.topic}")
            return True
        except Exception as e:
            self.logger.warning(f"Could not initialize Kafka producer: {e}")
            self.producer = None
            return False

    def send_log(self, message: str, level: str = "INFO",
                 metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Send a log message to Kafka"""
        if self.producer is None:
            return False

        try:
            data = {
                "timestamp": time.time(),
                "server": self.server_name,
                "level": level,
                "message": message
            }

            if metadata:
                data["metadata"] = metadata

            self.producer.send(self.topic, data)
            return True
        except Exception as e:
            self.logger.error(f"Failed to send log to Kafka: {e}")
            return False

    def close(self):
        """Close the Kafka producer"""
        if self.producer:
            self.producer.flush()
            self.producer.close()
            self.producer = None


class KafkaOutputRedirector:
    """
    Redirects process output (stdout/stderr) to Kafka topics
    """

    def __init__(
        self,
        server_name: str,
        process: subprocess.Popen,
        kafka_logger: KafkaLogger
    ):
        self.server_name = server_name
        self.process = process
        self.kafka_logger = kafka_logger
        self.logger = logging.getLogger(f"OutputRedirector.{server_name}")
        self.stdout_thread = None
        self.stderr_thread = None

    def start_redirection(self):
        """Start redirecting stdout and stderr to Kafka"""
        if self.process.stdout:
            self.stdout_thread = threading.Thread(
                target=self._redirect_stream,
                args=(self.process.stdout, "STDOUT"),
                daemon=True
            )
            self.stdout_thread.start()

        if self.process.stderr:
            self.stderr_thread = threading.Thread(
                target=self._redirect_stream,
                args=(self.process.stderr, "STDERR"),
                daemon=True
            )
            self.stderr_thread.start()

    def _redirect_stream(self, stream, stream_name):
        """Read from the stream and send to Kafka"""
        for line in iter(stream.readline, b''):
            try:
                message = line.decode('utf-8').strip()
                if message:
                    self.kafka_logger.send_log(
                        message=message,
                        level="INFO" if stream_name == "STDOUT" else "ERROR",
                        metadata={"stream": stream_name}
                    )
            except Exception as e:
                self.logger.error(f"Error processing {stream_name} output: {e}")

    def is_running(self):
        """Check if the process is still running"""
        return self.process.poll() is None

    def wait(self, timeout=None):
        """Wait for the process to complete"""
        return self.process.wait(timeout=timeout)
