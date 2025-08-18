"""
Key lifecycle security tests for X3DH implementation

These tests verify key management security properties:
- Key rotation procedures and security
- Key compromise scenario handling
- Secure key storage validation
- Key derivation and generation security
- Key lifecycle management
"""

import base64
import json
import platform
import stat
import tempfile
from pathlib import Path

import pytest
from loguru import logger
from syft_core import Client
from syft_crypto.did_utils import (
    get_did_document,
)
from syft_crypto.key_storage import (
    keys_exist,
    load_private_keys,
    private_key_path,
)
from syft_crypto.x3dh import decrypt_message, encrypt_message
from syft_crypto.x3dh_bootstrap import bootstrap_user

from tests.conftest import create_temp_client


def test_key_rotation_security(alice_client: Client, bob_client: Client) -> None:
    """Test key rotation lifecycle and security properties"""

    # Initial state: keys should exist and be loadable
    assert keys_exist(alice_client)
    original_identity, original_spk = load_private_keys(alice_client)
    original_did = get_did_document(alice_client, alice_client.config.email)

    # Send initial message before rotation
    original_message = "Message before key rotation"
    encrypted_before = encrypt_message(
        original_message, bob_client.config.email, alice_client
    )

    # Verify message works with current keys
    decrypted_before_rotation = decrypt_message(encrypted_before, bob_client)
    assert decrypted_before_rotation == original_message

    # Rotate Alice's keys (simulate by re-bootstrapping)
    bootstrap_user(alice_client, force=True)

    # Verify new keys are different from original
    new_identity, new_spk = load_private_keys(alice_client)
    new_did = get_did_document(alice_client, alice_client.config.email)
    assert original_identity.private_bytes_raw() != new_identity.private_bytes_raw()
    assert original_spk.private_bytes_raw() != new_spk.private_bytes_raw()
    assert original_did != new_did

    # Keys should still exist and be loadable after rotation
    assert keys_exist(alice_client)

    # New messages should use new keys
    new_message = "Message after key rotation"
    encrypted_after = encrypt_message(
        new_message, bob_client.config.email, alice_client
    )
    decrypted_new = decrypt_message(encrypted_after, bob_client)
    assert decrypted_new == new_message

    # The ephemeral keys should be different
    assert encrypted_before.ek != encrypted_after.ek

    # Test multiple rotations work correctly
    for _ in range(3):
        prev_identity, prev_spk = load_private_keys(alice_client)
        bootstrap_user(alice_client, force=True)
        curr_identity, curr_spk = load_private_keys(alice_client)

        # Each rotation should produce new keys
        assert prev_identity.private_bytes_raw() != curr_identity.private_bytes_raw()
        assert prev_spk.private_bytes_raw() != curr_spk.private_bytes_raw()

    # Note: Old messages encrypted before rotation won't decrypt after rotation
    # because the DID document now has new public keys. This is expected behavior
    # for forward secrecy - old messages become undecryptable after key rotation.


def test_key_storage_security(alice_client: Client) -> None:
    """Test that private keys are stored securely with proper permissions"""

    # Verify keys exist and get file path
    assert keys_exist(alice_client)
    key_file = private_key_path(alice_client)
    assert key_file.exists()

    # Check file permissions are restrictive (Unix-like systems only)
    if platform.system() != "Windows":
        file_mode = key_file.stat().st_mode
        # Should not be readable/writable by others
        assert not (file_mode & stat.S_IROTH), "Private keys should not be world-readable"
        assert not (file_mode & stat.S_IWOTH), "Private keys should not be world-writable"

    # Verify key file structure
    with open(key_file, "r") as f:
        key_data = json.load(f)

    # Check both required keys exist
    assert "identity_key" in key_data, "Missing identity key"
    assert "signed_prekey" in key_data, "Missing signed prekey"

    # Verify JWK format for both keys
    for key_type in ["identity_key", "signed_prekey"]:
        key = key_data[key_type]
        assert all(
            field in key for field in ["kty", "crv", "d", "x"]
        ), f"{key_type} missing required JWK fields"


def test_key_generation_entropy() -> None:
    """Test that key generation produces unique keys with sufficient entropy"""

    # Generate multiple key pairs and verify they're all different
    key_pairs = []

    for i in range(10):
        # Create temporary client for key generation
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "SyftBox"
            workspace.mkdir(parents=True, exist_ok=True)

            temp_client = create_temp_client(f"test_{i}@example.com", workspace)

            # Bootstrap with fresh keys
            bootstrap_user(temp_client)

            # Load the generated keys
            identity_key, spk_key = load_private_keys(temp_client)
            key_pairs.append(
                (identity_key.private_bytes_raw(), spk_key.private_bytes_raw())
            )

    # All keys should be unique
    identity_keys = {pair[0] for pair in key_pairs}
    spk_keys = {pair[1] for pair in key_pairs}

    assert len(identity_keys) == 10, "Identity keys not unique"
    assert len(spk_keys) == 10, "Signed prekeys not unique"


