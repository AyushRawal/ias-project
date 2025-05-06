import json
import logging
import os
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timezone

from confluent_kafka import Consumer
from kafka import KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError

# ——— Logging setup ————————————————————————————————————————
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("Registry")

kafka_producer = None

with open("descriptor.json", "r") as f:
    constants = json.load(f)


def stop_vm_func(data):
    if "vm_id" not in data:
        message = f"Invalid request, missing field: vm_id"
        make_log(message)
        return
    vm_id = data["vm_id"]
    vm_dir = os.path.join(os.getcwd(), "vms", vm_id)
    if os.path.exists(vm_dir):
        subprocess.run(["vagrant", "halt"], cwd=vm_dir, check=True)

        message = f"VM {vm_id} stopped successfully."
        make_log(message)
        message = {
            "method": "DELETE",
            "endpoint": f"/servers/{vm_id}",
        }

        # register vm
        send_message_through_kafka(
            constants["Kafka_Registry_Service_Topic"],
            message,
        )
    else:
        message = f"VM {vm_id} not found"
        make_log(message)


def start_vm_func(data):
    if "vm_id" not in data:
        message = f"Invalid request, missing field: vm_id"
        make_log(message)
        return
    vm_id = data["vm_id"]
    vm_dir = os.path.join(os.getcwd(), "vms", vm_id)
    if os.path.exists(vm_dir):
        subprocess.run(["vagrant", "up"], cwd=vm_dir, check=True)

        result = subprocess.run(
            ["vagrant", "ssh", "-c", "hostname -I"],
            cwd=vm_dir,
            capture_output=True,
            text=True,
        )

        ips = result.stdout.strip().split()
        ip = ips[1] if ips else None

        if ip:
            vm_agent_port = constants["VM_Agent_Port"]

            payload = {
                "id": vm_id,
                "ip_address": ip,
                "port": vm_agent_port,
            }
            message = {
                "method": "POST",
                "endpoint": "/register_server",
                "payload": payload,
            }

            # register vm
            send_message_through_kafka(
                constants["Kafka_Registry_Service_Topic"],
                message,
            )

            message_log = f"VM started at {ip}:{vm_agent_port}"
            logger.info(message_log)

            # log
            make_log(message_log)
        else:
            msg = "VM starting failed"
            make_log(msg)
            logger.error(msg)
    else:
        message = f"VM {vm_id} not found"
        make_log(message)


def destroy_vm_func(data):
    if "vm_id" not in data:
        message = f"Invalid request, missing field: vm_id"
        make_log(message)
        return
    vm_id = data["vm_id"]
    vm_dir = os.path.join(os.getcwd(), "vms", vm_id)
    if os.path.exists(vm_dir):
        subprocess.run(["vagrant", "halt"], cwd=vm_dir, check=True)
        subprocess.run(["vagrant", "destroy", "-f"], cwd=vm_dir, check=True)
        shutil.rmtree(vm_dir, ignore_errors=True)

        message = f"VM {vm_id} destroyed successfully."
        make_log(message)
        message = {
            "method": "DELETE",
            "endpoint": f"/servers/{vm_id}",
        }

        # register vm
        send_message_through_kafka(
            constants["Kafka_Registry_Service_Topic"],
            message,
        )
    else:
        message = f"VM {vm_id} not found"
        make_log(message)


def provision_vm_func(data):
    vm_uuid = str(uuid.uuid4())
    vm_dir = os.path.join(os.getcwd(), "vms", vm_uuid)

    # vm_dir = os.path.join(os.getcwd(), vm_dir)

    # os.makedirs(vm_dir, exist_ok=True)
    # shutil.copy("shared/agent.py", vm_dir)
    # shutil.copy("shared/Vagrantfile", vm_dir)
    shutil.copytree("shared", vm_dir)

    subprocess.run(["vagrant", "up"], cwd=vm_dir, check=True)

    result = subprocess.run(
        ["vagrant", "ssh", "-c", "hostname -I"],
        cwd=vm_dir,
        capture_output=True,
        text=True,
    )

    ips = result.stdout.strip().split()
    ip = ips[1] if ips else None

    if ip:
        vm_agent_port = constants["VM_Agent_Port"]

        payload = {
            "id": vm_uuid,
            "ip_address": ip,
            "port": vm_agent_port,
        }
        message = {"method": "POST", "endpoint": "/register_server", "payload": payload}

        # register vm
        send_message_through_kafka(
            constants["Kafka_Registry_Service_Topic"],
            message,
        )

        message_log = f"VM provisioned at {ip}:{vm_agent_port}"
        logger.info(message_log)

        # log
        make_log(message_log)
    else:
        msg = "VM provisioning failed"
        make_log(msg)
        logger.error(msg)


