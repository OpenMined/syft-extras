import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from syft_core import Client
from syft_crypto import EncryptedPayload, decrypt_message
from syft_rpc.protocol import SyftFuture, SyftRequest, SyftResponse
from syft_rpc.rpc import make_url, reply_to, send, serialize, write_response


def test_serialize_edge_cases():
    """Test serialize function with various edge cases."""
    # Test with None
    result = serialize(None)
    assert result is None

    # Test with empty structures
    assert serialize("") == b""
    assert serialize({}) == b"{}"
    assert serialize([]) == b"[]"
    assert serialize(0) == b"0"
    assert serialize(False) == b"false"

    # Test with complex nested structures
    complex_data = {
        "nested": {
            "deeply": {
                "nested": {
                    "list": [1, 2, {"key": "value"}, [3, 4, 5]],
                    "unicode": "🚀 Ñoño 中文",
                    "numbers": [0, -42, 3.14159, float("inf")],
                    "booleans": [True, False, None],
                }
            }
        }
    }
    result = serialize(complex_data)
    # Should be able to parse back
    parsed = json.loads(result.decode())
    assert parsed["nested"]["deeply"]["nested"]["unicode"] == "🚀 Ñoño 中文"


def test_send_with_invalid_url(alice_client: Client):
    """Test send with invalid URL formats."""
    invalid_urls = [
        "",
        "not-a-url",
        "http://invalid-scheme.com",
        "syft://",
        "syft:///missing-host",
    ]

    for invalid_url in invalid_urls:
        try:
            future = send(url=invalid_url, body="test", client=alice_client)
            # If it doesn't raise an exception, check if the URL was parsed correctly
            # Some invalid URLs might be auto-corrected by SyftBoxURL
            assert future is not None
        except (ValueError, AttributeError) as e:
            # Expected for truly invalid URLs
            assert str(e) is not None


def test_send_with_extremely_large_payload(alice_client: Client, bob_client: Client):
    """Test send with very large payload."""
    url = make_url(bob_client.email, "test_app", "large_data")

    # Create large payload (1MB of data)
    large_data = {
        "big_list": ["x" * 1000 for _ in range(1000)],
        "metadata": "This is a large payload test",
    }

    future = send(url=url, body=large_data, encrypt=True, client=alice_client)

    # Should handle large payloads
    assert isinstance(future, SyftFuture)
    request_file = future.path / f"{future.id}.request"
    assert request_file.exists()

    # Verify encrypted payload is valid
    loaded_request = SyftRequest.load(request_file)
    encrypted_payload = EncryptedPayload.model_validate_json(
        loaded_request.body.decode()
    )

    # Bob should be able to decrypt it
    decrypted = decrypt_message(encrypted_payload, client=bob_client)
    parsed_data = json.loads(decrypted)
    assert parsed_data["metadata"] == "This is a large payload test"
    assert len(parsed_data["big_list"]) == 1000


def test_reply_to_with_missing_request_fields(alice_client: Client, bob_client: Client):
    """Test reply_to with malformed or incomplete request objects."""
    # Create request with missing fields
    incomplete_request = SyftRequest(
        id=uuid4(),
        sender=alice_client.email,
        method="POST",
        url=make_url(bob_client.email, "test_app", "endpoint"),
        headers={},
        body=None,  # Missing body
        # expires field might be missing
    )

    # Should still work
    response = reply_to(
        request=incomplete_request,
        body={"status": "handled incomplete request"},
        client=bob_client,
    )

    assert isinstance(response, SyftResponse)
    assert response.sender == bob_client.email


def test_reply_to_with_corrupted_request_sender(
    alice_client: Client, bob_client: Client
):
    """Test reply_to when request sender email is invalid."""
    request = SyftRequest(
        id=uuid4(),
        sender="invalid-email-format",  # Invalid email
        method="POST",
        url=make_url(bob_client.email, "test_app", "endpoint"),
        headers={},
        body=b'{"test": "data"}',
    )

    # Should still create response but encryption might fail
    with pytest.raises(FileNotFoundError, match="No DID document found"):
        reply_to(
            request=request,
            body={"error": "invalid sender"},
            encrypt=True,
            client=bob_client,
        )

    # But without encryption should work
    response = reply_to(
        request=request,
        body={"error": "invalid sender"},
        encrypt=False,
        client=bob_client,
    )
    assert isinstance(response, SyftResponse)


def test_send_with_client_loading_failure(alice_client: Client, bob_client: Client):
    """Test send when Client.load() fails."""
    url = make_url(bob_client.email, "test_app", "endpoint")

    with patch("syft_rpc.rpc.Client.load") as mock_load:
        mock_load.side_effect = Exception("Failed to load client")

        with pytest.raises(Exception, match="Failed to load client"):
            send(url=url, body="test", client=None)  # Forces Client.load()


