import os
import json
import logging
import threading
import requests
from flask import Flask, jsonify, request, Response
from itertools import cycle

# —— Load config ——————————————————————————————————————
HERE = os.path.dirname(__file__)
# Basic error handling for config loading
try:
    with open(os.path.join(HERE, "descriptor.json"), "r") as f:
        CONFIG = json.load(f)
except FileNotFoundError:
    logging.error("descriptor.json not found!")
    exit(1)
except json.JSONDecodeError:
    logging.error("Error decoding descriptor.json!")
    exit(1)


PORT       = CONFIG.get("port", 5000) # Provide default if missing
REG_HOST   = CONFIG.get("registry_host", "localhost") # Provide default
REG_PORT   = CONFIG.get("registry_port", 8080) # Provide default
REG_URL    = f"http://{REG_HOST}:{REG_PORT}"

# —— Logging setup ————————————————————————————————————
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s" # Added logger name
)
logger = logging.getLogger("LoadBalancer")

# —— Flask app ——————————————————————————————————————
app = Flask(__name__)

# Optional: If the Load Balancer ITSELF is behind another proxy (e.g., Nginx handling TLS)
# uncomment and configure ProxyFix for the load balancer app too.
# from werkzeug.middleware.proxy_fix import ProxyFix
# app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


# —— Round-robin pools (simplified, no caching as per original code) ———
_lock = threading.Lock()

def _get_pool(app_name, version, server_type):
    key = (app_name, version, server_type)
    # Removed caching logic based on the commented-out code in the original snippet
    # Using lock just to be safe around registry calls if needed, though not strictly necessary here
    with _lock:
        logger.info(f"Fetching pool for {key}")
        try:
            resp = requests.get(
                f"{REG_URL}/get_application_url",
                params={"name": app_name, "version": version, "server_type": server_type},
                timeout=5 # Added timeout to registry request
            )
            resp.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

            servers = resp.json()
            # Ensure servers is a list - adjust if registry returns different structure
            if not isinstance(servers, list):
                 logger.warning(f"Received unexpected data format from registry for {key}: {servers}")
                 return None

            targets = [
                f"http://{s.get('ip_address')}:{s.get('port')}"
                for s in servers if s.get('ip_address') and s.get('port')
            ]
            if not targets:
                logger.warning(f"No active {server_type} servers found for {app_name}:{version}")
                return None
            logger.info(f"Found targets for {key}: {targets}")
            return cycle(targets)

        except requests.exceptions.RequestException as e:
             logger.error(f"Failed to fetch servers for {key} from registry: {e}")
             return None
        except json.JSONDecodeError as e:
             logger.error(f"Failed to decode JSON response from registry for {key}: {e}")
             return None


# —— Proxy logic (MODIFIED) —————————————————————————————————————
# Added app_name and version arguments to pass context for X-Forwarded-Prefix
def proxy_request(target_url, app_name, version):
    try:
        method = request.method
        # Copy incoming headers, excluding 'Host' (requests library sets the correct Host)
        # Use case-insensitive comparison for keys
        headers = {k: v for k, v in request.headers.items() if k.lower() != 'host'}
        data = request.get_data()
        params = request.args # Query parameters

        # ===========================================================
        # == Add/Update Forwarded Headers ===========================
        # ===========================================================

        # 1. X-Forwarded-For
        # If header exists, append client IP; otherwise, set client IP.
        # request.remote_addr gives the IP of the immediate client connecting to this LB.
        if 'X-Forwarded-For' in request.headers:
            # Append the new client IP to the existing list
            headers['X-Forwarded-For'] = request.headers['X-Forwarded-For'] + ', ' + request.remote_addr
        else:
            # Start the list with the client IP
            headers['X-Forwarded-For'] = request.remote_addr

        # 2. X-Forwarded-Proto
        # Use the scheme the client used to connect to *this* load balancer.
        # This might be 'http' or 'https'. If this LB is behind *another* TLS
        # terminating proxy, you might need ProxyFix (uncommented above) on this LB
        # for request.scheme to be correctly set to 'https'.
        headers['X-Forwarded-Proto'] = request.scheme

        # 3. X-Forwarded-Prefix
        # The prefix under which the application was accessed *at the load balancer*.
        # Based on the routes, this seems to be "/<app_name>/<version>"
        headers['X-Forwarded-Prefix'] = f"/{app_name}/{version}"

        # Optional: X-Forwarded-Host (Original host requested by the client)
        if 'Host' in request.headers:
             headers['X-Forwarded-Host'] = request.headers['Host']

        # ===========================================================

        logger.info(f"→ {method} {target_url} (Proto: {headers['X-Forwarded-Proto']}, Prefix: {headers['X-Forwarded-Prefix']}, For: {headers['X-Forwarded-For']})")
        # logger.debug(f"Forwarding headers: {headers}") # Uncomment for detailed header debugging

        # Make the downstream request
        resp = requests.request(method, target_url,
                                headers=headers, # Pass modified headers
                                data=data,
                                params=params,
                                timeout=10, # Timeout for backend request
                                stream=True) # Use stream=True for potentially large responses

        # Filter headers from the backend response before sending back to client
        excluded_headers = ["content-encoding", "content-length", "transfer-encoding", "connection"]
        response_headers = []
        for name, value in resp.raw.headers.items(): # Use resp.raw.headers for correct case
            if name.lower() not in excluded_headers:
                 response_headers.append((name, value))

        # Return the response from the backend server
        # Use resp.raw to stream content, suitable for large files/responses
        return Response(resp.raw.stream(decode_content=False), resp.status_code, response_headers)

    except requests.exceptions.Timeout:
        logger.error(f"Proxy timeout connecting to {target_url}")
        return jsonify({"error": "Backend service timed out"}), 504 # Gateway Timeout
    except requests.exceptions.RequestException as e:
        logger.error(f"Proxy error connecting to {target_url}: {e}")
        return jsonify({"error": f"Error connecting to backend service: {e}"}), 502 # Bad Gateway
    except Exception as e:
        # Catch-all for unexpected errors during proxying
        logger.exception(f"Unexpected proxy error: {e}") # Log stack trace
        return jsonify({"error": f"An unexpected error occurred: {e}"}), 500 # Internal Server Error

