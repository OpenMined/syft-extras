"""
This example demonstrates how to directly talk to Ollama, proxied through syft-http-bridge.
"""

import httpx
from syft_http_bridge import create_syft_http_client

# ollama_url = "http://localhost:11434"
# direct_client = httpx.Client(base_url=ollama_url)

app_name = "ollama"
host = "eelco@openmined.org"
syft_client = create_syft_http_client(app_name, host)

response = syft_client.post(
    "/api/generate",
    json={
        "model": "llama3.2:1b",
        "prompt": "Explain differential privacy in 1 paragraph.",
        "stream": False,
    },
    timeout=60,
)

print(response.json()["response"])
print()
print()

response = syft_client.get(
    "/api/admin/health",
)

print(response.status_code, response.json())
