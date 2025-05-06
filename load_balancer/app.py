import os
import json
import logging
import threading
import requests
from flask import Flask, jsonify, request, Response
from itertools import cycle

# —— Load config ——————————————————————————————————————
HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "descriptor.json"), "r") as f:
    CONFIG = json.load(f)

PORT       = CONFIG["port"]
REG_HOST   = CONFIG["registry_host"]
REG_PORT   = CONFIG["registry_port"]
REG_URL    = f"http://{REG_HOST}:{REG_PORT}"

# —— Logging setup ————————————————————————————————————
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("LoadBalancer")

# —— Flask app ——————————————————————————————————————
app = Flask(__name__)

# —— Round-robin pools ——————————————————————————————
# Structure: _pools[(app, version, server_type)] = cycle([...])
_pools = {}
_lock = threading.Lock()

def _get_pool(app_name, version, server_type):
    key = (app_name, version, server_type)
    with _lock:
        if key not in _pools:
            logger.info(f"Fetching pool for {key}")
            resp = requests.get(
                f"{REG_URL}/get_application_url",
                params={"name": app_name, "version": version, "server_type": server_type}
            )
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch servers for {key}")
                return None
            servers = resp.json()
            print(servers)
            targets = [
                f"http://{s['ip_address']}:{s['port']}"
                for s in servers
            ]
            if not targets:
                logger.warning(f"No active {server_type} servers for {app_name}:{version}")
                return None
            _pools[key] = cycle(targets)
        return _pools[key]

# —— Proxy logic —————————————————————————————————————
def proxy_request(target_url):
    try:
        method = request.method
        headers = {k: v for k, v in request.headers.items() if k != 'Host'}
        data = request.get_data()
        params = request.args

        logger.info(f"→ {method} {target_url}")

        resp = requests.request(method, target_url,
                                headers=headers,
                                data=data,
                                params=params,
                                timeout=10)

        excluded_headers = ["content-encoding", "content-length", "transfer-encoding", "connection"]
        response_headers = [(name, value) for (name, value) in resp.headers.items()
                            if name.lower() not in excluded_headers]

        return Response(resp.content, resp.status_code, response_headers)
    except Exception as e:
        logger.exception(f"Proxy error: {e}")
        return jsonify({"error": str(e)}), 502

# —— Routes —————————————————————————————————————

@app.route("/<app_name>/<version>/inference", methods=["GET", "POST", "PUT", "DELETE"])
def route_inference(app_name, version):
    pool = _get_pool(app_name, version, "inference")
    if not pool:
        return jsonify({"error": "No inference server available"}), 503
    target = next(pool)
    return proxy_request(f"{target}/inference")

@app.route("/<app_name>/<version>", methods=["GET", "POST", "PUT", "DELETE"])
def route_webapp(app_name, version):
    pool = _get_pool(app_name, version, "webapp")
    if not pool:
        return jsonify({"error": "No webapp server available"}), 503
    target = next(pool)
    return proxy_request(f"{target}/")

@app.route("/get_endpoint", methods=["GET"])
def get_endpoint():
    name = request.args.get("name")
    version = request.args.get("version")
    if not name or not version:
        return jsonify({"error": "Missing name/version"}), 400
    pool = _get_pool(name, version, "webapp")
    if not pool:
        return jsonify({"error": "Unavailable"}), 502
    return jsonify({"endpoint": next(pool)})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

# —— Entrypoint —————————————————————————————————————
if __name__ == "__main__":
    logger.info("Starting Load Balancer...")
    app.run(host="0.0.0.0", port=PORT)
