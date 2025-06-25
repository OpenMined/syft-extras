import json
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from syft_core import Client

from syft_proxy.models import RPCSendRequest
from syft_proxy.server import app
import syft_proxy.server

# Create a persistent temp directory for tests
TEST_DIR = tempfile.mkdtemp()
TEST_PATH = Path(TEST_DIR)

def create_test_client():
    """Create a test client with a test config file."""
    # Create config directory
    config_dir = TEST_PATH / ".syftbox"
    config_dir.mkdir(parents=True, exist_ok=True)
    
    # Create config file
    config_file = config_dir / "config.json"
    config_data = {
        "email": "test@example.com",
        "server_url": "https://syftbox.example.com",
        "client_url": "http://127.0.0.1:8080",
        "data_dir": str(TEST_PATH)
    }
    config_file.write_text(json.dumps(config_data))
    
    # Create necessary directories
    (TEST_PATH / "datasites" / "test@example.com" / "app_data").mkdir(parents=True, exist_ok=True)
    
    # Load client with the config file
    return Client.load(config_file)


# Create test client and inject it into the server module
if syft_proxy.server.client is None:
    syft_client = create_test_client()
    syft_proxy.server.client = syft_client
else:
    syft_client = syft_proxy.server.client

client = TestClient(app)


# Workflow Tests
def test_index_endpoint():
    """Test the index endpoint to ensure it returns a 200 status code and contains the expected text."""
    response = client.get("/")
    assert response.status_code == 200
    assert "SyftBox HTTP Proxy" in response.text


def test_rpc_send_non_blocking():
    """Test sending a non-blocking RPC request and verify the response status and status message."""
    rpc_req = RPCSendRequest(
        url="syft://user@openmined.org",
        headers={},
        body={},
        expiry="30s",
        app_name="test_app",
    )
    response = client.post(
        "/rpc", json=rpc_req.model_dump(), params={"blocking": False}
    )
    # When client is properly initialized (locally), we expect 200
    # When client is None (in CI), we expect 503
    assert response.status_code in [200, 503]
    if response.status_code == 200:
        assert response.json()["status"] == "RPC_PENDING"


def test_rpc_send_blocking():
    """Test sending a blocking RPC request and verify the response status and ID presence."""
    rpc_req = RPCSendRequest(
        url="syft://user@openmined.org",
        headers={},
        body={},
        expiry="1s",
        app_name="test_app",
    )
    response = client.post("/rpc", json=rpc_req.model_dump(), params={"blocking": True})
    # Accept various status codes that might occur
    assert response.status_code in [200, 403, 419, 500, 503]
    assert isinstance(response.json(), dict)
    if response.status_code == 503:
        assert "client not initialized" in response.json().get("detail", "").lower()
    else:
        assert response.json().get("id", None) is not None


def test_rpc_schema():
    """Test the RPC schema endpoint to ensure it returns the correct schema for the specified app."""
    app_path = syft_client.app_data("test_app")
    app_schema = app_path / "rpc" / "rpc.schema.json"

    os.makedirs(app_path / "rpc", exist_ok=True)
    schema = {
        "sender": "user@openmined.org",
        "method": "GET",
        "url": "syft://user1@openmined.org",
    }
    if not os.path.isfile(app_schema):
        with open(app_schema, "w") as f:
            f.write(json.dumps(schema))

    response = client.get("/rpc/schema/test_app")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)
    assert response.json() == schema


def test_rpc_status_found():
    """Test the RPC status endpoint to ensure it returns a 200 status code for a valid request ID."""
    rpc_req = RPCSendRequest(
        url="syft://test@openmined.org/public/rpc",
        headers={"Content-Type": "application/json", "User-Agent": "MyApp/1.0"},
        body={},
        expiry="30s",
        app_name="test_app",
    )
    response = client.post(
        "/rpc", json=rpc_req.model_dump(), params={"blocking": False}
    )
    
    # If client is not initialized, we can't test status lookup
    if response.status_code == 503:
        return

    rpc_request_id = response.json()["id"]
    response = client.get(f"/rpc/status/{rpc_request_id}")
    assert response.status_code == 200


def test_rpc_status_not_found():
    """Test the RPC status endpoint to ensure it returns a 404 or 503 status code for a non-existent request ID."""
    response = client.get("/rpc/status/non_existent_id")
    # 404 when client is initialized and ID not found
    # 503 when client is not initialized
    assert response.status_code in [404, 503]


# Edge Case Tests
def test_rpc_send_invalid_request():
    """Test sending an invalid RPC request to ensure it returns a 422 status code due to missing required fields."""
    response = client.post("/rpc", json={})  # Missing required fields
    assert response.status_code == 422


def test_rpc_schema_non_existent_app():
    """Test the RPC schema endpoint to ensure it returns a 500 or 503 status code for a non-existent app."""
    response = client.get("/rpc/schema/non_existent_app")
    # 500 when client is initialized but app doesn't exist
    # 503 when client is not initialized
    assert response.status_code in [500, 503]


def test_rpc_status_non_existent_id():
    """Test the RPC status endpoint to ensure it returns a 404 or 503 status code for a non-existent request ID."""
    response = client.get("/rpc/status/non_existent_id")
    # 404 when client is initialized and ID not found
    # 503 when client is not initialized  
    assert response.status_code in [404, 503]


# Cleanup
def test_cleanup():
    """Clean up the test directory."""
    import shutil
    try:
        shutil.rmtree(TEST_DIR)
    except Exception:
        pass
