import json
import logging
import os
import shutil
import subprocess

import requests

from flask import Flask, jsonify, request
from kafka import KafkaConsumer, KafkaProducer

from inference_server import InferenceAPIServer
from webapp_server import WebAppServer

# Setting up default paths and configuration
agent_deployment = "agent_deployment"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("agent")

kafka_producer = None

url_pid = {}

here = os.path.dirname(__file__)

with open(os.path.join(here, "descriptor.json"), "r") as f:
    constants = json.load(f)


NFS_LOCAL_DIR = "/home/vagrant/nfs"
HOME = os.environ["HOME"]
LOAD_BALANCER_URL = constants["load_balancer"]
REPOSITORY_URL = constants["repository"]


def mount_nfs():
    if not os.path.exists(NFS_LOCAL_DIR):
        os.system(f"sudo mkdir -p {NFS_LOCAL_DIR}")
    nfs_server_ip = constants["nfs_ip"]
    nfs_remote_path = constants["nfs_remote_path"]

    mount_cmd = (
        f"sudo mount -o nolock {nfs_server_ip}:{nfs_remote_path} {NFS_LOCAL_DIR}"
    )

    if os.system(mount_cmd) != 0:
        return "Error: Failed to mount NFS. Check NFS server IP and export path."

    return "NFS mounted Successfully!!!"


def umount_nfs():
    unmount_cmd = f"sudo umount {NFS_LOCAL_DIR}"
    if os.system(unmount_cmd) != 0:
        return f"Warning: Files copied, but failed to unmount {NFS_LOCAL_DIR}."


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


init_kafka_producer(constants["Kafka_Bootstrap_Server"])


def send_message_through_kafka(topic_name, message):
    if kafka_producer:
        try:
            kafka_producer.send(topic_name, message)
            kafka_producer.flush()
        except Exception as e:
            logger.error(f"Error sending message to Kafka: {e}")


def run_inference_server(
    name,
    version,
    my_ip,
):
    """Run an inference server for the given model"""
    logger.info(f"Starting inference server for {name} - {version}")
    mount_nfs()

    # Copy files from NFS share to local directories
    # repo = os.path.join(NFS_LOCAL_DIR, "repository", "versioned_models")


    data = requests.get(f"{REPOSITORY_URL}/versions/{name}/{version}")
    if data.status_code != 200:
        print(f"Failed querying repository. Response status code: {data.status_code}")
        raise Exception

    data = data.json()
    app_nfs_path = data["release_path"]
    model_nfs_path = data["model_path"]
    app_nfs_path = app_nfs_path.replace("/home/orion/data/ias_nfs", NFS_LOCAL_DIR)
    model_nfs_path = model_nfs_path.replace("/home/orion/data/ias_nfs", NFS_LOCAL_DIR)

    app_nfs_path = os.path.join(app_nfs_path, "inference")
    model_nfs_path = os.path.join(model_nfs_path, "model.pt")

    # app_nfs_path = "/home/vagrant/nfs/repository/versioned_models/my_app/release/v1.0/inference"
    # model_nfs_path = "/home/vagrant/nfs/repository/versioned_models/my_app/models/model.pt"

    # app_nfs_path = os.path.join(repo, name, "inference")
    # model_nfs_path = os.path.join(repo, name, "model.pt")

    dest = os.path.join(HOME, name + "_" + version + "_inference")
    model_path = os.path.join(dest, "model.pt")

    if os.path.exists(dest):
        print(dest, " already exists, skipping copy")
    else:
        shutil.copytree(app_nfs_path, dest)

    shutil.copy(model_nfs_path, model_path)

    umount_nfs()

    server = InferenceAPIServer(dest, model_path)
    pid, port = server.start()

    if pid < 0:
        logger.info(f"could not start inference server")
        raise Exception


    url_pid[my_ip + ":" + str(port)] = pid

    payload = {
        "name": name,
        "version": version,
        "process_id": pid,
        "type": "inference",
        "port": port,
        "ip_address": my_ip,
    }
    message = {
        "method": "POST",
        "endpoint": f"/register_application",
        "payload": payload,
    }

    # register vm
    send_message_through_kafka(
        constants["Kafka_Registry_Service_Topic"],
        message,
    )
    logger.info(f"inference started at {my_ip}:{port}")
    return pid


