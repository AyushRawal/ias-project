# Intelligent Application Server (IAS)

A microservices-based application infrastructure system for deploying, managing, and scaling applications.

## System Overview

This system consists of several components working together to deploy and manage applications:

- **Registry Server**: Manages application registrations and configurations
- **Repository Server**: Handles application package storage and retrieval
- **Server Lifecycle Manager**: Manages the lifecycle of application servers
- **Logging Server**: Centralized logging service
- **Load Balancer**: Distributes traffic among application instances

## Application Deployment

Applications are deployed as ZIP files with a specific structure. The system supports two types of applications:

1. **Inference Applications**: ML model inference services
2. **Web Applications**: Web-based user interfaces

### ZIP File Structure

Each deployment ZIP file must follow this structure:

```
application.zip
│
├── inference/             # ML model inference service (if applicable)
│   ├── app.py             # Main application code
│   ├── descriptor.json    # Configuration for the inference service
│   └── model.pt           # ML model file
│
└── webapp/                # Web application (if applicable)
    ├── app.py             # Main web application code
    └── descriptor.json    # Configuration for the web application
```

Either or both components can be included in the ZIP file. The system will deploy each component separately based on its descriptor.json configuration.

### Example Descriptor Files

#### Inference Service Descriptor (inference/descriptor.json)

```json
{
  "name": "example-inference-service",
  "version": "1.0.0",
  "port": 5100,
  "app_module": "app:app",
  "init_module": "app:init_model",
  "dependencies": [
    "flask==2.0.1",
    "numpy==1.21.2",
    "torch==1.9.0",
    "transformers==4.9.2"
  ],
  "environment": {
    "MODEL_PATH": "model.pt",
    "LOG_LEVEL": "INFO"
  }
}
```

#### Web Application Descriptor (webapp/descriptor.json)

```json
{
  "name": "example-webapp",
  "version": "1.0.0",
  "port": 5200,
  "app_module": "app:app",
  "init_module": null,
  "dependencies": [
    "flask==2.0.1",
    "requests==2.26.0"
  ],
  "environment": {
    "INFERENCE_SERVICE_URL": "http://localhost:5100",
    "LOG_LEVEL": "INFO"
  }
}
```

## Deployment Instructions

1. **Prepare your application**:
   - Create the necessary folders and files as described above
   - Implement your application code in app.py files
   - Configure your descriptor.json files
   - Include any model files or additional resources

2. **Create a ZIP file** containing your application structure

3. **Upload the ZIP file** using the test script:
   ```
   python test.py path/to/your/application.zip
   ```

4. **Access your application**:
   - Inference service: `http://localhost:<port-from-descriptor>`
   - Web application: `http://localhost:<port-from-descriptor>`

## Descriptor.json Reference

| Field         | Type           | Description                                                     |
|---------------|----------------|-----------------------------------------------------------------|
| name          | string         | Application name                                               |
| version       | string         | Application version                                            |
| port          | number         | Port on which the application will run                         |
| app_module    | string         | Python module path to the application object (package:object)  |
| init_module   | string or null | Python module path to initialization function (package:function)|
| dependencies  | array          | List of Python package dependencies (pip format)              |
| environment   | object         | Key-value pairs of environment variables                       |

## Troubleshooting

If you encounter issues with deployment:
1. Check your descriptor.json for formatting errors
2. Ensure all dependencies are specified correctly
3. Verify your app.py implements the expected interface
4. Check the logs for detailed error messages:
   ```
   tail -f logging/server_logs.log
   ```