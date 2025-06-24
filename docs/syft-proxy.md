# Syft-Proxy Package Documentation

## Overview

The `syft-proxy` package provides a centralized HTTP proxy server that facilitates RPC communication between SyftBox applications. It acts as a message broker, allowing applications to send requests to each other without direct network connections, using a RESTful API interface.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         syft-proxy                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐ │
│  │   Models     │    │   Server     │    │      CLI         │ │
│  │              │    │              │    │                  │ │
│  │ - RPCSend    │    │ - FastAPI    │    │ - Start server   │ │
│  │ - RPCStatus  │    │ - Endpoints  │    │ - Health check   │ │
│  │ - Broadcast  │    │ - Storage    │    │ - Debug tools    │ │
│  └──────────────┘    └──────────────┘    └──────────────────┘ │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                    API Endpoints                          │  │
│  │                                                           │  │
│  │  POST   /rpc/send          - Send RPC request            │  │
│  │  POST   /rpc/broadcast     - Broadcast to multiple       │  │
│  │  GET    /rpc/status/{id}   - Check request status        │  │
│  │  GET    /rpc/schema/{app}  - Get app schema              │  │
│  │  GET    /                  - Server info                 │  │
│  │                                                           │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Communication Flow

```
┌──────────┐          ┌──────────┐          ┌──────────┐
│  App A   │          │  Proxy   │          │  App B   │
│ (Client) │          │ (Server) │          │ (Server) │
└────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │
     │ 1. POST /rpc/send   │                     │
     │   {app: "app_b",    │                     │
     │    dest: "bob@..."} │                     │
     ├────────────────────►│                     │
     │                     │                     │
     │ 2. Store request    │                     │
     │    Return ID        │                     │
     │◄────────────────────┤                     │
     │                     │                     │
     │                     │ 3. Forward request  │
     │                     ├────────────────────►│
     │                     │                     │
     │                     │ 4. Process &        │
     │                     │    Return response  │
     │                     │◄────────────────────┤
     │                     │                     │
     │ 5. GET /rpc/status  │                     │
     │    /{id}            │                     │
     ├────────────────────►│                     │
     │                     │                     │
     │ 6. Return response  │                     │
     │◄────────────────────┤                     │
     │                     │                     │
     ▼                     ▼                     ▼
```

## Core Components

### 1. Data Models

**RPCSendRequest** - Request to send an RPC call:
```python
from syft_proxy.models import RPCSendRequest
from syft_core.url import SyftBoxURL

request = RPCSendRequest(
    app_name="calculator",              # Target app
    func_name="add",                    # Function to call
    destination="bob@example.com",      # Target user
    params={"a": 5, "b": 3},           # Function parameters
    blocking=True,                      # Wait for response
    timeout=30.0,                       # Timeout in seconds
    headers={"X-Request-ID": "123"}     # Optional headers
)
```

**RPCBroadcastRequest** - Broadcast to multiple destinations:
```python
from syft_proxy.models import RPCBroadcastRequest

broadcast = RPCBroadcastRequest(
    func_name="notify",
    params={"message": "System update"},
    destinations=[
        SyftBoxURL("syft://alice@example.com/app_data/notifier/rpc/notify"),
        SyftBoxURL("syft://bob@example.com/app_data/notifier/rpc/notify"),
        SyftBoxURL("syft://carol@example.com/app_data/notifier/rpc/notify"),
    ]
)
```

**RPCStatus** - Status of an RPC request:
```python
from syft_proxy.models import RPCStatus

status = RPCStatus(
    id="request-123",
    func_name="calculate",
    status="completed",         # pending, processing, completed, failed
    result={"result": 42},      # Function result
    error=None,                 # Error message if failed
    created_at=datetime.now(),
    completed_at=datetime.now()
)
```

### 2. Server Implementation

The server is built with FastAPI and provides a RESTful API:

```python
from syft_proxy.server import app
import uvicorn

# Run the server
uvicorn.run(app, host="0.0.0.0", port=8000)
```

**Key Features**:
- Asynchronous request handling
- In-memory request storage
- Automatic request forwarding
- Status tracking
- Schema discovery

### 3. CLI Interface

