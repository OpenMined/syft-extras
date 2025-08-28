import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from syft_core import Client
from syft_crypto import EncryptedPayload, decrypt_message, keys_exist
from syft_rpc.protocol import SyftRequest, SyftResponse, SyftStatus
from syft_rpc.rpc import make_url, reply_to


def test_reply_to_without_encryption(alice_client: Client, bob_client: Client):
    """Test reply_to() without encryption uses normal serialization."""
    # Create a mock request from Alice to Bob
    request = SyftRequest(
        id=uuid4(),
        sender=alice_client.email,
        method="POST",
        url=make_url(bob_client.email, "test_app", "endpoint"),
        headers={},
        body=b'{"query": "hello"}',
    )

    response_body = {"result": "world"}

    response = reply_to(
        request=request, body=response_body, encrypt=False, client=bob_client
    )

    # Should return a SyftResponse with unencrypted body
    assert isinstance(response, SyftResponse)
    assert response.body == b'{"result":"world"}'
    assert response.sender == bob_client.email
    assert response.id == request.id  # Same ID as original request
    assert response.status_code == SyftStatus.SYFT_200_OK

    # Verify the response file is written
    response_file = (
        response.url.to_local_path(bob_client.workspace.datasites)
        / f"{response.id}.response"
    )
    assert response_file.exists(), f"Response file should exist at {response_file}"


def test_reply_to_with_encryption_success(alice_client: Client, bob_client: Client):
    """Test reply_to() with encryption successfully encrypts response body."""
    # Create a mock request from Alice to Bob
    request = SyftRequest(
        id=uuid4(),
        sender=alice_client.email,  # Alice is the sender, so she should receive encrypted reply
        method="POST",
        url=make_url(bob_client.email, "test_app", "endpoint"),
        headers={},
        body=b'{"query": "secret_data"}',
    )

    response_body = {"result": "confidential_response"}

    response = reply_to(
        request=request, body=response_body, encrypt=True, client=bob_client
    )

    # Should return a SyftResponse with encrypted body
    assert isinstance(response, SyftResponse)
    assert response.body != b'{"result":"confidential_response"}'  # Should be encrypted
    assert response.sender == bob_client.email
    assert response.id == request.id

    # Body should be a valid encrypted payload
    encrypted_payload = EncryptedPayload.model_validate_json(response.body.decode())
    assert isinstance(encrypted_payload, EncryptedPayload)
    assert encrypted_payload.sender == bob_client.email  # Bob is replying
    assert encrypted_payload.receiver == alice_client.email  # Alice should receive it

    # Verify Alice can decrypt the response
    decrypted_message = decrypt_message(encrypted_payload, client=alice_client)
    assert decrypted_message == '{"result":"confidential_response"}'


def test_reply_to_with_encryption_auto_client(alice_client: Client, bob_client: Client):
    """Test reply_to() with encryption auto-loads client when not provided."""
    request = SyftRequest(
        id=uuid4(),
        sender=alice_client.email,
        method="GET",
        url=make_url(bob_client.email, "test_app", "endpoint"),
        headers={},
        body=None,
    )

    with patch("syft_rpc.rpc.Client.load") as mock_load:
        mock_load.return_value = bob_client

        response = reply_to(
            request=request,
            body="Encrypted reply",
            encrypt=True,  # No client provided
        )

        # Should auto-load client
        mock_load.assert_called_once()
        assert isinstance(response, SyftResponse)


def test_reply_to_with_encryption_custom_client(
    alice_client: Client, bob_client: Client
):
    """Test reply_to() uses provided custom client for encryption."""
    request = SyftRequest(
        id=uuid4(),
        sender=alice_client.email,
        method="POST",
        url=make_url(bob_client.email, "test_app", "endpoint"),
        headers={},
        body=b'{"message": "test"}',
    )

    with patch("syft_rpc.rpc.Client.load") as mock_load:
        response = reply_to(
            request=request,
            body={"reply": "encrypted"},
            encrypt=True,
            client=bob_client,
        )

        # Should NOT auto-load client when one is provided
        mock_load.assert_not_called()
        assert response.sender == bob_client.email


def test_reply_to_with_encryption_unbootstrapped_sender(
    alice_client: Client, unbootstrapped_client: Client
):
    """Test reply_to() bootstraps sender automatically if needed."""
    request = SyftRequest(
        id=uuid4(),
        sender=alice_client.email,
        method="POST",
        url=make_url(unbootstrapped_client.email, "test_app", "endpoint"),
        headers={},
        body=b'{"data": "test"}',
    )

    # Sender starts without keys
    assert not keys_exist(unbootstrapped_client)

    response = reply_to(
        request=request,
        body={"reply": "secret"},
        encrypt=True,
        client=unbootstrapped_client,
    )

    # Should have bootstrapped the sender
    assert keys_exist(unbootstrapped_client)
    assert isinstance(response, SyftResponse)


