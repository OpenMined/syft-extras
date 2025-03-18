import httpx
from syft_http_bridge import SyftHttpBridge

ollama_url = "http://localhost:11434"


def run_server():
    http_client: httpx.Client = httpx.Client(base_url=ollama_url)

    ollama_bridge = SyftHttpBridge(
        app_name="ollama",
        http_client=http_client,
        allowed_endpoints=["/api/generate"],
    )

    ollama_bridge.run_forever()


if __name__ == "__main__":
    run_server()
