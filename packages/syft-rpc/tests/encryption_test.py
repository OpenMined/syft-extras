import json
from unittest.mock import patch

import pytest
from pydantic import BaseModel
from syft_core import Client
from syft_crypto import EncryptedPayload, decrypt_message, keys_exist
from syft_rpc.rpc import serialize


def test_serialize_without_encryption():
    """Test that normal serialization works without encryption."""
    data = {"message": "hello world"}
    result = serialize(data)
    assert result == b'{"message":"hello world"}'


def test_serialize_with_encryption_missing_recipient(alice_client: Client):
    """Test that encryption fails without recipient."""
    data = {"message": "secret"}

    # Should fail without recipient even with valid client
    with pytest.raises(ValueError, match="recipient required for encryption"):
        serialize(data, encrypt=True, client=alice_client)


def test_serialize_with_encryption_success(alice_client: Client, bob_client: Client):
    """Test successful encryption flow with real clients."""
    data = {"message": "secret"}
    recipient = bob_client.email  # Use Bob's email as recipient

    encrypted_result: bytes = serialize(
        data, encrypt=True, recipient=recipient, client=alice_client
    )
    plain_result: bytes = serialize(data)

    # Should return encrypted bytes (JSON format) that's different from plain serialization
    assert isinstance(encrypted_result, bytes)
    assert encrypted_result != plain_result

    # Result should be valid JSON containing encrypted payload
    encrypted_payload: dict = json.loads(encrypted_result.decode())
    assert "ciphertext" in encrypted_payload


def test_serialize_with_encryption_auto_client(
    bob_client: Client, alice_client: Client
):
    """Test encryption with auto-loaded client (no client provided)."""
    with patch("syft_rpc.rpc.Client.load") as mock_load:
        mock_load.return_value = bob_client

        data = {"message": "secret"}

        result = serialize(data, encrypt=True, recipient=alice_client.email)

        # Should use auto-loaded client
        mock_load.assert_called_once()
        assert isinstance(result, bytes)
        assert result != b'{"message":"secret"}'

        assert json.loads(result.decode())["sender"] == bob_client.email


def test_serialize_with_encryption_unbootstrapped_sender(
    unbootstrapped_client: Client, alice_client: Client
):
    """Test encryption succeeds when sender's keys are not available since they will be automatically created."""
    data = {"message": "secret"}

    # Client starts without keys
    assert not keys_exist(unbootstrapped_client)

    result = serialize(
        data, encrypt=True, recipient=alice_client.email, client=unbootstrapped_client
    )

    # But the sender client should still have been bootstrapped during the attempt
    assert keys_exist(unbootstrapped_client)
    assert json.loads(result.decode())["sender"] == unbootstrapped_client.email


def test_serialize_with_encryption_unbootstrapped_receiver(
    unbootstrapped_client: Client, alice_client: Client
):
    """Test encryption fails when receiver's keys are not available."""
    data = {"message": "secret"}

    # Unbootstrapped client has no DID document (no public keys available)
    assert not keys_exist(unbootstrapped_client)

    # Should fail with FileNotFoundError when trying to find recipient's DID document
    with pytest.raises(FileNotFoundError, match="No DID document found"):
        serialize(
            data,
            encrypt=True,
            recipient=unbootstrapped_client.email,
            client=alice_client,
        )


def test_serialize_different_data_types_with_encryption(
    alice_client: Client, bob_client: Client
):
    """Test encryption works with different serializable data types."""
    test_cases = [
        # Basic types
        ("string", b"string"),
        (b"bytes", b"bytes"),
        ({"dict": "value"}, b'{"dict":"value"}'),
        ([1, 2, 3], b"[1, 2, 3]"),
        (42, b"42"),
        # Edge cases
        ("", b""),  # Empty string
        ({}, b"{}"),  # Empty dict
        ([], b"[]"),  # Empty list
        (0, b"0"),  # Zero value
        (None, None),  # None value (special case)
        # Complex nesting
        (
            {"nested": {"deep": [1, 2, {"key": "value"}]}},
            b'{"nested":{"deep":[1,2,{"key":"value"}]}}',
        ),
        # Special characters and UTF-8
        ("Hello 👋 World!", b"Hello \xf0\x9f\x91\x8b World!"),
        (
            "Ñoño 中文 日本語",
            b"\xc3\x91o\xc3\xb1o \xe4\xb8\xad\xe6\x96\x87 \xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e",
        ),
        ({"emoji": "🔐🔑"}, b'{"emoji":"\xf0\x9f\x94\x90\xf0\x9f\x94\x91"}'),
        # Numbers and booleans
        (3.14159, b"3.14159"),
        (-42, b"-42"),
        (True, b"true"),
        (False, b"false"),
    ]

    recipient = bob_client.email

    for original_data, expected_serialized in test_cases:
        # Skip None case as it returns None without encryption
        if original_data is None:
            result = serialize(
                None, encrypt=True, recipient=recipient, client=alice_client
            )
            assert result is None
            continue

        encrypted_result = serialize(
            original_data, encrypt=True, recipient=recipient, client=alice_client
        )
        plain_result = serialize(original_data)

        # Verify encryption produces different result than plain serialization
        assert encrypted_result != plain_result
        assert isinstance(encrypted_result, bytes)

        # Result should be valid JSON containing encrypted payload
        encrypted_payload: EncryptedPayload = EncryptedPayload.model_validate_json(
            encrypted_result.decode()
        )

        # Receiver decrypts and check with the expected value
        decrypted_result: str = decrypt_message(encrypted_payload, client=bob_client)
        assert decrypted_result == expected_serialized.decode()


def test_serialize_preserves_kwargs_for_pydantic(
    alice_client: Client, bob_client: Client
):
    """
    Test that non-encryption kwargs are still passed to pydantic serialization
    Verifies that the encryption feature doesn't break existing Pydantic functionality
    """

    class TestModel(BaseModel):
        value: str
        optional_field: str = "default"

    model_without_optional = TestModel(value="test")  # Uses default
    recipient = bob_client.email

    # Test exclude_unset - should exclude fields with default values
    result_exclude_unset = serialize(
        model_without_optional,
        encrypt=True,
        recipient=recipient,
        client=alice_client,
        exclude_unset=True,  # Should exclude optional_field since it wasn't set
    )

    # Test without exclude_unset - should include all fields
    result_include_all = serialize(
        model_without_optional,
        encrypt=True,
        recipient=recipient,
        client=alice_client,
        exclude_unset=False,
    )

    # Both should be encrypted
    assert isinstance(result_exclude_unset, bytes)
    assert isinstance(result_include_all, bytes)

    # Decrypt and verify the exclude_unset actually worked
    payload_exclude = EncryptedPayload.model_validate_json(
        result_exclude_unset.decode()
    )
    payload_include = EncryptedPayload.model_validate_json(result_include_all.decode())

    decrypted_exclude = decrypt_message(payload_exclude, client=bob_client)
    decrypted_include = decrypt_message(payload_include, client=bob_client)

    # The one with exclude_unset should be smaller (no optional_field)
    assert "optional_field" not in decrypted_exclude
    assert "optional_field" in decrypted_include