def test_reply_to_encryption_fails_without_recipient_keys(
    alice_client: Client, unbootstrapped_client: Client
):
    """Test reply_to() fails when recipient's DID document is not available."""
    # Request from unbootstrapped client (no DID document available)
    request = SyftRequest(
        id=uuid4(),
        sender=unbootstrapped_client.email,  # No DID document for this user
        method="POST",
        url=make_url(alice_client.email, "test_app", "endpoint"),
        headers={},
        body=b'{"message": "test"}',
    )

    with pytest.raises(FileNotFoundError, match="No DID document found"):
        reply_to(
            request=request, body={"reply": "secret"}, encrypt=True, client=alice_client
        )


def test_reply_to_different_status_codes(alice_client: Client, bob_client: Client):
    """Test reply_to() works with different HTTP status codes."""
    request = SyftRequest(
        id=uuid4(),
        sender=alice_client.email,
        method="POST",
        url=make_url(bob_client.email, "test_app", "endpoint"),
        headers={},
        body=b'{"request": "data"}',
    )

    test_cases = [
        (SyftStatus.SYFT_200_OK, {"success": True}),
        (SyftStatus.SYFT_403_FORBIDDEN, {"error": "Permission issue"}),
        (SyftStatus.SYFT_404_NOT_FOUND, {"error": "Request not found"}),
        (SyftStatus.SYFT_419_EXPIRED, {"error": "Request expired"}),
        (SyftStatus.SYFT_500_SERVER_ERROR, {"error": "Internal server error"}),
    ]

    for status_code, body in test_cases:
        response = reply_to(
            request=request,
            body=body,
            status_code=status_code,
            encrypt=True,
            client=bob_client,
        )

        assert response.status_code == status_code
        assert isinstance(response, SyftResponse)

        # Verify encryption worked
        encrypted_payload = EncryptedPayload.model_validate_json(response.body.decode())
        decrypted_message = decrypt_message(encrypted_payload, client=alice_client)
        assert json.loads(decrypted_message) == body


def test_reply_to_different_data_types_with_encryption(
    alice_client: Client, bob_client: Client
):
    """Test reply_to() encryption works with different serializable data types."""
    request = SyftRequest(
        id=uuid4(),
        sender=alice_client.email,
        method="POST",
        url=make_url(bob_client.email, "test_app", "endpoint"),
        headers={},
        body=b'{"request": "test"}',
    )

    test_cases = [
        "string response",
        b"bytes response",
        {"dict": "response"},
        [1, 2, 3, "list response"],
        42,
        3.14159,
        True,
        False,
        None,
        {"nested": {"deep": [1, 2, {"key": "encrypted_value"}]}},
        "Hello 👋 Encrypted World!",
        "Ñoño 中文 日本語",
        {"emoji": "🔐🔑"},
    ]

    for test_data in test_cases:
        response = reply_to(
            request=request, body=test_data, encrypt=True, client=bob_client
        )

        assert isinstance(response, SyftResponse)

        if test_data is None:
            # None should result in None body even with encryption
            assert response.body is None
            continue

        # Verify encryption worked and Alice can decrypt
        encrypted_payload = EncryptedPayload.model_validate_json(response.body.decode())
        decrypted_message = decrypt_message(encrypted_payload, client=alice_client)

        # Compare with expected serialized form
        from syft_rpc.rpc import serialize

        expected_serialized = serialize(test_data)
        assert decrypted_message == expected_serialized.decode()


def test_reply_to_with_custom_headers(alice_client: Client, bob_client: Client):
    """Test reply_to() preserves custom headers with encryption."""
    request = SyftRequest(
        id=uuid4(),
        sender=alice_client.email,
        method="GET",
        url=make_url(bob_client.email, "test_app", "endpoint"),
        headers={"Custom-Header": "request-value"},
        body=None,
    )

    custom_headers = {
        "Content-Type": "application/json",
        "X-Custom-Response": "encrypted-response",
        "Cache-Control": "no-cache",
    }

    response = reply_to(
        request=request,
        body={"data": "encrypted"},
        headers=custom_headers,
        encrypt=True,
        client=bob_client,
    )

    assert response.headers == custom_headers
    assert isinstance(response, SyftResponse)

    # Verify encryption still worked
    encrypted_payload = EncryptedPayload.model_validate_json(response.body.decode())
    assert encrypted_payload.sender == bob_client.email
    assert encrypted_payload.receiver == alice_client.email
