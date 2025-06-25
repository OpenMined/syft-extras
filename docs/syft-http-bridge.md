# Syft-HTTP-Bridge Package Documentation

## Overview

The `syft-http-bridge` package enables SyftBox applications to communicate with external HTTP APIs by bridging the gap between the SyftBox filesystem-based communication and standard HTTP protocols. It acts as a proxy that translates HTTP requests and responses to/from the SyftBox file system.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      syft-http-bridge                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐ │
│  │   Bridge     │    │   Client     │    │      Serde       │ │
│  │              │    │              │    │                  │ │
│  │ - Watch FS   │    │ - Transport  │    │ - Serialize req  │ │
│  │ - Process    │    │ - Send files │    │ - Serialize resp │ │
│  │ - Forward    │    │ - Wait resp  │    │ - msgpack format │ │
│  └──────────────┘    └──────────────┘    └──────────────────┘ │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                   File System Layout                      │  │
│  │                                                           │  │
│  │  app_data/                                               │  │
│  │  └── http_app/                                           │  │
│  │      └── http/                                           │  │
│  │          ├── requests/                                   │  │
│  │          │   └── {request_id}.request                    │  │
│  │          └── responses/                                  │  │
│  │              └── {request_id}.response                   │  │
│  │                                                           │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Request-Response Flow

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│  SyftBox    │      │   HTTP      │      │   HTTP      │      │  External   │
│    App      │      │   Bridge    │      │  Transport  │      │    API      │
└──────┬──────┘      └──────┬──────┘      └──────┬──────┘      └──────┬──────┘
       │                     │                     │                     │
       │ 1. Write Request    │                     │                     │
       │    to filesystem    │                     │                     │
       ├────────────────────►│                     │                     │
       │                     │                     │                     │
       │                     │ 2. Detect & Read    │                     │
       │                     │    Request File     │                     │
       │                     ├────────────────────►│                     │
       │                     │                     │                     │
       │                     │                     │ 3. Send HTTP       │
       │                     │                     │    Request         │
       │                     │                     ├────────────────────►│
       │                     │                     │                     │
       │                     │                     │ 4. HTTP Response   │
       │                     │                     │◄────────────────────┤
       │                     │                     │                     │
       │                     │ 5. Write Response   │                     │
       │                     │◄────────────────────┤                     │
       │                     │                     │                     │
       │ 6. Read Response    │                     │                     │
       │◄────────────────────┤                     │                     │
       │                     │                     │                     │
       ▼                     ▼                     ▼                     ▼
```

## Core Components

### 1. Serialization (serde.py)

The serialization module handles converting HTTP requests and responses to/from a binary format using MessagePack:

```python
from syft_http_bridge.serde import (
    serialize_request,
    deserialize_request,
    serialize_response,
    deserialize_response
)
import httpx

# Serialize a request
request = httpx.Request("GET", "https://api.example.com/users")
serialized = serialize_request(request)  # Returns bytes

# Deserialize back
restored_request = deserialize_request(serialized)
assert restored_request.method == "GET"
assert str(restored_request.url) == "https://api.example.com/users"

# Serialize a response
response = httpx.Response(200, json={"users": ["alice", "bob"]})
serialized_resp = serialize_response(response)

# Deserialize back
restored_response = deserialize_response(serialized_resp)
assert restored_response.status_code == 200
```

**Serialization Format**:
- Uses MessagePack for efficient binary encoding
- Preserves all request/response properties
- Handles headers, body, extensions
- Supports streaming content

### 2. Client Transport

The client provides an httpx-compatible transport that uses the filesystem:

```python
from syft_http_bridge import create_syft_http_client
from syft_core import Client as SyftBoxClient

# Create a SyftBox HTTP client
syftbox_client = SyftBoxClient.load()
http_client = create_syft_http_client(
    app_name="my_app",
    host="api.example.com",
    syftbox_client=syftbox_client,
    timeout=60.0  # Optional timeout in seconds
)

# Use it like a regular httpx client
response = http_client.get("https://api.example.com/users")
print(response.json())

