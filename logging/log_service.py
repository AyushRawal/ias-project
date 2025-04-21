import os
import time
import json
import logging
from datetime import datetime
from kafka import KafkaConsumer

# Configure logging for our application.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Kafka configuration: Using the Kafka broker at 10.1.37.28:9092.
KAFKA_BROKERS = ['10.1.37.28:9092']
KAFKA_TOPIC = 'logs'         # Replace with your Kafka topic name.
KAFKA_GROUP = 'log_consumer_group' # Replace with your consumer group ID.

# NFS Directory where logs will be stored.
NFS_DIRECTORY = '/Users/priyanshusharma/Desktop/logs/'

def ensure_directory(directory_path: str):
    """
    Ensure that the given directory exists.
    Create it (and any intermediate directories) if it does not exist.
    """
    if not os.path.exists(directory_path):
        try:
            os.makedirs(directory_path, exist_ok=True)
            logger.info(f"Created directory: {directory_path}")
        except Exception as e:
            logger.exception(f"Failed to create directory {directory_path}: {e}")
            raise

def get_log_file_path(server: str) -> str:
    # try:
    #     # Try to parse the timestamp provided in the log message.
    #     # dt = datetime.fromisoformat(log_timestamp)
    # except Exception as parse_error:
    #     # If parsing fails, fall back to the current date.
    #     # logger.error(f"Invalid timestamp format '{log_timestamp}', using current date instead.")
    #     dt = datetime.now()

    # date_str = dt.strftime("%Y-%m-%d")

    file_name = f"{server}.log"
    return os.path.join(NFS_DIRECTORY, file_name)

def consume_and_store_logs():
    """
    Consume logs from Kafka, then store each log in a file.
    Files are uniquely named based on the 'server' field and the date part of the log's timestamp.
    """
    # Ensure that the main NFS directory is present.
    ensure_directory(NFS_DIRECTORY)

    # Create a Kafka consumer.
    consumer = KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BROKERS,
        group_id=KAFKA_GROUP,
        auto_offset_reset='earliest',  # Read from the beginning if no previous offset is committed.
        enable_auto_commit=True,       # Let Kafka handle committing offsets automatically.
        consumer_timeout_ms=1000       # Timeout period in milliseconds when polling for messages.
    )
    logger.info("Started Kafka consumer...")

    try:
        while True:
            for message in consumer:
                try:
                    # Decode the message as JSON. The message should contain at least 'server', 'log', and 'timestamp'.
                    msg_data = json.loads(message.value.decode('utf-8'))
                except Exception as decode_error:
                    logger.error(f"Failed to decode or parse message: {decode_error}")
                    continue

                server = msg_data.get("server")
                log_message = msg_data.get("log")
                log_timestamp = msg_data.get("timestamp")

                # Ensure all required fields are present.
                if not all([server, log_message, log_timestamp]):
                    logger.error(f"Message missing required fields: {msg_data}")
                    continue

                # Build the file path from the server name and timestamp.
                log_file_path = get_log_file_path(server)

                # If the file (or its parent directory) is not present, create the NFS_DIRECTORY.
                # (The file will be created automatically when opened in append mode.)
                try:
                    with open(log_file_path, "a", encoding="utf-8") as log_file:
                        # Append the log message to the file.
                        # You can adjust the log format as needed.
                        log_file.write(f"{log_timestamp}-----{log_message}\n")
                    logger.info(f"Appended log entry for server '{server}' to {log_file_path}")
                except Exception as file_error:
                    logger.exception(f"Error writing to file {log_file_path}: {file_error}")

            # Pause briefly before checking for new messages.
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Consumer interrupted by user. Shutting down...")

    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")

    finally:
        consumer.close()
        logger.info("Kafka consumer closed.")

if __name__ == "__main__":
    consume_and_store_logs()
