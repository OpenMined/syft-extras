"""
This example demonstrates how to directly talk to Ollama, proxied through syft-http-bridge.
"""

from syft_http_bridge import create_syft_http_client

app_name = "ollama"
host = "eelco@openmined.org"

client = create_syft_http_client(app_name, host)

response = client.post(
    "/api/generate",
    json={
        "model": "llama3.2:1b",
        "prompt": "Why is the sky blue?",
        "stream": False,
    },
)

print(response.json()["response"])
