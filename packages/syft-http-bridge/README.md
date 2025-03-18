# Syft-http-bridge

`syft-http-bridge` is a library that provides a simple way connect HTTP 1.1 servers to syftbox' file-based communication.


## Usage

### Development Mode (with FastAPI)
```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Server-side
app = FastAPI()

@app.get("/hello")  
def hello():
    return {"message": "Hello, World!"}

# Client-side (same process)
client = TestClient(app)
response = client.get("/hello")
```

### Production over HTTP
```python
import httpx
import uvicorn
from fastapi import FastAPI

# Could be any HTTP 1.1 server
app = FastAPI()

@app.get("/hello")
def hello():
    return {"message": "Hello, World!"}

uvicorn.run(app, port=8000)
```

```python
# Client-side (direct HTTP, no SyftBox)
client = httpx.Client(base_url="http://localhost:8000")
response = client.get("/hello")
```

### Production with SyftBox
```python
# Server-side, start HTTP server

import httpx
import uvicorn
from fastapi import FastAPI
from syft_core import Client as SyftboxClient

app = FastAPI()

@app.get("/hello")
def hello():
    return {"message": "Hello, World!"}

uvicorn.run(app, port=8000)
```

```python
# Server-side, start SyftBox bridge

import httpx
from syft_http_bridge import SyftHttpBridge

# Set up the bridge
proxy_client = httpx.Client(base_url="http://localhost:8000")
bridge = SyftHttpBridge(
    app_name="my-app",
    http_client=proxy_client,
)

# Watch for file-based requests and forwards them to proxy_client
bridge.run_forever()
```

```python
# Client-side

from syft_http_bridge.client import create_syft_http_client

client = create_syft_http_client(
    app_name="my-app",
    host="user@openmined.org", # Datasite hosting the bridge
    syftbox_client=syftbox_client,
)

# Same HTTP interface, but uses file-based transport
response = client.get("/hello")
```

Each pattern uses the same API code but with different transport mechanisms - direct in-process calls, HTTP requests, or Syft's secure file-based communication.

## Access Control

You can restrict which endpoints the bridge will serve by using allow and deny lists:

```python
# Only allow specific endpoints
bridge = SyftHttpBridge(
    app_name="my-app",
    http_client=proxy_client,
    allowed_endpoints=["/hello", "/api/data"],  # Only these endpoints will be accessible
)

# Block specific endpoints
bridge = SyftHttpBridge(
    app_name="my-app",
    http_client=proxy_client,
    disallowed_endpoints=["/admin", "/internal"],  # These endpoints will be blocked
)