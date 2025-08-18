"""
Tests system robustness against malformed inputs and edge cases for X3DH implementation

These tests verify resilience against various attack vectors:
- Malformed payload handling
- Resource exhaustion attacks
- Key validation edge cases
- Error information leakage
- Boundary condition attacks
"""

import random
import time

import pytest
from loguru import logger
from syft_core import Client
from syft_crypto.x3dh import EncryptedPayload, decrypt_message, encrypt_message


def test_malformed_payload_handling(bob_client: Client) -> None:
    """Test handling of various malformed payloads"""

    # Test cases with different types of malformed data
    malformed_payloads = [
        # Invalid base64 data
        {
            "ek": "invalid-base64-data",
            "iv": "YWJjZGVmZ2hpams=",
            "ciphertext": "dGVzdCBjaXBoZXJ0ZXh0",
            "tag": "dGVzdCB0YWcxMjM0NTY=",
            "sender": "test@example.com",
            "receiver": bob_client.email,
            "version": "1.0",
        },
        # Wrong field types
        {
            "ek": 12345,  # Should be string
            "iv": "YWJjZGVmZ2hpams=",
            "ciphertext": "dGVzdCBjaXBoZXJ0ZXh0",
            "tag": "dGVzdCB0YWcxMjM0NTY=",
            "sender": "test@example.com",
            "receiver": bob_client.email,
            "version": "1.0",
        },
        # Missing required fields
        {
            "iv": "YWJjZGVmZ2hpams=",
            "ciphertext": "dGVzdCBjaXBoZXJ0ZXh0",
            "tag": "dGVzdCB0YWcxMjM0NTY=",
            "sender": "test@example.com",
            "receiver": bob_client.email,
            "version": "1.0",
            # Missing 'ek' field
        },
        # Empty strings
        {
            "ek": "",
            "iv": "",
            "ciphertext": "",
            "tag": "",
            "sender": "",
            "receiver": "",
            "version": "",
        },
        # Null/None values
        {
            "ek": None,
            "iv": None,
            "ciphertext": None,
            "tag": None,
            "sender": None,
            "receiver": None,
            "version": None,
        },
    ]

    for i, payload_data in enumerate(malformed_payloads):
        logger.info(f"Testing malformed payload {i}: {payload_data}")

        # Each malformed payload should fail at some point
        failed = False

        try:
            # Try to create EncryptedPayload from malformed data
            malformed_payload = EncryptedPayload.model_validate(payload_data)

            # If creation succeeds, try decryption (should fail)
            decrypt_message(malformed_payload, bob_client)

            # If we get here, the test should fail
            pytest.fail(
                f"Malformed payload {i} should have failed but didn't: {payload_data}"
            )

        except (ValueError, TypeError, AttributeError, KeyError) as e:
            # Expected - malformed payload should fail
            logger.debug(e)
            failed = True
        except Exception as e:
            # Unexpected exception type, but still a failure
            logger.debug(e)
            failed = True

        # Ensure the payload actually failed
        assert failed, f"Malformed payload {i} should have failed: {payload_data}"


def test_oversized_payload_handling(alice_client: Client, bob_client: Client) -> None:
    """Test handling of extremely large payloads"""

    # Test with progressively larger messages
    large_sizes = [1024, 10240, 102400]  # 1KB, 10KB, 100KB

    for size in large_sizes:
        # Create a large message
        large_message = "A" * size

        try:
            # Should handle large messages gracefully
            encrypted = encrypt_message(large_message, bob_client.email, alice_client)
            decrypted = decrypt_message(encrypted, bob_client)
            assert decrypted == large_message

        except MemoryError:
            # If we hit memory limits, that's acceptable
            pytest.skip(f"Memory limit reached at {size} bytes")
        except ValueError as e:
            # If implementation has size limits, that's acceptable
            logger.debug(e)


def test_rapid_encryption_requests(alice_client: Client, bob_client: Client) -> None:
    """
    This test verifies that the cryptographic system can handle multiple encryption requests
    in a short period of time without significant performance degradation.
    """

    # Perform many encryptions rapidly
    num_requests = 50
    messages = []
    encrypted_messages = []

    start_time = time.time()

    for i in range(num_requests):
        message = f"Rapid test message {i}"
        encrypted = encrypt_message(message, bob_client.email, alice_client)
        messages.append(message)
        encrypted_messages.append(encrypted)

    end_time = time.time()

    # Should complete within reasonable time (adjust threshold as needed)
    time_per_encryption = (end_time - start_time) / num_requests
    assert (
        time_per_encryption < 1.0
    ), f"Encryption too slow: {time_per_encryption}s per message"

    # All messages should decrypt correctly
    for original, encrypted in zip(messages, encrypted_messages):
        decrypted = decrypt_message(encrypted, bob_client)
        assert decrypted == original


def test_invalid_key_sizes(alice_client: Client, bob_client: Client) -> None:
    """Test handling of invalid key sizes in payloads"""

    # Create a legitimate message first
    message = "Key size test"
    encrypted = encrypt_message(message, bob_client.email, alice_client)

    # Test with various invalid key sizes
    invalid_key_sizes = [
        # Too short
        b"short",
        b"x" * 16,  # Half size
        # Too long
        b"x" * 64,  # Double size
        b"x" * 100,  # Much too long
        # Empty
        b"",
    ]

    for invalid_key in invalid_key_sizes:
        tampered = encrypted.model_copy()
        tampered.ek = invalid_key

        with pytest.raises(ValueError):
            decrypt_message(tampered, bob_client)


