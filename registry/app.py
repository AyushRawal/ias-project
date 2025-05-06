import json
import logging
import os
import sqlite3
import threading
from datetime import date, datetime, timezone

from flask import Flask, jsonify, request
from kafka import KafkaConsumer, KafkaProducer

# ——— Load configuration ——————————————————————————————————————
HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "descriptor.json"), "r") as f:
    CONFIG = json.load(f)

DATABASE = CONFIG.get("database", "registry.db")
KAFKA_BROKER = CONFIG.get("kafka_broker", "10.1.37.28:9092")
LOG_TOPIC = CONFIG.get("kafka_log_topic", "logs")
CMD_TOPIC = CONFIG.get("kafka_cmd_topic", "registry_commands")
HTTP_PORT = CONFIG.get("port", 5001)

# ——— Logging setup ————————————————————————————————————————
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("Registry")

# ——— Kafka producer initialization ———————————————————————————
kafka_producer = None


def init_producer():
    global kafka_producer
    try:
        kafka_producer = KafkaProducer(
            bootstrap_servers=[KAFKA_BROKER],
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        logger.info("Kafka producer initialized.")
    except Exception as e:
        kafka_producer = None
        logger.warning(f"Could not initialize Kafka producer: {e}")


# ——— Structured logging helper —————————————————————————————
def make_log(server: str, msg: str):
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


# ——— Database helpers —————————————————————————————————————
def init_db():
    """Create tables if missing, then init Kafka producer."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS servers (
            id TEXT PRIMARY KEY,
            ip_address TEXT NOT NULL DEFAULT '127.0.0.1',
            port INTEGER NOT NULL,
            registered_at INTEGER NOT NULL
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            type TEXT NOT NULL,
            process_id TEXT NOT NULL,
            started_at INTEGER NOT NULL,
            ip_address TEXT NOT NULL DEFAULT '127.0.0.1',
            port INTEGER NOT NULL,
            UNIQUE(ip_address, port)
        )
    """
    )
    # c.execute(
    #     """
    #     CREATE TABLE IF NOT EXISTS server_applications (
    #         id INTEGER PRIMARY KEY AUTOINCREMENT,
    #         server_id TEXT NOT NULL,
    #         application_id INTEGER NOT NULL,
    #         FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE,
    #         FOREIGN KEY(application_id) REFERENCES applications(id) ON DELETE CASCADE,
    #         UNIQUE(server_id, application_id)
    #     )
    # """
    # )
    conn.commit()
    conn.close()
    logger.info("Database initialized.")
    init_producer()


def query_db(query: str, args=(), one=False):
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(query, args)
    if query.strip().upper().startswith("SELECT"):
        rows = c.fetchall()
        conn.close()
        return (rows[0] if rows else None) if one else rows
    conn.commit()
    conn.close()
    return c.rowcount


# ——— Business logic (POST/PUT/DELETE) ————————————————————————
def register_server_logic(data):
    required = ["id", "ip_address", "port"]
    for f in required:
        if f not in data:
            msg = f"Invalid register server request, missing field: {f}"
            make_log("registry", msg)
            return {"error": f"Missing field: {f}"}, 400

    id = data["id"]
    port = data["port"]
    ip = data["ip_address"]
    registered_at = datetime.now(timezone.utc).isoformat()

    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # server record
        c.execute(
            "INSERT INTO servers(id,ip_address,port,registered_at) VALUES(?,?,?,?)",
            (id, ip, port, registered_at),
        )

        conn.commit()
        conn.close()

        msg = f"Registered server {id} @ {ip}:{port}"
        make_log("registry", msg)
        return {"message": "Server registered", "server_id": id}, 201

    except Exception as e:
        msg = f"Error registering server: {e}"
        make_log("registry", msg)
        return {"error": msg}, 500


