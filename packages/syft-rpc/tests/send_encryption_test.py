from unittest.mock import patch

import pytest
from syft_core import Client
from syft_crypto import EncryptedPayload, keys_exist
from syft_rpc.protocol import SyftFuture, SyftRequest
from syft_rpc.rpc import make_url, send


def test_send_without_encryption(alice_client: Client):
    """Test send() without encryption uses normal serialization (no encryption)."""
    url = make_url("recipient@domain.com", "test_app", "endpoint")
    body = {"message": "hello"}

    future = send(url=url, body=body, encrypt=False, client=alice_client)

    # Should return a SyftFuture
    assert isinstance(future, SyftFuture)
    assert future.request.body == b'{"message":"hello"}'
    assert future.request.sender == alice_client.email

    # Test that request file is written to future.path
    request_file = future.path / f"{future.id}.request"
    assert request_file.exists(), f"Request file should exist at {request_file}"

    # Verify the request file contains the correct unencrypted data
    loaded_request = SyftRequest.load(request_file)
    assert loaded_request.id == future.request.id
    assert loaded_request.body == b'{"message":"hello"}'  # Plain unencrypted body
    assert loaded_request.sender == alice_client.email


def test_send_with_encryption_success(alice_client: Client, bob_client: Client):
    """Test send() with encryption successfully encrypts body."""
    url = make_url(datasite=bob_client.email, app_name="test_app", endpoint="endpoint")
    body = {"message": "secret"}

    future = send(url=url, body=body, encrypt=True, client=alice_client)

    # Should return a SyftFuture with encrypted body
    assert isinstance(future, SyftFuture)
    assert future.request.body != b'{"message":"secret"}'  # Should be encrypted

    # Body should be a valid encrypted payload
    encrypted_payload = EncryptedPayload.model_validate_json(
        future.request.body.decode()
    )
    assert isinstance(encrypted_payload, EncryptedPayload)
    assert encrypted_payload.sender == alice_client.email
    assert encrypted_payload.receiver == bob_client.email

    # Test that request file is written to future.path
    request_file = future.path / f"{future.id}.request"
    assert request_file.exists(), f"Request file should exist at {request_file}"

    # Verify the request file contains the correct encrypted data
    loaded_request = SyftRequest.load(request_file)
    assert loaded_request.id == future.request.id
    assert loaded_request.body == future.request.body  # Same encrypted body
    assert loaded_request.sender == alice_client.email


def test_send_with_encryption_auto_client(alice_client: Client, bob_client: Client):
    """Test send() with encryption auto-loads client when not provided."""
    url = make_url(bob_client.email, "test_app", "endpoint")
    body = "Hello Bob my name is Alice!"

    with patch("syft_rpc.rpc.Client.load") as mock_load:
        mock_load.return_value = alice_client

        future = send(url=url, body=body, encrypt=True)  # No client provided

        # Should auto-load client
        mock_load.assert_called_once()
        assert isinstance(future, SyftFuture)


def test_send_with_encryption_custom_client(alice_client: Client, bob_client: Client):
    """Test send() uses provided custom client for encryption."""
    url = make_url(bob_client.email, "test_app", "endpoint")
    body = {"message": "secret"}

    with patch("syft_rpc.rpc.Client.load") as mock_load:
        future = send(url=url, body=body, encrypt=True, client=alice_client)

        # Should NOT auto-load client when one is provided
        mock_load.assert_not_called()
        assert future.request.sender == alice_client.email


def test_send_encryption_with_unbootstrapped_sender(
    unbootstrapped_client: Client, alice_client: Client
):
    """Test send() bootstraps sender automatically if needed."""
    url = make_url(alice_client.email, "test_app", "endpoint")
    body = {"message": "secret"}

    # Sender starts without keys
    assert not keys_exist(unbootstrapped_client)

    future = send(url=url, body=body, encrypt=True, client=unbootstrapped_client)

    # Should have bootstrapped the sender
    assert keys_exist(unbootstrapped_client)
    assert isinstance(future, SyftFuture)


def test_send_encryption_fails_without_recipient_keys(
    alice_client: Client, unbootstrapped_client: Client
):
    """Test send() fails when recipient's DID document is not available."""
    # Using unbootstrapped client's email as recipient (no DID document)
    url = make_url(unbootstrapped_client.email, "test_app", "endpoint")
    body = {"message": "secret"}

    with pytest.raises(FileNotFoundError, match="No DID document found"):
        send(url=url, body=body, encrypt=True, client=alice_client)