def test_invalid_iv_sizes(alice_client: Client, bob_client: Client) -> None:
    """Test handling of invalid IV sizes"""

    message = "IV size test"
    encrypted = encrypt_message(message, bob_client.email, alice_client)

    # Test various invalid IV sizes for AES-GCM
    invalid_ivs = [
        b"short",  # Too short
        b"x" * 8,  # Too short for GCM
        b"x" * 16,  # Wrong size for GCM (should be 12)
        b"x" * 24,  # Too long
        b"",  # Empty
    ]

    for invalid_iv in invalid_ivs:
        tampered = encrypted.model_copy()
        tampered.iv = invalid_iv

        with pytest.raises(ValueError):
            decrypt_message(tampered, bob_client)


def test_invalid_tag_sizes(alice_client: Client, bob_client: Client) -> None:
    """Test handling of invalid authentication tag sizes"""

    message = "Tag size test"
    encrypted = encrypt_message(message, bob_client.email, alice_client)

    # Test various invalid tag sizes for AES-GCM
    invalid_tags = [
        b"short",  # Too short
        b"x" * 8,  # Too short
        b"x" * 12,  # Still too short
        b"x" * 24,  # Too long
        b"",  # Empty
    ]

    for invalid_tag in invalid_tags:
        tampered = encrypted.model_copy()
        tampered.tag = invalid_tag

        with pytest.raises(ValueError):
            decrypt_message(tampered, bob_client)


def test_random_data_injection(alice_client: Client, bob_client: Client) -> None:
    """Test resilience against random data injection"""

    message = "Random data test"
    encrypted = encrypt_message(message, bob_client.email, alice_client)

    # Test injecting random data into different fields
    fields_to_test = ["ek", "iv", "ciphertext", "tag"]

    for field in fields_to_test:
        for _ in range(10):  # Test multiple random values per field
            # Generate random bytes
            random_length = random.randint(1, 64)
            random_data = bytes(random.randint(0, 255) for _ in range(random_length))

            tampered = encrypted.model_copy()
            setattr(tampered, field, random_data)

            with pytest.raises(ValueError):
                decrypt_message(tampered, bob_client)


def test_error_message_information_leakage(
    alice_client: Client, bob_client: Client
) -> None:
    """
    This test verifies that the cryptographic system does not leak sensitive information
    through error messages.
    """

    message = "Error leakage test"
    encrypted = encrypt_message(message, bob_client.email, alice_client)

    # Test various tampering scenarios and check error messages
    tampering_tests = [
        ("ek", b"wrong_key_data"),
        ("iv", b"wrong_iv_data"),
        ("tag", b"wrong_tag_data"),
        ("ciphertext", b"wrong_ciphertext"),
    ]

    for field, wrong_data in tampering_tests:
        tampered = encrypted.model_copy()
        setattr(tampered, field, wrong_data)

        try:
            decrypt_message(tampered, bob_client)
            pytest.fail(f"Tampering with {field} should have failed")
        except ValueError as e:
            logger.debug(f"Error message: {e}")
            error_msg = str(e).lower()

            # Error message should not contain actual key values or user emails
            sensitive_patterns = [
                "secret",  # Avoid leaking secret information
                "private",  # Avoid leaking private key values
                bob_client.email.lower(),  # Avoid leaking email
                alice_client.email.lower(),  # Avoid leaking email
            ]

            # Check for sensitive information
            for pattern in sensitive_patterns:
                assert (
                    pattern not in error_msg
                ), f"Error message may leak information: '{error_msg}'"


def test_zero_length_components(alice_client: Client, bob_client: Client) -> None:
    """Test handling of zero-length cryptographic components"""

    message = "Zero length test"
    encrypted = encrypt_message(message, bob_client.email, alice_client)

    # Test zero-length components
    zero_length_tests = ["ek", "iv", "ciphertext", "tag"]

    for field in zero_length_tests:
        tampered = encrypted.model_copy()
        setattr(tampered, field, b"")

        with pytest.raises(ValueError):
            decrypt_message(tampered, bob_client)


def test_boundary_conditions(alice_client: Client, bob_client: Client) -> None:
    """Test boundary conditions in cryptographic parameters by checking:

    1. Correct sizes - Verifies that components with exactly the right byte sizes (32 for X25519 key, 12 for AES-GCM IV, 16
    for authentication tag) still fail when containing invalid data
    2. Off-by-one errors - Ensures the system rejects components that are one byte too short or too long, catching common
    boundary bug
    """

    message = "Boundary test"
    encrypted = encrypt_message(message, bob_client.email, alice_client)

    # Test boundary values for different components
    boundary_tests = [
        # Exactly correct sizes (should work)
        ("ek", 32),  # X25519 key size
        ("iv", 12),  # AES-GCM IV size
        ("tag", 16),  # AES-GCM tag size
        # Off-by-one errors (should fail)
        ("ek", 31),  # One byte short
        ("ek", 33),  # One byte long
        ("iv", 11),  # One byte short
        ("iv", 13),  # One byte long
        ("tag", 15),  # One byte short
        ("tag", 17),  # One byte long
    ]

    for field, size in boundary_tests:
        test_data = b"x" * size
        tampered = encrypted.model_copy()
        setattr(tampered, field, test_data)

        if size in [32, 12, 16] and field in ["ek", "iv", "tag"]:
            # Correct sizes should still fail due to wrong data, but with different error
            with pytest.raises(ValueError):
                decrypt_message(tampered, bob_client)
        else:
            # Incorrect sizes should fail
            with pytest.raises(ValueError):
                decrypt_message(tampered, bob_client)