# —— Routes (MODIFIED to pass app_name, version to proxy_request) ——————

@app.route("/<app_name>/<version>/inference", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE"])
@app.route("/<app_name>/<version>/inference/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
def route_inference(app_name, version, path):
    logger.info(f"Routing inference request for {app_name}/{version}/{path}")
    pool = _get_pool(app_name, version, "inference")
    if not pool:
        logger.warning(f"No inference server available for {app_name}/{version}")
        return jsonify({"error": "No inference server available"}), 503 # Service Unavailable
    try:
        target_host = next(pool)
        target_url = f"{target_host}/{path}"
        # Pass app_name and version to proxy_request
        return proxy_request(target_url, app_name, version)
    except StopIteration: # Should not happen with cycle, but good practice
         logger.error(f"Pool exhausted unexpectedly for inference {app_name}/{version}")
         return jsonify({"error": "Internal load balancer error"}), 500


@app.route("/<app_name>/<version>", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE"])
@app.route("/<app_name>/<version>/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
def route_webapp(app_name, version, path):
    logger.info(f"Routing webapp request for {app_name}/{version}/{path}")
    pool = _get_pool(app_name, version, "webapp")
    if not pool:
        logger.warning(f"No webapp server available for {app_name}/{version}")
        return jsonify({"error": "No webapp server available"}), 503 # Service Unavailable
    try:
        target_host = next(pool)
        # Construct target URL, ensuring leading slash if path exists
        target_url = f"{target_host}/{path.lstrip('/')}" if path else target_host
        # Pass app_name and version to proxy_request
        return proxy_request(target_url, app_name, version)
    except StopIteration:
         logger.error(f"Pool exhausted unexpectedly for webapp {app_name}/{version}")
         return jsonify({"error": "Internal load balancer error"}), 500

# This route likely doesn't need the forwarded headers logic, as it's internal comms
@app.route("/get_endpoint", methods=["GET"])
def get_endpoint():
    name = request.args.get("name")
    version = request.args.get("version")
    if not name or not version:
        return jsonify({"error": "Missing name and/or version parameter"}), 400
    logger.info(f"Request for endpoint: {name}/{version}")
    pool = _get_pool(name, version, "webapp") # Assuming webapp? Or should type be param?
    if not pool:
        return jsonify({"error": f"No endpoint available for {name}/{version}"}), 503 # Service Unavailable
    try:
        # Note: next(pool) gives the full http://host:port
        endpoint_url = next(pool)
        return jsonify({"endpoint": endpoint_url})
    except StopIteration:
         logger.error(f"Pool exhausted unexpectedly for get_endpoint {name}/{version}")
         return jsonify({"error": "Internal load balancer error"}), 500

@app.route("/health", methods=["GET"])
def health():
    # Basic health check, could be expanded (e.g., check registry connection)
    return jsonify({"status": "ok"}), 200

# —— Entrypoint —————————————————————————————————————
if __name__ == "__main__":
    logger.info(f"Starting Load Balancer on port {PORT}...")
    logger.info(f"Using Registry at {REG_URL}")
    # Use waitress or gunicorn in production instead of Flask's development server
    app.run(host="0.0.0.0", port=PORT)