def init_kafka_producer(bootstrap_servers):
    global kafka_producer
    try:
        kafka_producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
    except Exception as e:
        kafka_producer = None
        logger.warning(f"Could not initialize Kafka producer: {e}")


def send_message_through_kafka(topic_name, message):
    if kafka_producer:
        try:
            kafka_producer.send(topic_name, message)
            kafka_producer.flush()
        except Exception as e:
            logger.error(f"Error sending message to Kafka: {e}")


def make_log(msg):
    payload = {
        "server": "lifecycle",
        "log": msg,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    send_message_through_kafka(constants["Kafka_Logs_Topic"], payload)


init_kafka_producer(constants["Kafka_Bootstrap_Server"])


def create_kafka_topics():
    bootstrap_servers = constants["Kafka_Bootstrap_Server"]
    topic_keys = [
        "Kafka_Provision_VM_Topic",
        "Kafka_Stop_VM_Topic",
        "Kafka_Destroy_VM_Topic",
        "Kafka_Start_VM_Topic",
    ]

    admin_client = KafkaAdminClient(bootstrap_servers=bootstrap_servers)

    try:
        existing_topics = admin_client.list_topics()

        topics_to_create = []
        for key in topic_keys:
            topic_name = constants[key]
            if topic_name not in existing_topics:
                topics_to_create.append(
                    NewTopic(name=topic_name, num_partitions=1, replication_factor=1)
                )
            else:
                logger.info(f"Topic '{topic_name}' already exists.")

        if topics_to_create:
            admin_client.create_topics(new_topics=topics_to_create, validate_only=False)
            for topic in topics_to_create:
                print(f"Topic '{topic.name}' created successfully.")
        else:
            logger.info("All topics already exist. No new topics were created.")

    finally:
        admin_client.close()


def listener(listener_name, func_name, bootstrap_server_ip, group_id, topic):
    conf = {
        "bootstrap.servers": bootstrap_server_ip,
        "group.id": group_id,
        "auto.offset.reset": "earliest",
    }

    consumer = Consumer(conf)
    consumer.subscribe([topic])

    logger.info(f"{listener_name} started...")

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error(f"{listener_name} error: {msg.error()}")
                continue

            raw_message = msg.value().decode("utf-8")
            logger.info(f"{listener_name} Received message: {raw_message}")
            data = json.loads(raw_message)

            threading.Thread(target=func_name, args=(data,)).start()

    except KeyboardInterrupt:
        logger.warning(f"{listener_name} interrupted by user...")
    finally:
        logger.info(f"Closing {listener_name}...")
        consumer.close()


if __name__ == "__main__":

    create_kafka_topics()

    listener_configs = [
        (
            "Service Deployer Listener",
            provision_vm_func,
            "Kafka_Provision_VM_Consumer_Group_Id",
            "Kafka_Provision_VM_Topic",
        ),
        (
            "Service Stopper Listener",
            stop_vm_func,
            "Kafka_Stop_VM_Consumer_Group_Id",
            "Kafka_Stop_VM_Topic",
        ),
        (
            "VM Destroyer Listener",
            destroy_vm_func,
            "Kafka_Destroy_VM_Consumer_Group_Id",
            "Kafka_Destroy_VM_Topic",
        ),
        (
            "VM Starter Listener",
            start_vm_func,
            "Kafka_Start_VM_Consumer_Group_Id",
            "Kafka_Start_VM_Topic",
        ),
    ]

    for name, func, group_id_key, topic_key in listener_configs:
        threading.Thread(
            target=listener,
            args=(
                name,
                func,
                constants["Kafka_Bootstrap_Server"],
                constants[group_id_key],
                constants[topic_key],
            ),
        ).start()