def run_webapp_server(name, version, my_ip):
    """Run a webapp server for the given application"""
    logger.info(f"Starting webapp server for {name}")
    mount_nfs()

    data = requests.get(f"{REPOSITORY_URL}/versions/{name}/{version}")
    if data.status_code != 200:
        print(f"Failed querying repository. Response status code: {data.status_code}")
        raise Exception

    data = data.json()
    app_nfs_path = data["release_path"]
    # model_nfs_path = data["model_path"]
    app_nfs_path = app_nfs_path.replace("/home/orion/data/ias_nfs", NFS_LOCAL_DIR)
    # model_nfs_path = model_nfs_path.replace("/home/orion/data/ias_nfs", NFS_LOCAL_DIR)

    app_nfs_path = os.path.join(app_nfs_path, "web_app")
    # model_nfs_path = os.path.join(model_nfs_path, "model.pt")
    # Copy files from NFS share to local directories
    # repo = os.path.join(NFS_LOCAL_DIR, "repository", "versioned_models")
    # app_nfs_path = os.path.join(repo, name, "webapp")

    # app_nfs_path = "/home/vagrant/nfs/repository/versioned_models/my_app/release/v1.0/web_app"

    dest = os.path.join(HOME, name + "_" + version + "_webapp")

    if os.path.exists(dest):
        print(dest, " already exists, skipping copy")
    else:
        shutil.copytree(app_nfs_path, dest)

    inference_url = f"{LOAD_BALANCER_URL}/{name}/{version}/inference"
    # inference_url = f"{my_ip}:5005"
    logger.info(f"Inference url: {inference_url}")
    server = WebAppServer(dest, inference_url)
    pid, port = server.start()

    if pid < 0:
        logger.info(f"could not start webapp server")
        raise Exception

    url_pid[my_ip + ":" + str(port)] = pid

    payload = {
        "name": name,
        "version": version,
        "process_id": pid,
        "type": "webapp",
        "port": port,
        "ip_address": my_ip,
    }
    message = {
        "method": "POST",
        "endpoint": f"/register_application",
        "payload": payload,
    }

    # register vm
    send_message_through_kafka(
        constants["Kafka_Registry_Service_Topic"],
        message,
    )
    logger.info(f"Webapp started at {my_ip}:{port}")
    return pid


def stop_service(my_ip, port):
    """Stop a running service by its process ID"""
    if not url_pid[my_ip + ":" + port]:
        logger.warning("no running application found")
    pid = url_pid[my_ip + ":" + str(port)]
    cmd = ["sudo", "kill", "-9", str(pid)]
    try:
        subprocess.run(cmd, check=True)
        logger.info(f"Process with pid {pid} successfully stopped")
        return True
    except subprocess.CalledProcessError:
        logger.error(f"Could not find process with pid {pid}")
        return False


app = Flask(__name__)


@app.route("/run_server", methods=["POST"])
def api_run_inference_server():
    try:
        data = request.get_json()
        name = data.get("name")
        version = data.get("version")
        my_ip = data.get("ip")
        server_type = data.get("type")
    except Exception as e:
        return jsonify({"error": f"Invalid request: {str(e)}"}), 400

    if not all([name, version, my_ip]):
        return jsonify({"error": "Missing required parameters", "data": data}), 400

    if server_type == "inference":
        try:
            pid = run_inference_server(name, version, my_ip)
            return (
                jsonify(
                    {"message": "Inference server started successfully", "pid": pid}
                ),
                200,
            )
        except Exception as e:
            logger.error(f"Error starting inference server: {e}")
            return (
                jsonify({"error": f"Failed to start inference server: {str(e)}"}),
                500,
            )
    elif server_type == "webapp":
        try:
            pid = run_webapp_server(name, version, my_ip)
            return (
                jsonify({"message": "webapp server started successfully", "pid": pid}),
                200,
            )
        except Exception as e:
            logger.error(f"Error starting webapp server: {e}")
            return jsonify({"error": f"Failed to start webapp server: {str(e)}"}), 500


@app.route("/stop_service", methods=["POST"])
def api_stop_service():
    try:
        data = request.get_json()
        ip = data.get("ip")
        port = data.get("port")

        if not ip or not port:
            return jsonify({"error": "Missing required parameter: ip or port"}), 400

        success = stop_service(ip, port)
        if success:
            return (
                jsonify({"message": f"Service at {ip}:{port} stopped successfully"}),
                200,
            )
        else:
            return jsonify({"error": f"Failed to stop service at {ip}:{port}"}), 404
    except Exception as e:
        logger.error(f"Error stopping service: {e}")
        return jsonify({"error": f"Failed to stop service: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
