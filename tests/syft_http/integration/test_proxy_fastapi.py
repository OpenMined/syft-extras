import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from syft_http.bridge import FileSystemProxy, SerializedHttpProxy
from syft_http.client import FileSystemTransport
from syft_http.serde import (
    deserialize_request,
    deserialize_response,
    serialize_request,
    serialize_response,
)


@pytest.fixture
def app():
    app = FastAPI()

    @app.get("/hello")
    def read_hello():
        return {"message": "Hello World"}

    return app


@pytest.fixture
def test_client(app):
    return TestClient(app)


@pytest.fixture
def test_dirs(tmp_path):
    requests_dir = tmp_path / "requests"
    responses_dir = tmp_path / "responses"
    requests_dir.mkdir()
    responses_dir.mkdir()
    return requests_dir, responses_dir


def test_http_proxy_with_fastapi(test_client):
    responses = {}

    def response_handler(request_id, serialized_response):
        responses[request_id] = serialized_response

    proxy = SerializedHttpProxy(
        response_handler=response_handler,
        proxy_client=test_client,
    )

    request_id = uuid.uuid4()
    request = httpx.Request("GET", "http://testserver/hello")
    serialized_request = serialize_request(request)

    proxy.handle_request(request_id, serialized_request)

    assert request_id in responses, "No response received for request"
    response = deserialize_response(responses[request_id])

    assert response.status_code == 200
    assert response.json() == {"message": "Hello World"}


def test_filesystem_proxy_with_fastapi(test_client, test_dirs):
    requests_dir, responses_dir = test_dirs

    fs_proxy = FileSystemProxy(
        requests_dir=requests_dir,
        responses_dir=responses_dir,
        client=test_client,
    )

    request_id = uuid.uuid4()
    request = httpx.Request("GET", "http://testserver/hello")
    serialized_request = serialize_request(request)

    request_path = requests_dir / f"{request_id}.request"
    request_path.write_bytes(serialized_request)

    fs_proxy._process_existing_files()

    response_path = responses_dir / f"{request_id}.response"
    assert response_path.exists(), "Response file not found"

    serialized_response = response_path.read_bytes()
    response = deserialize_response(serialized_response)

    assert response.status_code == 200
    assert response.json() == {"message": "Hello World"}


def test_filesystem_transport_with_fastapi(test_client, test_dirs):
    requests_dir, responses_dir = test_dirs

    transport = FileSystemTransport(
        requests_dir=requests_dir,
        responses_dir=responses_dir,
        timeout=2.0,
    )

    request = httpx.Request("GET", "http://testserver/hello")

    def process_request_files():
        start_time = time.time()
        while time.time() - start_time < 3.0:
            for request_path in requests_dir.glob("*.request"):
                try:
                    request_id = uuid.UUID(request_path.stem)
                    serialized_request = request_path.read_bytes()
                    request_obj = deserialize_request(serialized_request)
                    response = test_client.send(request_obj)
                    serialized_response = serialize_response(response)
                    response_path = responses_dir / f"{request_id}.response"
                    response_path.write_bytes(serialized_response)
                    request_path.unlink()
                except Exception as e:
                    print(f"Error processing request file: {e}")
            time.sleep(0.1)

    monitor_thread = threading.Thread(target=process_request_files)
    monitor_thread.daemon = True
    monitor_thread.start()

    try:
        response = transport.handle_request(request)
        assert response.status_code == 200
        assert response.json() == {"message": "Hello World"}
    finally:
        monitor_thread.join(timeout=1.0)
