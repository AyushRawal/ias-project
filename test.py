# test.py

import sys
import os
import requests

if len(sys.argv) < 2:
    print("Usage: python test.py <zip_path>")
    sys.exit(1)

zip_path = sys.argv[1]
app_name = "my_app"  # You can customize this or read from descriptor.json inside the zip

# Ensure the file exists
if not os.path.isfile(zip_path):
    print(f"Error: File '{zip_path}' not found.")
    sys.exit(1)

url = "http://10.1.37.28:5002/tag_release"  # Change this if the repository service is running elsewhere

# Send POST request with zip file
with open(zip_path, "rb") as f:
    files = {'file': (os.path.basename(zip_path), f, 'application/zip')}
    data = {'app': app_name}

    print(f"Uploading {zip_path} as app '{app_name}' to repository service...")
    response = requests.post(url, files=files, data=data)

# Output response from the server
print(f"Status Code: {response.status_code}")
print("Response:")
print(response.json())