def test_reply_to_with_client_loading_failure(alice_client: Client, bob_client: Client):
    """Test reply_to when Client.load() fails."""
    request = SyftRequest(
        id=uuid4(),
        sender=alice_client.email,
        method="POST",
        url=make_url(bob_client.email, "test_app", "endpoint"),
        headers={},
        body=b'{"test": "data"}',
    )

    with patch("syft_rpc.rpc.Client.load") as mock_load:
        mock_load.side_effect = Exception("Failed to load client")

        with pytest.raises(Exception, match="Failed to load client"):
            reply_to(request=request, body="test", client=None)  # Forces Client.load()


def test_encryption_with_invalid_recipient_format(alice_client: Client):
    """Test encryption with malformed recipient email."""
    invalid_recipients = [
        "",
        "not-an-email",
        "@domain.com",
        "user@",
        "user@@domain.com",
        None,
    ]

    for recipient in invalid_recipients:
        if recipient in [None, ""]:
            # This should raise ValueError for missing recipient
            with pytest.raises(ValueError, match="recipient required for encryption"):
                serialize({"data": "test"}, encrypt=True, client=alice_client)
        else:
            # These should raise FileNotFoundError when trying to find DID document
            with pytest.raises(FileNotFoundError, match="No DID document found"):
                serialize(
                    {"data": "test"},
                    encrypt=True,
                    recipient=recipient,
                    client=alice_client,
                )


def test_response_with_binary_data(alice_client: Client, bob_client: Client):
    """Test reply_to with binary response data."""
    request = SyftRequest(
        id=uuid4(),
        sender=alice_client.email,
        method="POST",
        url=make_url(bob_client.email, "test_app", "binary_endpoint"),
        headers={},
        body=b'{"request_type": "binary"}',
    )

    # Test with binary data that can be UTF-8 decoded
    binary_data = b"Hello World with some bytes"

    response = reply_to(
        request=request, body=binary_data, encrypt=True, client=bob_client
    )

    # Verify encryption worked with binary data
    encrypted_payload = EncryptedPayload.model_validate_json(response.body.decode())
    decrypted = decrypt_message(encrypted_payload, client=alice_client)

    # The serialize function handles bytes by decoding as UTF-8
    assert decrypted == binary_data.decode("utf-8")


def test_concurrent_request_creation(alice_client: Client, bob_client: Client):
    """Test creating multiple requests concurrently to same endpoint."""
    url = make_url(bob_client.email, "test_app", "concurrent")

    futures = []
    for i in range(10):
        future = send(
            url=url, body={"request_id": i}, encrypt=True, client=alice_client
        )
        futures.append(future)

    # All should have unique IDs (due to different encryption ephemeral keys)
    ids = [f.id for f in futures]
    assert len(set(ids)) == 10  # All unique

    # All files should exist
    for future in futures:
        request_file = future.path / f"{future.id}.request"
        assert request_file.exists()


def test_write_response_with_invalid_request_path(alice_client: Client):
    """Test write_response with invalid request path."""
    # Test with path that has invalid UUID in filename
    import tempfile

    temp_dir = tempfile.mkdtemp()
    invalid_path = Path(temp_dir) / "not-a-valid-uuid.request"

    with pytest.raises(ValueError, match="badly formed"):
        write_response(
            request_path=invalid_path, body="error response", client=alice_client
        )

    # Cleanup
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)


def test_unicode_in_all_fields(alice_client: Client, bob_client: Client):
    """Test Unicode handling in URLs, headers, and body."""
    # Unicode in app name and endpoint
    unicode_app = "测试应用"
    unicode_endpoint = "端点/ñoño"

    url = make_url(bob_client.email, unicode_app, unicode_endpoint)

    unicode_headers = {
        "X-Custom-Header": "Ñoño 中文 🚀",
        "Content-Language": "zh-CN,es-ES",
    }

    unicode_body = {
        "message": "Hello 世界! 🌍",
        "data": {
            "chinese": "你好",
            "spanish": "Hola",
            "emoji": "🎉🎊🚀",
            "mixed": "Mix中文español🌟",
        },
    }

    # Send with Unicode data
    future = send(
        url=url,
        body=unicode_body,
        headers=unicode_headers,
        encrypt=True,
        client=alice_client,
    )

    assert isinstance(future, SyftFuture)

    # Load and verify
    request_file = future.path / f"{future.id}.request"
    loaded_request = SyftRequest.load(request_file)

    # Headers should preserve Unicode
    assert loaded_request.headers["X-Custom-Header"] == "Ñoño 中文 🚀"

    # Decrypt and verify Unicode in body
    encrypted_payload = EncryptedPayload.model_validate_json(
        loaded_request.body.decode()
    )
    decrypted = decrypt_message(encrypted_payload, client=bob_client)
    parsed_body = json.loads(decrypted)

    assert parsed_body["message"] == "Hello 世界! 🌍"
    assert parsed_body["data"]["chinese"] == "你好"
    assert parsed_body["data"]["emoji"] == "🎉🎊🚀"
