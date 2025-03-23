"""
Before running, make sure Ollama is installed and running on http://localhost:11434 (default).
See: https://ollama.com/download

This example will use llama3.2:1b to generate text based on a prompt in client.py.
To download the model first, run: `ollama pull llama3.2:1b`

The script can also be run as a CLI application using the command:
```
pip install "syft-http-bridge[cli]"
syft-http-bridge \
    --app-name ollama \
    --base-url http://localhost:11434 \
    --allowed-endpoints /api/generate \
    --allowed-endpoints /api/chat
```
"""

import httpx
from syft_http_bridge import SyftHttpBridge

OLLAMA_URL = "http://localhost:11434"


if __name__ == "__main__":
    http_client = httpx.Client(base_url=OLLAMA_URL)

    # Only allow /api/generate and /api/chat endpoints
    # Other Ollama endpoints will return a 403 Forbidden
    ollama_bridge = SyftHttpBridge(
        app_name="ollama",
        http_client=http_client,
        allowed_endpoints=["/api/generate", "/api/chat"],
    )

    ollama_bridge.run_forever()