# Supports all HTTP methods
response = http_client.post(
    "https://api.example.com/users",
    json={"name": "Alice", "email": "alice@example.com"}
)

# Headers and authentication
response = http_client.get(
    "https://api.example.com/protected",
    headers={"Authorization": "Bearer token123"}
)
```

### 3. FileSystemTransport

Lower-level transport for custom implementations:

```python
from syft_http_bridge.client import FileSystemTransport
from pathlib import Path

# Create transport with specific directories
transport = FileSystemTransport(
    requests_dir=Path("/path/to/requests"),
    responses_dir=Path("/path/to/responses"),
    requesting_user="alice@example.com",
    timeout=30.0,
    poll_interval=0.1,  # Check for response every 100ms
    delete_response=True  # Clean up response files
)

# Use with httpx
import httpx
client = httpx.Client(transport=transport)
response = client.get("https://api.example.com/data")
```

### 4. Bridge Server

The bridge server watches for request files and forwards them to external APIs:

```python
from syft_http_bridge import SyftHttpBridge
from syft_core import Client

# Create bridge for specific app
client = Client.load()
bridge = SyftHttpBridge(
    app_name="weather_api",
    client=client,
    allowed_hosts=["api.weather.com", "api.openweather.org"],
    max_workers=5  # Concurrent request handlers
)

# Start the bridge
bridge.run()
```

## Usage Patterns

### Basic API Client

```python
from syft_http_bridge import create_syft_http_client
from syft_core import Client

# Weather API client
syftbox_client = Client.load()
weather_client = create_syft_http_client(
    app_name="weather_app",
    host="api.openweathermap.org",
    syftbox_client=syftbox_client
)

# Get weather data
response = weather_client.get("/data/2.5/weather", params={
    "q": "London",
    "appid": "your_api_key",
    "units": "metric"
})

weather_data = response.json()
print(f"Temperature in London: {weather_data['main']['temp']}°C")
```

### Authenticated Requests

```python
# GitHub API client with authentication
github_client = create_syft_http_client(
    app_name="github_integration",
    host="api.github.com",
    syftbox_client=syftbox_client
)

# Set default headers
github_client.headers.update({
    "Authorization": f"token {github_token}",
    "Accept": "application/vnd.github.v3+json"
})

# Get user repositories
response = github_client.get("/user/repos")
repos = response.json()

for repo in repos:
    print(f"- {repo['name']}: {repo['description']}")
```

### Handling Errors

```python
from httpx import HTTPStatusError, TimeoutException

try:
    response = http_client.get("https://api.example.com/data")
    response.raise_for_status()  # Raise for 4xx/5xx
    data = response.json()
except HTTPStatusError as e:
    print(f"HTTP error: {e.response.status_code}")
except TimeoutException:
    print("Request timed out")
except Exception as e:
    print(f"Unexpected error: {e}")
```

### Streaming Responses

```python
# Download large file
with http_client.stream("GET", "https://example.com/large-file.zip") as response:
    with open("downloaded.zip", "wb") as f:
        for chunk in response.iter_bytes(chunk_size=8192):
            f.write(chunk)

# Stream JSON lines
with http_client.stream("GET", "https://api.example.com/stream") as response:
    for line in response.iter_lines():
        data = json.loads(line)
        process_data(data)
```

## File System Structure

The HTTP bridge uses a specific directory structure:

```
datasites/
└── alice@example.com/
    └── app_data/
        └── weather_app/
            ├── http/
            │   ├── requests/
            │   │   ├── 123e4567-e89b-12d3-a456-426614174000.request
            │   │   └── 987fcdeb-51a2-43f1-b012-5a6f7c8e9d10.request
            │   └── responses/
            │       ├── 123e4567-e89b-12d3-a456-426614174000.response
            │       └── 987fcdeb-51a2-43f1-b012-5a6f7c8e9d10.response
            └── syft.pub.yaml  # Permissions
```

### Permission Configuration

The bridge requires appropriate permissions:

```yaml
# syft.pub.yaml for HTTP bridge app
rules:
  - pattern: "http/requests/*.request"
    access:
      write: ["*"]      # Anyone can write requests
      admin: ["alice@example.com"]
      
  - pattern: "http/responses/*.response"
    access:
      read: ["*"]       # Anyone can read responses
      admin: ["alice@example.com"]