```bash
# Start the proxy server
syft-proxy serve --host 0.0.0.0 --port 8000 --reload

# Check server health
syft-proxy health --url http://localhost:8000

# Get server info
syft-proxy info --url http://localhost:8000

# Send a test request
syft-proxy test-request --url http://localhost:8000
```

## API Endpoints

### POST /rpc/send

Send an RPC request to another application:

```python
import httpx

client = httpx.Client()
response = client.post("http://localhost:8000/rpc/send", json={
    "app_name": "data_processor",
    "func_name": "process_data",
    "destination": "alice@example.com",
    "params": {
        "data": [1, 2, 3, 4, 5],
        "operation": "sum"
    },
    "blocking": True,
    "timeout": 60.0
})

result = response.json()
print(result)  # {"id": "req-123", "status": "completed", "result": 15}
```

**Non-blocking mode**:
```python
# Send without waiting
response = client.post("http://localhost:8000/rpc/send", json={
    "app_name": "background_job",
    "func_name": "start_job",
    "destination": "worker@example.com",
    "params": {"job_type": "cleanup"},
    "blocking": False  # Returns immediately
})

# Get request ID
request_id = response.json()["id"]

# Check status later
status_response = client.get(f"http://localhost:8000/rpc/status/{request_id}")
status = status_response.json()
```

### POST /rpc/broadcast

Send the same request to multiple destinations:

```python
response = client.post("http://localhost:8000/rpc/broadcast", json={
    "func_name": "update_config",
    "params": {"setting": "debug", "value": True},
    "destinations": [
        "syft://alice@example.com/app_data/config/rpc/update",
        "syft://bob@example.com/app_data/config/rpc/update",
        "syft://carol@example.com/app_data/config/rpc/update"
    ]
})

# Returns list of request IDs
request_ids = response.json()["request_ids"]
```

### GET /rpc/status/{request_id}

Check the status of an RPC request:

```python
response = client.get(f"http://localhost:8000/rpc/status/{request_id}")
status = response.json()

if status["status"] == "completed":
    print(f"Result: {status['result']}")
elif status["status"] == "failed":
    print(f"Error: {status['error']}")
elif status["status"] == "processing":
    print("Still processing...")
```

### GET /rpc/schema/{app_name}

Get the schema of available functions for an app:

```python
response = client.get("http://localhost:8000/rpc/schema/calculator")
schema = response.json()

# Example schema response
{
    "app_name": "calculator",
    "functions": {
        "add": {
            "params": {"a": "number", "b": "number"},
            "returns": "number",
            "description": "Add two numbers"
        },
        "multiply": {
            "params": {"a": "number", "b": "number"},
            "returns": "number",
            "description": "Multiply two numbers"
        }
    }
}
```

## Usage Patterns

### Basic Client Usage

```python
import httpx
from typing import Any, Dict

class ProxyClient:
    def __init__(self, proxy_url: str = "http://localhost:8000"):
        self.proxy_url = proxy_url
        self.client = httpx.Client()
    
    def call(self, app: str, func: str, destination: str, 
             params: Dict[str, Any], timeout: float = 30.0) -> Any:
        """Make a blocking RPC call."""
        response = self.client.post(
            f"{self.proxy_url}/rpc/send",
            json={
                "app_name": app,
                "func_name": func,
                "destination": destination,
                "params": params,
                "blocking": True,
                "timeout": timeout
            }
        )
        response.raise_for_status()
        
        result = response.json()
        if result["status"] == "failed":
            raise Exception(f"RPC failed: {result['error']}")
        
        return result["result"]
    
    def call_async(self, app: str, func: str, destination: str,
                   params: Dict[str, Any]) -> str:
        """Make a non-blocking RPC call."""
        response = self.client.post(
            f"{self.proxy_url}/rpc/send",
            json={
                "app_name": app,
                "func_name": func,
                "destination": destination,
                "params": params,
                "blocking": False
            }
        )
        response.raise_for_status()
        return response.json()["id"]
    
    def get_status(self, request_id: str) -> Dict[str, Any]:
        """Get status of an RPC request."""
        response = self.client.get(
            f"{self.proxy_url}/rpc/status/{request_id}"
        )
        response.raise_for_status()
        return response.json()

# Usage
proxy = ProxyClient()

# Blocking call
result = proxy.call(
    app="math_service",
    func="calculate",
    destination="alice@example.com",
    params={"expression": "2 + 2"}
)
print(f"Result: {result}")  # Result: 4

# Non-blocking call
request_id = proxy.call_async(
    app="report_generator",
    func="generate",
    destination="bob@example.com",
    params={"report_type": "monthly"}
)

# Check status later
import time
while True:
    status = proxy.get_status(request_id)
    if status["status"] in ["completed", "failed"]:
        break
    time.sleep(1)
```

