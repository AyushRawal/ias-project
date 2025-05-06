import argparse
import json
import logging
import os
import socket

# from kafka import KafkaProducer

from server_runtime.lifecycle_server import ServerLifeCycleServer
from server_runtime.load_balancer_server import LoadBalancerServer
from server_runtime.logging_server import LoggingServer
from server_runtime.registry_server import RegistryServer
from server_runtime.repository_server import RepositoryServer

# constants = {
#     "Kafka_Bootstrap_Server": "10.1.37.28:9092",
#     "Kafka_Registry_Service_Topic": "Registry_Service",
# }
#
# my_ip = socket.gethostbyname(socket.gethostname())
#
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
# )
# logger = logging.getLogger("bootstrap")
#
#
# def init_kafka_producer(bootstrap_servers):
#     global kafka_producer
#     try:
#         kafka_producer = KafkaProducer(
#             bootstrap_servers=bootstrap_servers,
#             value_serializer=lambda v: json.dumps(v).encode("utf-8"),
#         )
#     except Exception as e:
#         kafka_producer = None
#         logger.warning(f"Could not initialize Kafka producer: {e}")
#
#
# init_kafka_producer(constants["Kafka_Bootstrap_Server"])
#
#
# def send_message_through_kafka(topic_name, message):
#     if kafka_producer:
#         try:
#             kafka_producer.send(topic_name, message)
#             kafka_producer.flush()
#         except Exception as e:
#             logger.error(f"Error sending message to Kafka: {e}")


def start_server(server_type, base_path):
    """Starts the specified server type."""
    pid = None
    if server_type == "registry":
        server = RegistryServer(os.path.join(base_path, "registry"))
        pid = server.start()
        print(f"Registry Server started with PID: {pid}")
    elif server_type == "repository":
        server = RepositoryServer(os.path.join(base_path, "repository"))
        pid, port = server.start()
        print(f"Repository Server started with PID: {pid}")
        # payload = {
        #     "name": "repository",
        #     "version": 0,
        #     "process_id": pid,
        #     "type": "inference",
        #     "port": port,
        #     "ip_address": my_ip,
        # }
        # message = {
        #     "method": "POST",
        #     "endpoint": f"/register_application/",
        #     "payload": payload,
        # }
        #
        # # register vm
        # send_message_through_kafka(
        #     constants["Kafka_Registry_Service_Topic"],
        #     message,
        # )
    elif server_type == "lifecycle":
        server = ServerLifeCycleServer(
            os.path.join(base_path, "server_lifecycle_manager")
        )
        pid = server.start()
        print(f"Server LifeCycle Server started with PID: {pid}")
    elif server_type == "logging":
        server = LoggingServer(os.path.join(base_path, "logging"))
        pid = server.start()
        print(f"Logging Server started with PID: {pid}")
    elif server_type == "loadbalancer":
        server = LoadBalancerServer(os.path.join(base_path, "load_balancer"))
        pid = server.start()
        print(f"Load Balancer Server started with PID: {pid}")
    else:
        print(f"Unknown server type: {server_type}")
    return pid


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start one or more runtime servers.")
    parser.add_argument(
        "servers",
        nargs="+",
        choices=["registry", "repository", "lifecycle", "logging", "loadbalancer"],
        help="Specify one or more servers to run ('registry', 'repository', 'lifecycle', 'logging', 'loadbalancer')",
    )
    parser.add_argument(
        "--base_path",
        default=".",
        help="Base directory for server data (default: '.')",
    )

    args = parser.parse_args()

    base_path = args.base_path

    for server_name in args.servers:
        pid = start_server(server_name, base_path)
