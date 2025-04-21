import os
import json
import logging
import threading
import requests
from flask import Flask, jsonify, request
from itertools import cycle

# —— Load config ——————————————————————————————————————
HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "descriptor.json"), "r") as f:
    CONFIG = json.load(f)

PORT          = CONFIG["port"]
REG_HOST      = CONFIG["registry_host"]
REG_PORT      = CONFIG["registry_port"]
REG_URL       = f"http://{REG_HOST}:{REG_PORT}"
APP_MODULE    = CONFIG["app_module"]

# —— Logging setup ————————————————————————————————————
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("LoadBalancer")

# —— Round‑robin state —————————————————————————————————
# one cycle per application+version
_pools = {}
_lock  = threading.Lock()

def _get_pool(app_name: str, version: str):
    key = f"{app_name}:{version}"
    with _lock:
        if key not in _pools:
            # Fetch initial list
            resp = requests.get(
                f"{REG_URL}/servers_by_application",
                params={"name": app_name, "version": version}
            )
            if resp.status_code != 200:
                return None
            urls = [
                f"http://{s['ip_address']}:{s['port']}"
                for s in resp.json()
                if s.get("status") == "active"
            ]
            _pools[key] = cycle(urls)
        return _pools[key]

# —— Flask endpoints —————————————————————————————————————
app = Flask(__name__)

@app.route("/get_endpoint", methods=["GET"])
def get_endpoint():
    """
    Query params:
      - name: application name
      - version: application version
    Returns one next endpoint in round‑robin.
    """
    name    = request.args.get("name")
    version = request.args.get("version")
    if not name or not version:
        return jsonify({"error": "name and version are required"}), 400

    pool = _get_pool(name, version)
    if not pool:
        return jsonify({"error": "Could not fetch servers"}), 502

    try:
        endpoint = next(pool)
    except StopIteration:
        return jsonify({"error": "No available servers"}), 503

    return jsonify({"endpoint": endpoint}), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

# —— Standalone launcher for local dev —————————————————————
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