### Service Discovery

```python
class ServiceRegistry:
    def __init__(self, proxy_url: str):
        self.proxy_url = proxy_url
        self.client = httpx.Client()
    
    def discover_services(self, app_names: List[str]) -> Dict[str, Any]:
        """Discover available services and their schemas."""
        services = {}
        
        for app in app_names:
            try:
                response = self.client.get(
                    f"{self.proxy_url}/rpc/schema/{app}"
                )
                if response.status_code == 200:
                    services[app] = response.json()
            except:
                pass
        
        return services
    
    def list_functions(self, app: str) -> List[str]:
        """List available functions for an app."""
        schema = self.discover_services([app]).get(app, {})
        return list(schema.get("functions", {}).keys())

# Usage
registry = ServiceRegistry("http://localhost:8000")
services = registry.discover_services(["calculator", "data_processor"])

for app, schema in services.items():
    print(f"\n{app}:")
    for func, details in schema["functions"].items():
        print(f"  - {func}: {details['description']}")
```

### Request Batching

```python
class BatchProcessor:
    def __init__(self, proxy_client: ProxyClient):
        self.proxy = proxy_client
    
    def batch_call(self, requests: List[Dict]) -> List[Any]:
        """Execute multiple RPC calls in parallel."""
        import concurrent.futures
        
        # Submit all requests
        request_ids = []
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = []
            for req in requests:
                future = executor.submit(
                    self.proxy.call_async,
                    req["app"],
                    req["func"],
                    req["destination"],
                    req["params"]
                )
                futures.append(future)
            
            # Collect request IDs
            for future in concurrent.futures.as_completed(futures):
                request_ids.append(future.result())
        
        # Wait for all results
        results = []
        for req_id in request_ids:
            while True:
                status = self.proxy.get_status(req_id)
                if status["status"] == "completed":
                    results.append(status["result"])
                    break
                elif status["status"] == "failed":
                    results.append({"error": status["error"]})
                    break
                time.sleep(0.1)
        
        return results

# Usage
batch = BatchProcessor(proxy)
results = batch.batch_call([
    {
        "app": "calculator",
        "func": "add",
        "destination": "alice@example.com",
        "params": {"a": 1, "b": 2}
    },
    {
        "app": "calculator",
        "func": "multiply",
        "destination": "alice@example.com",
        "params": {"a": 3, "b": 4}
    }
])
```

### Error Handling

```python
from enum import Enum

class RPCError(Exception):
    pass

class RPCTimeoutError(RPCError):
    pass

class RPCExecutionError(RPCError):
    pass

def safe_rpc_call(proxy: ProxyClient, **kwargs) -> Any:
    """Make an RPC call with comprehensive error handling."""
    try:
        # Start the call
        request_id = proxy.call_async(**kwargs)
        
        # Poll for result with timeout
        start_time = time.time()
        timeout = kwargs.get("timeout", 30.0)
        
        while time.time() - start_time < timeout:
            try:
                status = proxy.get_status(request_id)
                
                if status["status"] == "completed":
                    return status["result"]
                elif status["status"] == "failed":
                    raise RPCExecutionError(status["error"])
                
                time.sleep(0.5)
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    # Request not found, might be too early
                    time.sleep(0.5)
                    continue
                raise
        
        raise RPCTimeoutError(f"RPC call timed out after {timeout}s")
        
    except httpx.RequestError as e:
        raise RPCError(f"Network error: {e}")
    except Exception as e:
        raise RPCError(f"Unexpected error: {e}")

# Usage with error handling
try:
    result = safe_rpc_call(
        proxy,
        app="data_service",
        func="process",
        destination="processor@example.com",
        params={"data": large_dataset},
        timeout=120.0  # 2 minutes for large processing
    )
    print(f"Processing complete: {result}")
    
except RPCTimeoutError:
    print("Processing is taking too long")
except RPCExecutionError as e:
    print(f"Processing failed: {e}")
except RPCError as e:
    print(f"RPC error: {e}")
```

