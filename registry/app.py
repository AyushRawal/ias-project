# registry/app.py

import os
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from kafka import KafkaProducer, KafkaConsumer

# ——— Load configuration ——————————————————————————————————————
HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "descriptor.json"), "r") as f:
    CONFIG = json.load(f)

DATABASE      = CONFIG.get("database", "registry.db")
KAFKA_BROKER  = CONFIG.get("kafka_broker", "10.1.37.28:9092")
LOG_TOPIC     = CONFIG.get("kafka_log_topic", "logs")
CMD_TOPIC     = CONFIG.get("kafka_cmd_topic", "registry_commands")
HTTP_PORT     = CONFIG.get("port", 5001)

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
            value_serializer=lambda v: json.dumps(v).encode("utf-8")
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
        "timestamp": datetime.now(timezone.utc).isoformat()
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
    c.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            process_id INTEGER NOT NULL,
            ip_address TEXT NOT NULL DEFAULT '127.0.0.1',
            port INTEGER NOT NULL,
            server_type TEXT NOT NULL DEFAULT 'standard',
            status TEXT CHECK(status IN ('active','stopped','starting')) DEFAULT 'active',
            registered_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            UNIQUE(name, version)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS server_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL,
            application_id INTEGER NOT NULL,
            FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE,
            FOREIGN KEY(application_id) REFERENCES applications(id) ON DELETE CASCADE,
            UNIQUE(server_id, application_id)
        )
    """)
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
    required = ["process_id", "port", "application_version", "application_name"]
    for f in required:
        if f not in data:
            return {"error": f"Missing field: {f}"}, 400

    pid   = data["process_id"]
    port  = data["port"]
    ver   = data["application_version"]
    name  = data["application_name"]
    ip    = data.get("ip_address", "127.0.0.1")
    stype = data.get("server_type", "standard")
    status= data.get("status", "active")
    registered_at = datetime.now(timezone.utc).isoformat()

    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # application record
        c.execute(
            "INSERT OR IGNORE INTO applications(name,version) VALUES(?,?)",
            (name, ver)
        )
        c.execute(
            "SELECT id FROM applications WHERE name=? AND version=?",
            (name, ver)
        )
        app_id = c.fetchone()["id"]

        # server record
        c.execute(
            "INSERT INTO servers(process_id,ip_address,port,server_type,status,registered_at) VALUES(?,?,?,?,?,?)",
            (pid, ip, port, stype, status, registered_at)
        )
        server_id = c.lastrowid

        # relationship
        c.execute(
            "INSERT INTO server_applications(server_id,application_id) VALUES(?,?)",
            (server_id, app_id)
        )
        conn.commit()
        conn.close()

        msg = f"Registered server {server_id}: {name} v{ver} @ {ip}:{port}"
        make_log("registry", msg)
        return {"message": "Server registered", "server_id": server_id}, 201

    except Exception as e:
        msg = f"Error registering server: {e}"
        make_log("registry", msg)
        return {"error": msg}, 500

def register_application_logic(data):
    if "name" not in data or "version" not in data:
        return {"error": "Missing name or version"}, 400
    name, ver = data["name"], data["version"]
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO applications(name,version) VALUES(?,?)",
            (name, ver)
        )
        conn.commit()
        c.execute(
            "SELECT id FROM applications WHERE name=? AND version=?",
            (name, ver)
        )
        app_id = c.fetchone()[0]
        conn.close()
        msg = f"Registered application {name} v{ver}"
        make_log("registry", msg)
        return {"message": "Application registered", "application_id": app_id}, 201
    except Exception as e:
        msg = f"Error registering application: {e}"
        make_log("registry", msg)
        return {"error": msg}, 500

def update_server_logic(server_id, data):
    # similar to above, omitted for brevity
    return {"message": "Not implemented"}, 501

def delete_server_logic(server_id):
    # omitted for brevity
    return {"message": "Not implemented"}, 501

def delete_application_logic(app_id):
    # omitted for brevity
    return {"message": "Not implemented"}, 501

# ——— Kafka‑consumer dispatcher —————————————————————————————————
def dispatch_kafka_request(msg):
    method   = msg.get("method")
    endpoint = msg.get("endpoint", "")
    payload  = msg.get("payload", {})

    if method == "POST":
        if endpoint == "/register_server":
            return register_server_logic(payload)
        elif endpoint == "/register_application":
            return register_application_logic(payload)
    elif method == "PUT" and endpoint.startswith("/servers/"):
        sid = int(endpoint.rsplit("/",1)[-1])
        return update_server_logic(sid, payload)
    elif method == "DELETE":
        if endpoint.startswith("/servers/"):
            sid = int(endpoint.rsplit("/",1)[-1])
            return delete_server_logic(sid)
        elif endpoint.startswith("/applications/"):
            aid = int(endpoint.rsplit("/",1)[-1])
            return delete_application_logic(aid)

    return {"error": "Unknown route"}, 400

def start_kafka_consumer():
    try:
        consumer = KafkaConsumer(
            CMD_TOPIC,
            bootstrap_servers=[KAFKA_BROKER],
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="earliest",
            group_id="registry_consumer_group"
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
    rows = query_db("""
        SELECT s.id, s.process_id, s.ip_address, s.port,
               s.server_type, s.status, s.registered_at,
               a.name AS application_name, a.version AS application_version
        FROM servers s
        JOIN server_applications sa ON s.id = sa.server_id
        JOIN applications a ON sa.application_id = a.id
    """)
    return jsonify([dict(r) for r in rows]), 200

@app.route("/applications", methods=["GET"])
def list_applications():
    rows = query_db("SELECT * FROM applications")
    return jsonify([dict(r) for r in rows]), 200

@app.route("/get_application_url", methods=["GET"])
def get_application_url():
    name    = request.args.get("name")
    version = request.args.get("version")
    if not name or not version:
        return jsonify({"error": "name and version required"}), 400
    row = query_db("""
        SELECT s.ip_address, s.port
        FROM servers s
        JOIN server_applications sa ON s.id = sa.server_id
        JOIN applications a ON sa.application_id = a.id
        WHERE a.name = ? AND a.version = ? AND s.status='active'
        LIMIT 1
    """, (name, version), one=True)
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify({
        "ip_address": row["ip_address"],
        "port": row["port"],
        "url": f"http://{row['ip_address']}:{row['port']}"
    }), 200

# ——— Kick off Kafka consumer on import ————————————————————————
threading.Thread(target=start_kafka_consumer, daemon=True).start()

# ——— Entrypoint for standalone run ——————————————————————————
if __name__ == "__main__":
    init_db()
    make_log("registry", "Registry server starting")
    app.run(host="0.0.0.0", port=HTTP_PORT, debug=False)