def test_key_backup_and_restore(alice_client: Client, bob_client: Client) -> None:
    """Test backup and restore functionality for private keys and DID documents"""

    # Send a message before backup
    original_message = "Message before backup"
    encrypted_before = encrypt_message(
        original_message, bob_client.config.email, alice_client
    )

    # Backup Alice's keys
    original_identity, original_spk = load_private_keys(alice_client)
    original_did = get_did_document(alice_client, alice_client.config.email)

    # Simulate key loss by removing key files
    key_file = private_key_path(alice_client)
    did_file = (
        alice_client.datasites / alice_client.config.email / "public" / "did.json"
    )

    # Backup files
    key_backup = key_file.read_bytes()
    did_backup = did_file.read_text()

    # Remove original files
    key_file.unlink()
    did_file.unlink()

    # Verify keys are gone
    assert not keys_exist(alice_client)

    # Restore from backup
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key_backup)

    did_file.parent.mkdir(parents=True, exist_ok=True)
    did_file.write_text(did_backup)

    # Verify restoration worked
    assert keys_exist(alice_client)

    restored_identity, restored_spk = load_private_keys(alice_client)
    restored_did = get_did_document(alice_client, alice_client.config.email)

    # Keys should be identical to originals
    assert (
        original_identity.private_bytes_raw() == restored_identity.private_bytes_raw()
    )
    assert original_spk.private_bytes_raw() == restored_spk.private_bytes_raw()
    assert original_did == restored_did

    # Should still be able to encrypt/decrypt
    new_message = "Message after restore"
    encrypted_after = encrypt_message(
        new_message, bob_client.config.email, alice_client
    )
    decrypted_after = decrypt_message(encrypted_after, bob_client)
    assert decrypted_after == new_message

    # Bob should still be able to decrypt old message
    decrypted_old = decrypt_message(encrypted_before, bob_client)
    assert decrypted_old == original_message


def test_key_validation(alice_client: Client) -> None:
    """Test that invalid keys are properly rejected"""

    # Test with corrupted key data
    key_file = private_key_path(alice_client)

    invalid_key_files = [
        # Invalid JSON
        "not json content",
        # Missing required fields
        '{"identity_key": {}}',
        # Invalid key format
        '{"identity_key": {"kty": "RSA"}, "signed_prekey": {"kty": "RSA"}}',
        # Empty file
        "",
    ]

    for invalid_content in invalid_key_files:
        # Write invalid content
        key_file.write_text(invalid_content)

        # Should fail to load keys
        with pytest.raises((ValueError, KeyError, json.JSONDecodeError)) as exc_info:
            load_private_keys(alice_client)

        # Log the exception that was caught
        logger.debug(
            f"Expected exception for invalid content '{invalid_content[:20]}...': {exc_info.value}"
        )


def test_key_size_validation(alice_client: Client) -> None:
    """Test that key sizes are validated"""

    # Load legitimate keys for reference
    identity_key, spk_key = load_private_keys(alice_client)

    # Verify expected key sizes
    assert len(identity_key.private_bytes_raw()) == 32  # Ed25519 private key
    assert len(identity_key.public_key().public_bytes_raw()) == 32  # Ed25519 public key

    assert len(spk_key.private_bytes_raw()) == 32  # X25519 private key
    assert len(spk_key.public_key().public_bytes_raw()) == 32  # X25519 public key


def test_did_signature_validation(alice_client: Client) -> None:
    """Test that DID document signatures are properly validated"""

    did_doc = get_did_document(alice_client, alice_client.config.email)
    identity_key, spk_key = load_private_keys(alice_client)

    # Extract signature from DID
    spk_jwk = did_doc["keyAgreement"][0]["publicKeyJwk"]

    # Verify the signature exists
    assert "signature" in spk_jwk

    # Test that signature verification works
    # Get the signed prekey public bytes
    spk_public_bytes = spk_key.public_key().public_bytes_raw()

    # Get the signature
    signature_b64 = spk_jwk["signature"]
    signature_bytes = base64.urlsafe_b64decode(signature_b64 + "===")

    # Verify with identity key
    identity_public_key = identity_key.public_key()

    # Should not raise exception
    identity_public_key.verify(signature_bytes, spk_public_bytes)


def test_secure_key_deletion(alice_client: Client) -> None:
    """Test that key files can be properly deleted"""
    # Verify keys exist initially
    assert keys_exist(alice_client)
    key_file = private_key_path(alice_client)
    assert key_file.exists()

    key_file.unlink()

    # Verify deletion
    assert not key_file.exists()
    assert not keys_exist(alice_client)

    # Should not be able to load keys
    with pytest.raises(FileNotFoundError):
        load_private_keys(alice_client)
