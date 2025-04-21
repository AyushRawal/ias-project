import json
import logging
import os
import time
from datetime import datetime

from kafka import KafkaConsumer

# Configure python‐logging for this process
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("LogService")

HERE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(HERE, "descriptor.json")

try:
    with open(CONFIG_PATH, "r") as cfg:
        CONFIG = json.load(cfg)
except Exception as e:
    logger.error(f"Failed to load config {CONFIG_PATH}: {e}")
    CONFIG = {}

# Kafka configuration
KAFKA_BROKERS = CONFIG.get("kafka_brokers", ["10.1.37.28:9092"])
KAFKA_TOPIC = CONFIG.get("kafka_topic", "logs")
KAFKA_GROUP = CONFIG.get("kafka_group", "log_consumer_group")

# Where to store files
NFS_DIRECTORY = CONFIG.get("nfs_directory", "/home/orion/data/ias_nfs") + "/logs"


def init_consumer():
    """One‐time setup before starting the loop."""
    # create NFS_DIRECTORY if needed
    if not os.path.exists(NFS_DIRECTORY):
        os.makedirs(NFS_DIRECTORY, exist_ok=True)
        logger.info(f"Created NFS directory {NFS_DIRECTORY}")


def run():
    """Start consuming logs indefinitely."""
    consumer = KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BROKERS,
        group_id=KAFKA_GROUP,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        consumer_timeout_ms=1000,
    )
    logger.info("Kafka consumer started")

    try:
        while True:
            for msg in consumer:
                try:
                    data = json.loads(msg.value.decode())
                    server = data["server"]
                    ts = data["timestamp"]
                    text = data["log"]
                except Exception as e:
                    logger.error(f"Bad message: {e}")
                    continue

                path = os.path.join(NFS_DIRECTORY, f"{server}.log")
                try:
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(f"{ts} ----- {text}\n")
                    logger.info(f"Wrote log for {server}")
                except Exception as e:
                    logger.error(f"Failed writing to {path}: {e}")

            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down consumer")
    finally:
        consumer.close()
        logger.info("Consumer closed")


if __name__ == "__main__":
    init_consumer()
    run()