def register_application_logic(data):
    required = ["name", "version", "process_id", "type", "ip_address", "port"]
    for f in required:
        if f not in data:
            msg = f"Invalid register server request, missing field: {f}"
            make_log("registry", msg)
            return {"error": f"Missing field: {f}"}, 400

    name = data["name"]
    version = data["version"]
    process_id = data["process_id"]
    server_type = data["type"]
    ip_address = data["ip_address"]
    port = data["port"]
    started_at = datetime.now()

    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute(
            "INSERT INTO applications(name,version,process_id,type,ip_address,port,started_at) VALUES(?,?,?,?,?,?,?)",
            (name, version, process_id, server_type, ip_address, port, started_at),
        )
        conn.commit()
        c.execute(
            "SELECT id FROM applications WHERE ip_address=? AND port=?",
            (ip_address, port),
        )
        app_id = c.fetchone()[0]
        conn.close()
        msg = f"Registered application {name} v{version}"
        make_log("registry", msg)
        return {"message": "Application registered", "application_id": app_id}, 201
    except Exception as e:
        msg = f"Error registering application: {e}"
        make_log("registry", msg)
        return {"error": msg}, 500


def delete_server_logic(server_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("DELETE FROM servers WHERE id = ?", (server_id,))
        conn.commit()
        conn.close()
        msg = f"Deleted server with ID {server_id}"
        make_log("registry", msg)
        return {"message": "Server deleted", "server_id": server_id}, 200
    except Exception as e:
        msg = f"Error deleting server: {e}"
        make_log("registry", msg)
        return {"error": msg}, 500


def delete_application_logic(payload):
    ip_address = payload["ip_address"]
    port = payload["port"]
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute(
            "DELETE FROM applications WHERE ip_address = ? AND port = ?",
            (ip_address, port),
        )
        conn.commit()
        conn.close()
        msg = f"Deleted application with IP {ip_address}, Port {port}"
        make_log("registry", msg)
        return {
            "message": "Application deleted",
            "ip_address": ip_address,
            "port": port,
        }, 200
    except Exception as e:
        msg = f"Error deleting application: {e}"
        make_log("registry", msg)
        return {"error": msg}, 500


# ——— Kafka‑consumer dispatcher —————————————————————————————————
def dispatch_kafka_request(msg):
    method = msg.get("method")
    endpoint = msg.get("endpoint", "")
    payload = msg.get("payload", {})

    if method == "POST":
        if endpoint == "/register_server":
            return register_server_logic(payload)
        elif endpoint == "/register_application":
            return register_application_logic(payload)
    elif method == "DELETE":
        if endpoint.startswith("/servers/"):
            sid = int(endpoint.rsplit("/", 1)[-1])
            return delete_server_logic(sid)
        elif endpoint.startswith("/applications/"):
            return delete_application_logic(payload)

    return {"error": "Unknown route"}, 400


def start_kafka_consumer():
    try:
        consumer = KafkaConsumer(
            CMD_TOPIC,
            bootstrap_servers=[KAFKA_BROKER],
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="earliest",
            group_id="registry_consumer_group",
        )
        logger.info("Kafka consumer thread started.")
        for message in consumer:
            resp, code = dispatch_kafka_request(message.value)
            logger.info(f"Kafka → {message.value} => {resp} ({code})")
    except Exception as e:
        logger.error(f"Kafka consumer failed: {e}")


# ——— Flask app & HTTP GET endpoints ——————————————————————————————
app = Flask(__name__)


@app.route("/servers", methods=["GET"])
def list_servers():
    rows = query_db(
        """
        SELECT * from servers;
    """
    )
    return jsonify([dict(r) for r in rows]), 200


@app.route("/applications", methods=["GET"])
def list_applications():
    rows = query_db("SELECT * FROM applications")
    return jsonify([dict(r) for r in rows]), 200


@app.route("/get_application_url", methods=["GET"])
def get_application_url():
    name = request.args.get("name")
    version = request.args.get("version")
    server_type = request.args.get("server_type")
    if not name or not version or not server_type:
        return jsonify({"error": "name, version and server_type required"}), 400
    rows = query_db(
        """
        SELECT ip_address, port
        FROM applications
        WHERE name = ? AND version = ? AND type = ?
    """,
        (name, version, server_type),
    )
    if not rows:
        return jsonify({"error": "Not found"}), 404
    return jsonify([dict(r) for r in rows]), 200


# ——— Kick off Kafka consumer on import ————————————————————————
threading.Thread(target=start_kafka_consumer, daemon=True).start()

# ——— Entrypoint for standalone run ——————————————————————————
if __name__ == "__main__":
    init_db()
    make_log("registry", "Registry server starting")
    app.run(host="0.0.0.0", port=HTTP_PORT, debug=False)