## Advanced Features

### Request Middleware

```python
from fastapi import Request, Response
from typing import Callable

class RequestLogger:
    async def __call__(self, request: Request, call_next: Callable):
        # Log request
        print(f"[{request.method}] {request.url}")
        
        # Process request
        response = await call_next(request)
        
        # Log response
        print(f"Response: {response.status_code}")
        
        return response

# Add middleware to app
app.add_middleware(RequestLogger)
```

### Custom Request Storage

```python
from abc import ABC, abstractmethod
from typing import Dict, Optional

class RequestStore(ABC):
    @abstractmethod
    async def save(self, request_id: str, data: dict) -> None:
        pass
    
    @abstractmethod
    async def get(self, request_id: str) -> Optional[dict]:
        pass
    
    @abstractmethod
    async def update(self, request_id: str, data: dict) -> None:
        pass

class RedisRequestStore(RequestStore):
    def __init__(self, redis_url: str):
        import redis
        self.redis = redis.from_url(redis_url)
    
    async def save(self, request_id: str, data: dict):
        import json
        self.redis.set(f"rpc:{request_id}", json.dumps(data), ex=3600)
    
    async def get(self, request_id: str) -> Optional[dict]:
        import json
        data = self.redis.get(f"rpc:{request_id}")
        return json.loads(data) if data else None
    
    async def update(self, request_id: str, data: dict):
        await self.save(request_id, data)
```

### Load Balancing

```python
class LoadBalancer:
    def __init__(self, proxy_urls: List[str]):
        self.proxy_urls = proxy_urls
        self.current = 0
    
    def get_next_proxy(self) -> str:
        """Round-robin load balancing."""
        proxy = self.proxy_urls[self.current]
        self.current = (self.current + 1) % len(self.proxy_urls)
        return proxy
    
    def call(self, **kwargs) -> Any:
        """Make RPC call through load-balanced proxies."""
        proxy_url = self.get_next_proxy()
        client = ProxyClient(proxy_url)
        return client.call(**kwargs)

# Usage
balancer = LoadBalancer([
    "http://proxy1:8000",
    "http://proxy2:8000",
    "http://proxy3:8000"
])

result = balancer.call(
    app="service",
    func="process",
    destination="worker@example.com",
    params={"data": "test"}
)
```

## Security Considerations

### Authentication

```python
from fastapi import Depends, HTTPException, Header
from typing import Optional

async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if not x_api_key or x_api_key != "expected-api-key":
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

# Protect endpoints
@app.post("/rpc/send", dependencies=[Depends(verify_api_key)])
async def send_rpc(request: RPCSendRequest):
    # Process request
    pass
```

### Request Validation

```python
from pydantic import validator

class SecureRPCSendRequest(RPCSendRequest):
    @validator("destination")
    def validate_destination(cls, v):
        # Validate email format
        if "@" not in v:
            raise ValueError("Invalid destination email")
        return v
    
    @validator("timeout")
    def validate_timeout(cls, v):
        # Limit maximum timeout
        if v > 300:  # 5 minutes max
            raise ValueError("Timeout too large")
        return v
    
    @validator("params")
    def validate_params_size(cls, v):
        # Limit params size
        import json
        if len(json.dumps(v)) > 1_000_000:  # 1MB max
            raise ValueError("Parameters too large")
        return v
```

### Rate Limiting

