# Syft RPC Application Template (PingPong Library)

A template for building distributed applications on Syft with bidirectional communication, using PingPong as a concrete example.

## Overview

This library provides a general-purpose framework for building RPC-based applications on Syft, with a sample PingPong implementation. It serves as:

1. **A working example**: The PingPong application demonstrates bidirectional communication
2. **A template for your own apps**: The generic SyftRPCClient class can be extended for various use cases
3. **A learning resource**: Understand how to build distributed applications on Syft

The template handles the complexities of:
- Setting up background servers to receive requests
- Sending requests to other datasites
- Discovering available endpoints
- Error handling and resource management

## Features

- **Generic RPC Framework**: Extensible base class for building custom Syft applications
- **Simple Implementation API**: Create new applications by extending the base class and customizing a few methods
- **Background Processing**: Automatically handle incoming requests while sending outgoing ones
- **Client Discovery**: Identify available datasites and active servers
- **Clean Resource Management**: Simple shutdown of background server threads
- **Extensive Documentation**: Comments and examples make it easy to adapt for your needs

## Quick Start Guide

### Step 1: Set up SyftBox Clients (Development Environment)

For testing, you'll need one or more SyftBox clients:

```bash
# Create Alice's config
cat > ~/.syft_alice_config.json << EOL
{
    "data_dir": "${HOME}/Desktop/SyftBoxAlice",
    "server_url": "https://syftboxstage.openmined.org/",
    "client_url": "http://127.0.0.1:8082/",
    "email": "alice@openmined.org",
    "token": "0",
    "access_token": "YOUR_ALICE_ACCESS_TOKEN",
    "client_timeout": 5.0
}
EOL

# Start Alice's SyftBox client
rm -rf ~/Desktop/SyftBoxAlice
syftbox client --server https://syftboxstage.openmined.org \
              --email alice@openmined.org \
              --sync_folder ~/Desktop/SyftBoxAlice \
              --port 8082 \
              --config ~/.syft_alice_config.json
```

### Step 2: Use the PingPong Example

```python
import pingpong as pp

# Create a PingPong client
client = pp.client("~/.syft_alice_config.json")

# List available datasites
datasites = client.list_datasites()
print(f"All datasites: {len(datasites)}")

# List only datasites with the PingPong server running
servers = client.list_available_servers()
print(f"Active PingPong servers: {len(servers)}")

# Send a ping to another datasite
if servers:
    response = client.ping(servers[0])
    print(f"Response: {response.msg}")

# Clean up when done
client.close()
```

### Step 3: Build Your Own Syft App

Create your own application by extending the base class:

```python
from pingpong import SyftRPCClient
from pydantic import BaseModel, Field
from datetime import datetime
import time

# Define custom request/response models
class WeatherRequest(BaseModel):
    location: str = Field(description="City or coordinates")
    units: str = Field(default="metric", description="Temperature units")

class WeatherResponse(BaseModel):
    location: str = Field(description="Location of forecast")
    temperature: float = Field(description="Current temperature")
    conditions: str = Field(description="Weather conditions")
    timestamp: datetime = Field(description="Forecast time")

# Create your custom client
class WeatherClient(SyftRPCClient):
    def __init__(self, config_path=None):
        super().__init__(
            config_path=config_path,
            app_name="weather",
            endpoint="/forecast",
            request_model=WeatherRequest,
            response_model=WeatherResponse
        )
    
    def _handle_request(self, request_data, ctx, box):
        # In a real app, you'd look up actual weather data
        # This is just a mock implementation
        return WeatherResponse(
            location=request_data.location,
            temperature=22.5 if request_data.units == "metric" else 72.5,
            conditions="Sunny",
            timestamp=datetime.now()
        )
    
    def get_forecast(self, email, location):
        request = WeatherRequest(location=location)
        return self.send_request(email, request)

# Usage
client = WeatherClient("~/.syft_config.json")
forecast = client.get_forecast("other@example.com", "New York")
print(f"Temperature in {forecast.location}: {forecast.temperature}°C")
```

## API Reference

### Base Class

#### `SyftRPCClient(config_path, app_name, endpoint, request_model, response_model)`
The base class for building Syft RPC applications.

**Arguments:**
- `config_path`: Path to a custom Syft config.json file
- `app_name`: Name of your application (determines RPC directory)
- `endpoint`: The RPC endpoint name
- `request_model`: Pydantic model for requests
- `response_model`: Pydantic model for responses

**Key Methods:**
- `send_request(to_email, request_data)`: Send a request to another datasite
- `list_datasites()`: Get all available datasites
- `list_available_servers()`: Get datasites running your app's server
- `close()`: Shut down the client and server

**Methods to Override:**
- `_handle_request(request_data, ctx, box)`: Process incoming requests

### PingPong Implementation

#### `PingPongClient(config_path)`
A concrete implementation of SyftRPCClient for the PingPong use case.

**Methods:**
- `ping(email)`: Send a ping to the specified datasite

### Factory Function

#### `client(config_path)`
Create and return a new PingPong client instance.

## Design Philosophy

The template is designed around several key principles:

1. **Separation of concerns**: Generic RPC functionality is separate from specific application logic
2. **Extension over modification**: Create new applications by extending the base class rather than modifying it
3. **Convention over configuration**: Sensible defaults with the ability to customize when needed
4. **Error resilience**: Robust error handling with clear feedback
5. **Resource management**: Clean startup and shutdown of background processes

This approach makes it easy to build a wide variety of applications on Syft while maintaining a consistent structure.

## Troubleshooting

### Connection Issues
- Ensure SyftBox clients are running and connected
- Check network connectivity between clients
- Verify access tokens are valid

### Discovery Problems
- Wait for datasites to be fully discovered by the network
- Use `list_available_servers()` to see which datasites have your app's server running
- Ensure your app name and endpoint match between clients

### Server Errors
- Check the logs for specific error messages
- If you see "already scheduled" warnings, it's often safe to ignore them
- Ensure model definitions match between clients

## Extending the Template

The template can be extended in many ways:

1. **Custom data models**: Define your own request and response models
2. **Multiple endpoints**: Register different handlers for various endpoints
3. **Authentication**: Add custom authentication in request handling
4. **Complex business logic**: Implement sophisticated processing in request handlers
5. **Custom discovery**: Extend the discovery mechanisms to find specific capabilities

## Examples of Possible Applications

1. **Distributed Data Processing**: Request computation on data located at another datasite
2. **Notification Systems**: Send and receive notifications between datasites
3. **Distributed Databases**: Query and update data across multiple datasites
4. **Collaborative Applications**: Enable real-time collaboration between users
5. **Monitoring Systems**: Collect and aggregate status information from multiple datasites

The template provides a solid foundation for all these use cases and more.
