import json
import os
import sys

import requests
from kafka import KafkaProducer

if len(sys.argv) < 2:
    print("Usage: python test.py <zip_path>")
    sys.exit(1)

zip_path = sys.argv[1]
app_name = (
    "my_app"  # You can customize this or read from descriptor.json inside the zip
)
kafka_topic = "Provision_VM"
kafka_bootstrap_servers = ["10.1.37.28:9092"]  # Replace with your Kafka broker address
servers_api_url = "http://10.1.37.28:5001/servers"  # URL for the servers API

# Ensure the file exists
if not os.path.isfile(zip_path):
    print(f"Error: File '{zip_path}' not found.")
    sys.exit(1)

repository_url = "http://10.1.37.28:5002/tag_release"  # Change this if the repository service is running elsewhere


# Send POST request with zip file
with open(zip_path, "rb") as f:
    files = {"file": (os.path.basename(zip_path), f, "application/zip")}
    data = {"app": app_name}

    print(f"\nUploading {zip_path} as app '{app_name}' to repository service...")
    repository_response = requests.post(repository_url, files=files, data=data)

# Output response from the server
print(f"Repository Service Status Code: {repository_response.status_code}")
print("Repository Service Response:")
print(repository_response.json())

# Send message to Kafka topic
message = {"msg": "provision"}

try:
    producer = KafkaProducer(
        bootstrap_servers=kafka_bootstrap_servers,
        value_serializer=lambda x: json.dumps(x).encode("utf-8"),
    )
    producer.send(kafka_topic, message)
    producer.flush()
    print(f"\nMessage '{message}' sent to Kafka topic '{kafka_topic}'")
except Exception as e:
    print(f"Error sending message to Kafka: {e}")
finally:
    if "producer" in locals():
        producer.close()


# --- Get list of servers ---
print("Fetching list of servers...")
try:
    servers_response = requests.get(servers_api_url)
    servers_response.raise_for_status()  # Raise an exception for bad status codes
    servers_data = servers_response.json()
    print("Available Servers:")
    print(json.dumps(servers_data, indent=4))
except requests.exceptions.RequestException as e:
    print(f"Error fetching servers: {e}")
    servers_data = []  # Assign an empty list in case of an error
