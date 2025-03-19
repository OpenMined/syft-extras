"""
This example demonstrates how to directly talk to Ollama, proxied through syft-http-bridge.
"""

import httpx
from syft_http_bridge import create_syft_http_client

# The syft_client below can be directly swapped with the commented out direct_client
# The direct client communicates over http, while the syft_client communicates over syft filesync
# ollama_url = "http://localhost:11434"
# direct_client = httpx.Client(base_url=ollama_url)

app_name = "ollama"
host = "eelco@openmined.org"
syft_client = create_syft_http_client(app_name, host)

query = "Explain differential privacy in 1 paragraph."
response = syft_client.post(
    "/api/generate",
    json={
        "model": "llama3.2:1b",
        "prompt": query,
        "stream": False,
    },
    timeout=60,
)

print("Query:", query)
print("Ollama Response:", response.json()["response"])
print()
print()

# Query disallowed endpoint returns a 403 Forbidden
response = syft_client.get(
    "/api/admin/health",
)

assert response.status_code == 403
print("Disallowed endpoint returned:", response.status_code, response.json())