```

## Advanced Features

### Request Interception

```python
class LoggingTransport(FileSystemTransport):
    def handle_request(self, request):
        # Log request
        print(f"[{request.method}] {request.url}")
        
        # Modify request if needed
        request.headers["X-Client-ID"] = "syftbox"
        
        # Call parent implementation
        response = super().handle_request(request)
        
        # Log response
        print(f"Response: {response.status_code}")
        
        return response

# Use custom transport
transport = LoggingTransport(
    requests_dir=Path("requests"),
    responses_dir=Path("responses")
)
client = httpx.Client(transport=transport)
```

### Batch Requests

```python
import asyncio
import httpx

async def batch_requests(urls):
    async with httpx.AsyncClient(transport=transport) as client:
        tasks = [client.get(url) for url in urls]
        responses = await asyncio.gather(*tasks)
        return responses

# Execute batch
urls = [
    "https://api.example.com/user/1",
    "https://api.example.com/user/2",
    "https://api.example.com/user/3",
]
responses = asyncio.run(batch_requests(urls))
```

### Caching Responses

```python
from datetime import datetime, timedelta
import json

class CachingTransport(FileSystemTransport):
    def __init__(self, *args, cache_dir=None, cache_ttl=3600, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_dir = cache_dir or Path("cache")
        self.cache_ttl = cache_ttl  # seconds
        self.cache_dir.mkdir(exist_ok=True)
    
    def handle_request(self, request):
        # Check cache for GET requests
        if request.method == "GET":
            cache_key = self._get_cache_key(request)
            cached = self._get_cached_response(cache_key)
            if cached:
                return cached
        
        # Make real request
        response = super().handle_request(request)
        
        # Cache successful GET responses
        if request.method == "GET" and response.status_code == 200:
            self._cache_response(cache_key, response)
        
        return response
    
    def _get_cache_key(self, request):
        import hashlib
        key = f"{request.method}:{request.url}"
        return hashlib.sha256(key.encode()).hexdigest()
    
    def _get_cached_response(self, cache_key):
        cache_file = self.cache_dir / f"{cache_key}.cache"
        if cache_file.exists():
            data = json.loads(cache_file.read_text())
            # Check expiry
            cached_at = datetime.fromisoformat(data["cached_at"])
            if datetime.now() - cached_at < timedelta(seconds=self.cache_ttl):
                return httpx.Response(
                    status_code=data["status_code"],
                    headers=data["headers"],
                    content=data["content"].encode()
                )
        return None
```

## Security Considerations

### 1. Host Whitelisting

Always restrict which hosts can be accessed:

```python
bridge = SyftHttpBridge(
    app_name="api_client",
    client=client,
    allowed_hosts=[
        "api.trusted-service.com",
        "secure-api.example.org"
    ]
)

# Requests to other hosts will be rejected
```

### 2. Request Validation

```python
class SecureTransport(FileSystemTransport):
    def handle_request(self, request):
        # Validate URL scheme
        if request.url.scheme not in ["https"]:
            raise ValueError("Only HTTPS allowed")
        
        # Check headers
        if "Authorization" in request.headers:
            # Validate token format
            auth = request.headers["Authorization"]
            if not auth.startswith("Bearer "):
                raise ValueError("Invalid auth format")
        
        return super().handle_request(request)
```

### 3. Rate Limiting

```python
from collections import defaultdict
from datetime import datetime, timedelta

class RateLimitedTransport(FileSystemTransport):
    def __init__(self, *args, rate_limit=60, window=60, **kwargs):
        super().__init__(*args, **kwargs)
        self.rate_limit = rate_limit  # requests
        self.window = window  # seconds
        self.requests = defaultdict(list)
    
    def handle_request(self, request):
        # Check rate limit
        now = datetime.now()
        user = self.requesting_user or "anonymous"
        
        # Clean old requests
        cutoff = now - timedelta(seconds=self.window)
        self.requests[user] = [
            ts for ts in self.requests[user] if ts > cutoff
        ]
        
        # Check limit
        if len(self.requests[user]) >= self.rate_limit:
            raise Exception(f"Rate limit exceeded: {self.rate_limit}/{self.window}s")
        
        # Record request
        self.requests[user].append(now)
        
        return super().handle_request(request)
```

## Performance Optimization

### 1. Connection Pooling

```python
# Reuse client for multiple requests
client = create_syft_http_client(
    app_name="api_client",
    host="api.example.com",
    syftbox_client=syftbox_client
)

# Client maintains connection pool
for i in range(100):
    response = client.get(f"/data/{i}")
    # Connection is reused

# Close when done
client.close()
```

### 2. Parallel Processing

```python
bridge = SyftHttpBridge(
    app_name="bulk_processor",
    client=client,
    max_workers=10  # Process up to 10 requests in parallel
)
```

### 3. Request Timeout

```python
# Set appropriate timeouts
client = create_syft_http_client(
    app_name="fast_api",
    host="api.example.com",
    syftbox_client=syftbox_client,
    timeout=5.0  # 5 second timeout
)

# Or per-request timeout
response = client.get("/endpoint", timeout=10.0)
```

## Troubleshooting

### Common Issues

1. **Request files not being processed**
   - Check bridge is running
   - Verify file permissions
   - Check allowed_hosts configuration

2. **Timeout errors**
   - Increase timeout value
   - Check network connectivity
   - Verify API endpoint is responsive

3. **Serialization errors**
   - Ensure valid HTTP methods
   - Check request/response content types
   - Verify msgpack is installed

### Debug Mode

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# Bridge will log all operations
bridge = SyftHttpBridge(
    app_name="debug_app",
    client=client,
    debug=True
)
```

### Health Checks

```python
def check_bridge_health(app_name, client):
    """Check if bridge is working properly."""
    http_client = create_syft_http_client(
        app_name=app_name,
        host="httpbin.org",
        syftbox_client=client,
        timeout=5.0
    )
    
    try:
        response = http_client.get("/status/200")
        return response.status_code == 200
    except Exception as e:
        print(f"Health check failed: {e}")
        return False
```

## Best Practices

1. **Always use HTTPS** for external APIs
2. **Implement proper error handling** for network failures
3. **Set reasonable timeouts** to prevent hanging
4. **Use connection pooling** for multiple requests
5. **Implement caching** for frequently accessed data
6. **Monitor request/response files** to prevent disk filling
7. **Rotate logs** and clean up old files
8. **Use rate limiting** to respect API limits
9. **Validate all inputs** before forwarding
10. **Keep sensitive data** (API keys) secure

## Example: Complete Weather App

```python
from syft_http_bridge import create_syft_http_client
from syft_core import Client
import os

class WeatherApp:
    def __init__(self, api_key):
        self.api_key = api_key
        self.client = create_syft_http_client(
            app_name="weather_monitor",
            host="api.openweathermap.org",
            syftbox_client=Client.load()
        )
    
    def get_weather(self, city):
        """Get current weather for a city."""
        response = self.client.get("/data/2.5/weather", params={
            "q": city,
            "appid": self.api_key,
            "units": "metric"
        })
        response.raise_for_status()
        return response.json()
    
    def get_forecast(self, city, days=5):
        """Get weather forecast."""
        response = self.client.get("/data/2.5/forecast", params={
            "q": city,
            "appid": self.api_key,
            "units": "metric",
            "cnt": days * 8  # 8 forecasts per day (3-hour intervals)
        })
        response.raise_for_status()
        return response.json()
    
    def close(self):
        """Clean up resources."""
        self.client.close()

# Usage
app = WeatherApp(api_key=os.getenv("OPENWEATHER_API_KEY"))
try:
    weather = app.get_weather("London")
    print(f"Current temperature: {weather['main']['temp']}°C")
    print(f"Conditions: {weather['weather'][0]['description']}")
    
    forecast = app.get_forecast("London", days=3)
    print(f"\nForecast has {len(forecast['list'])} data points")
finally:
    app.close()
```