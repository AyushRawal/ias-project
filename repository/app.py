# repository/app.py

import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import zipfile
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from kafka import KafkaConsumer, KafkaProducer

# ——— Load configuration ——————————————————————————————————————
HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "descriptor.json"), "r") as cfg_file:
    CONFIG = json.load(cfg_file)

PORT = CONFIG.get("port", 5002)
KAFKA_BROKER = CONFIG.get("kafka_broker", "10.1.37.28:9092")
LOG_TOPIC = CONFIG.get("kafka_log_topic", "logs")
CMD_TOPIC = CONFIG.get("kafka_cmd_topic", "repository_commands")
VERSIONED_ROOT = CONFIG.get("nfs_path", HERE)
VERSIONED_ROOT = os.path.join(VERSIONED_ROOT, "..", "versioned_models")
# ——— Logging setup ————————————————————————————————————————
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("Repository")

# ——— Kafka producer initialization ———————————————————————————
kafka_producer = None
try:
    kafka_producer = KafkaProducer(
        bootstrap_servers=[KAFKA_BROKER],
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
    logger.info("Kafka producer initialized.")
except Exception as e:
    logger.warning(f"Could not initialize Kafka producer: {e}")


def make_log(server: str, msg: str):
    """Emit structured log to Kafka (and stdout)."""
    payload = {
        "server": server,
        "log": msg,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if kafka_producer:
        try:
            kafka_producer.send(LOG_TOPIC, payload)
            kafka_producer.flush()
        except Exception as e:
            logger.error(f"Failed to send Kafka log: {e}")
    logger.info(msg)


# ——— Versioning helpers —————————————————————————————————————
def get_next_version(app_name: str) -> str:
    release_dir = os.path.join(VERSIONED_ROOT, app_name, "release")
    if not os.path.isdir(release_dir):
        return "v1.0"
    versions = []
    for d in os.listdir(release_dir):
        if d.startswith("v"):
            try:
                num = int(d[1:].split(".")[0])
                versions.append(num)
            except:
                pass
    if not versions:
        return "v1.0"
    return f"v{max(versions)+1}.0"


# ——— Core logic ——————————————————————————————————————————
def process_tag_release_logic(app_name: str, file_bytes: bytes, filename: str):
    if not app_name or not file_bytes or not filename:
        err = "Missing required parameters: app, file and filename."
        make_log("repository", err)
        return {"error": err}, 400

    app_name = app_name.lower()
    tag = get_next_version(app_name)
    full_tag = f"{app_name}_{tag}"
    make_log("repository", f"Tagging release {full_tag}")

    # prepare temp dirs
    tmp_zip = tempfile.mkdtemp()
    tmp_ext = tempfile.mkdtemp()
    try:
        zip_path = os.path.join(tmp_zip, filename)
        with open(zip_path, "wb") as f:
            f.write(file_bytes)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(tmp_ext)
    except zipfile.BadZipFile:
        err = "Uploaded file is not a valid zip"
        make_log("repository", err)
        shutil.rmtree(tmp_zip)
        shutil.rmtree(tmp_ext)
        return {"error": err}, 400

    # validate structure
    for sub in ("inference", "web_app"):
        if not os.path.isdir(os.path.join(tmp_ext, sub)):
            err = f"Missing directory '{sub}'"
            make_log("repository", err)
            shutil.rmtree(tmp_zip)
            shutil.rmtree(tmp_ext)
            return {"error": err}, 400

    # find model file
    inf_dir = os.path.join(tmp_ext, "inference")
    model_file = next(
        (f for f in os.listdir(inf_dir) if f.endswith((".pt", ".pth"))), None
    )
    if not model_file:
        err = "No PyTorch model file found"
        make_log("repository", err)
        shutil.rmtree(tmp_zip)
        shutil.rmtree(tmp_ext)
        return {"error": err}, 400

    # organize versioned directories
    app_root = os.path.join(VERSIONED_ROOT, app_name)
    release_dir = os.path.join(app_root, "release", tag)
    models_dir = os.path.join(app_root, "models")
    os.makedirs(release_dir, exist_ok=True)
    os.makedirs(models_dir, exist_ok=True)

    try:
        for sub in ("inference", "web_app"):
            shutil.move(os.path.join(tmp_ext, sub), os.path.join(release_dir, sub))
        # move model into models_dir
        shutil.move(
            os.path.join(release_dir, "inference", model_file),
            os.path.join(models_dir, model_file),
        )
    except Exception as e:
        err = f"Filesystem error: {e}"
        make_log("repository", err)
        shutil.rmtree(tmp_zip)
        shutil.rmtree(tmp_ext)
        return {"error": err}, 500

    shutil.rmtree(tmp_zip)
    shutil.rmtree(tmp_ext)

    # init git + lfs
    if not os.path.isdir(os.path.join(app_root, ".git")):
        subprocess.run(["git", "init", app_root], check=False)
    subprocess.run(["git", "lfs", "install"], check=False, cwd=app_root)
    subprocess.run(
        ["git", "lfs", "track", f"models/{model_file}"], check=False, cwd=app_root
    )
    subprocess.run(["git", "add", "."], cwd=app_root)
    subprocess.run(["git", "commit", "-m", full_tag], cwd=app_root)
    subprocess.run(["git", "tag", full_tag], cwd=app_root)
    make_log("repository", f"Git tag {full_tag} created")

    return {"message": f"Release {full_tag} created"}, 200


def get_version_paths_logic(app_name: str, version: str):
    tag = f"{app_name}_{version}"
    base = os.path.join(VERSIONED_ROOT, app_name)
    if not os.path.isdir(base):
        err = f"App '{app_name}' not found"
        make_log("repository", err)
        return {"error": err}, 404
    # verify tag exists
    try:
        subprocess.run(
            ["git", "rev-parse", "--verify", tag],
            cwd=base,
            check=True,
            stdout=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        err = f"Tag '{tag}' not found"
        make_log("repository", err)
        return {"error": err}, 404

    return {
        "app": app_name,
        "version": version,
        "model_path": f"{VERSIONED_ROOT}/{app_name}/models",
        "release_path": f"{VERSIONED_ROOT}/{app_name}/release/{version}",
    }, 200


# ——— Flask endpoints —————————————————————————————————————
app = Flask(__name__)


@app.route("/tag_release", methods=["POST"])
def tag_release():
    app_name = request.form.get("app")
    f = request.files.get("file")
    if not app_name or not f:
        return jsonify({"error": "app & file required"}), 400
    data, code = process_tag_release_logic(app_name, f.read(), f.filename)
    return jsonify(data), code


@app.route("/versions/<app_name>/<version>", methods=["GET"])
def get_version_paths(app_name, version):
    data, code = get_version_paths_logic(app_name, version)
    return jsonify(data), code


# ——— Kafka dispatcher —————————————————————————————————————
def dispatch_kafka_request(msg: dict):
    method = msg.get("method")
    endpoint = msg.get("endpoint", "")
    payload = msg.get("payload", {})

    if method == "POST" and endpoint == "/tag_release":
        file_b64 = payload.get("file")
        return process_tag_release_logic(
            payload.get("app", ""),
            base64.b64decode(file_b64 or ""),
            payload.get("filename", ""),
        )
    if method == "GET" and endpoint.startswith("/versions/"):
        parts = endpoint.split("/")
        if len(parts) == 4:
            return get_version_paths_logic(parts[2], parts[3])
    return {"error": "Unknown route"}, 400


def start_kafka_consumer():
    try:
        consumer = KafkaConsumer(
            CMD_TOPIC,
            bootstrap_servers=[KAFKA_BROKER],
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="earliest",
            group_id="repository_consumer_group",
        )
        logger.info("Kafka consumer started")
        for msg in consumer:
            resp, code = dispatch_kafka_request(msg.value)
            logger.info(f"Kafka → {msg.value} => {resp} ({code})")
    except Exception as e:
        logger.error(f"Kafka consumer error: {e}")


# start consumer thread when module loads
threading.Thread(target=start_kafka_consumer, daemon=True).start()

# ——— Standalone entrypoint ——————————————————————————————————
if __name__ == "__main__":
    make_log("repository", "Repository standalone start")
    app.run(host="0.0.0.0", port=PORT, debug=False)