```python
from fastapi import Request
from collections import defaultdict
from datetime import datetime, timedelta

class RateLimiter:
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.requests = defaultdict(list)
    
    async def check_rate_limit(self, request: Request):
        client_ip = request.client.host
        now = datetime.now()
        minute_ago = now - timedelta(minutes=1)
        
        # Clean old requests
        self.requests[client_ip] = [
            req_time for req_time in self.requests[client_ip]
            if req_time > minute_ago
        ]
        
        # Check limit
        if len(self.requests[client_ip]) >= self.requests_per_minute:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        
        # Record request
        self.requests[client_ip].append(now)

# Use rate limiter
rate_limiter = RateLimiter()

@app.post("/rpc/send")
async def send_rpc(
    request: RPCSendRequest,
    req: Request,
    _: None = Depends(rate_limiter.check_rate_limit)
):
    # Process request
    pass
```

## Monitoring and Metrics

```python
from prometheus_client import Counter, Histogram, generate_latest
import time

# Define metrics
rpc_requests_total = Counter(
    'rpc_requests_total',
    'Total RPC requests',
    ['app_name', 'func_name', 'status']
)

rpc_request_duration = Histogram(
    'rpc_request_duration_seconds',
    'RPC request duration',
    ['app_name', 'func_name']
)

# Track metrics
class MetricsMiddleware:
    async def track_request(self, app_name: str, func_name: str, 
                          start_time: float, status: str):
        duration = time.time() - start_time
        
        rpc_requests_total.labels(
            app_name=app_name,
            func_name=func_name,
            status=status
        ).inc()
        
        rpc_request_duration.labels(
            app_name=app_name,
            func_name=func_name
        ).observe(duration)

# Expose metrics endpoint
@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

## Testing

```python
import pytest
from fastapi.testclient import TestClient
from syft_proxy.server import app

client = TestClient(app)

def test_send_rpc():
    response = client.post("/rpc/send", json={
        "app_name": "test_app",
        "func_name": "test_func",
        "destination": "test@example.com",
        "params": {"test": True},
        "blocking": False
    })
    
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["status"] == "pending"

def test_get_status():
    # First create a request
    send_response = client.post("/rpc/send", json={
        "app_name": "test_app",
        "func_name": "test_func",
        "destination": "test@example.com",
        "params": {},
        "blocking": False
    })
    
    request_id = send_response.json()["id"]
    
    # Get status
    status_response = client.get(f"/rpc/status/{request_id}")
    assert status_response.status_code == 200
    
    status = status_response.json()
    assert status["id"] == request_id
    assert status["status"] in ["pending", "processing", "completed", "failed"]

def test_invalid_request():
    response = client.post("/rpc/send", json={
        "app_name": "",  # Invalid empty app name
        "func_name": "test",
        "destination": "test@example.com",
        "params": {}
    })
    
    assert response.status_code == 422  # Validation error
```

## Best Practices

1. **Use non-blocking calls** for long-running operations
2. **Implement proper timeout handling** to avoid hanging requests
3. **Add retry logic** for transient failures
4. **Use batch operations** for multiple related calls
5. **Implement circuit breakers** for failing services
6. **Monitor request queues** to prevent overload
7. **Use compression** for large payloads
8. **Implement request deduplication** to prevent duplicate processing
9. **Add request tracing** for debugging distributed calls
10. **Use health checks** to ensure proxy availability

## Deployment

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "syft_proxy.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: syft-proxy
spec:
  replicas: 3
  selector:
    matchLabels:
      app: syft-proxy
  template:
    metadata:
      labels:
        app: syft-proxy
    spec:
      containers:
      - name: syft-proxy
        image: syft-proxy:latest
        ports:
        - containerPort: 8000
        env:
        - name: WORKERS
          value: "4"
        livenessProbe:
          httpGet:
            path: /
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: syft-proxy
spec:
  selector:
    app: syft-proxy
  ports:
  - port: 80
    targetPort: 8000
  type: LoadBalancer
```

### Configuration

Environment variables:
- `PROXY_HOST`: Host to bind to (default: 0.0.0.0)
- `PROXY_PORT`: Port to bind to (default: 8000)
- `PROXY_WORKERS`: Number of worker processes (default: 1)
- `PROXY_LOG_LEVEL`: Logging level (default: INFO)
- `PROXY_MAX_REQUESTS`: Max requests per worker (default: 1000)
- `PROXY_TIMEOUT`: Request timeout in seconds (default: 60)