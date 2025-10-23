"""
Test bootstrap functionality for X3DH key generation
"""

import json
import shutil
from pathlib import Path
from typing import Any, Dict

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from syft_core import Client
from syft_crypto.did_utils import (
    did_path,
    generate_did_web_id,
    get_did_document,
    save_did_document,
)
from syft_crypto.key_storage import (
    key_to_jwk,
    keys_exist,
    load_private_keys,
    private_key_path,
    save_private_keys,
)
from syft_crypto.x3dh import EncryptedPayload, decrypt_message, encrypt_message
from syft_crypto.x3dh_bootstrap import bootstrap_user, ensure_bootstrap

from tests.conftest import create_temp_client


def test_bootstrap_private_keys(unbootstrapped_client: Client) -> None:
    """Test that bootstrap creates all necessary files"""
    client: Client = unbootstrapped_client

    # Verify no keys exist initially
    assert not keys_exist(client)
    assert not did_path(client).exists()

    # Bootstrap
    result: bool = bootstrap_user(client)
    assert result is True

    # Verify keys were created
    assert keys_exist(client)
    assert did_path(client).exists()

    # Verify private key file structure
    key_file: Path = private_key_path(client)
    with open(key_file, "r") as f:
        keys_data: Dict[str, Any] = json.load(f)

    assert "identity_key" in keys_data
    assert "signed_prekey" in keys_data
    assert keys_data["identity_key"]["kty"] == "OKP"
    assert keys_data["signed_prekey"]["kty"] == "OKP"
    assert keys_data["identity_key"]["crv"] == "Ed25519"
    assert keys_data["signed_prekey"]["crv"] == "X25519"


def test_bootstrap_creates_valid_did_document(unbootstrapped_client: Client) -> None:
    """Test that bootstrap creates a valid DID document"""
    client: Client = unbootstrapped_client
    bootstrap_user(client)

    # Load and verify DID document
    did_doc: Dict[str, Any] = get_did_document(client, client.config.email)

    # Check structure
    assert "@context" in did_doc
    assert "id" in did_doc
    assert "verificationMethod" in did_doc
    assert "keyAgreement" in did_doc

    # Check DID ID
    expected_did: str = generate_did_web_id(
        client.config.email, client.config.server_url.host
    )
    assert did_doc["id"] == expected_did

    # Check verification method (identity key)
    assert len(did_doc["verificationMethod"]) == 1
    vm: Dict[str, Any] = did_doc["verificationMethod"][0]
    assert vm["type"] == "Ed25519VerificationKey2020"
    assert "publicKeyJwk" in vm
    assert vm["publicKeyJwk"]["kty"] == "OKP"
    assert vm["publicKeyJwk"]["crv"] == "Ed25519"

    # Check key agreement (signed prekey)
    assert len(did_doc["keyAgreement"]) == 1
    ka: Dict[str, Any] = did_doc["keyAgreement"][0]
    assert ka["type"] == "X25519KeyAgreementKey2020"
    assert "publicKeyJwk" in ka
    assert ka["publicKeyJwk"]["kty"] == "OKP"
    assert ka["publicKeyJwk"]["crv"] == "X25519"
    assert "signature" in ka["publicKeyJwk"]


def test_bootstrap_idempotent(unbootstrapped_client: Client) -> None:
    """Test that bootstrap doesn't overwrite existing keys"""
    client: Client = unbootstrapped_client

    # First bootstrap
    result1: bool = bootstrap_user(client)
    assert result1 is True

    # Load original DID
    original_did: Dict[str, Any] = get_did_document(client, client.config.email)

    # Second bootstrap (should not regenerate)
    result2: bool = bootstrap_user(client)
    assert result2 is False

    # Verify DID unchanged
    current_did: Dict[str, Any] = get_did_document(client, client.config.email)
    assert original_did == current_did


def test_bootstrap_force_regenerate(unbootstrapped_client: Client) -> None:
    """Test force regeneration of keys"""
    client: Client = unbootstrapped_client

    # First bootstrap
    bootstrap_user(client)
    original_did: Dict[str, Any] = get_did_document(client, client.config.email)

    # Force regenerate
    result: bool = bootstrap_user(client, force=True)
    assert result is True

    # Verify DID changed (new keys)
    new_did: Dict[str, Any] = get_did_document(client, client.config.email)
    assert (
        new_did["verificationMethod"][0]["publicKeyJwk"]
        != original_did["verificationMethod"][0]["publicKeyJwk"]
    )
    assert (
        new_did["keyAgreement"][0]["publicKeyJwk"]
        != original_did["keyAgreement"][0]["publicKeyJwk"]
    )


def test_ensure_bootstrap(unbootstrapped_client: Client) -> None:
    """Test ensure_bootstrap creates keys if missing"""
    client: Client = unbootstrapped_client

    # No keys initially
    assert not keys_exist(client)

    # Ensure bootstrap
    returned_client: Client = ensure_bootstrap(client)

    # Should return same client
    assert returned_client == client

    # Keys should exist now
    assert keys_exist(client)


def test_ensure_bootstrap_preserves_existing(alice_client: Client) -> None:
    """Test ensure_bootstrap doesn't regenerate existing keys"""
    # Alice already has keys from fixture
    original_did: Dict[str, Any] = get_did_document(
        alice_client, alice_client.config.email
    )

    # Ensure bootstrap
    ensure_bootstrap(alice_client)

    # Keys should be unchanged
    current_did: Dict[str, Any] = get_did_document(
        alice_client, alice_client.config.email
    )
    assert current_did == original_did


def test_key_signature_verification(alice_client: Client) -> None:
    """Test that signed prekey has valid signature"""
    import base64

    from cryptography.hazmat.primitives.asymmetric import ed25519

    # Load DID document
    did_doc: Dict[str, Any] = get_did_document(alice_client, alice_client.config.email)

    # Extract identity public key
    identity_jwk: Dict[str, Any] = did_doc["verificationMethod"][0]["publicKeyJwk"]
    identity_key_bytes: bytes = base64.urlsafe_b64decode(identity_jwk["x"] + "===")
    identity_public_key: ed25519.Ed25519PublicKey = (
        ed25519.Ed25519PublicKey.from_public_bytes(identity_key_bytes)
    )

    # Extract signed prekey and signature
    spk_jwk: Dict[str, Any] = did_doc["keyAgreement"][0]["publicKeyJwk"]
    spk_bytes: bytes = base64.urlsafe_b64decode(spk_jwk["x"] + "===")
    signature: bytes = base64.urlsafe_b64decode(spk_jwk["signature"] + "===")

    # Verify signature
    try:
        identity_public_key.verify(signature, spk_bytes)
        # If no exception, signature is valid
        assert True
    except Exception:
        pytest.fail("Signed prekey signature verification failed")


def test_save_and_load_private_keys(unbootstrapped_client: Client) -> None:
    """Test saving and loading private keys"""
    from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

    client: Client = unbootstrapped_client

    # Generate test keys
    identity_key: ed25519.Ed25519PrivateKey = ed25519.Ed25519PrivateKey.generate()
    spk_key: x25519.X25519PrivateKey = x25519.X25519PrivateKey.generate()

    # Save keys
    save_path: Path = save_private_keys(client, identity_key, spk_key)
    assert save_path.exists()

    # Load keys back
    loaded_identity: ed25519.Ed25519PrivateKey
    loaded_spk: x25519.X25519PrivateKey
    loaded_identity, loaded_spk = load_private_keys(client)

    # Verify they work (can't directly compare private keys)
    # So we compare public keys instead
    assert (
        loaded_identity.public_key().public_bytes_raw()
        == identity_key.public_key().public_bytes_raw()
    )
    assert (
        loaded_spk.public_key().public_bytes_raw()
        == spk_key.public_key().public_bytes_raw()
    )


@pytest.mark.parametrize(
    "key_type,expected_use",
    [
        ("ed25519", "sig"),
        ("x25519", "enc"),
    ],
)
def test_key_to_jwk(key_type: str, expected_use: str) -> None:
    """Test key to JWK conversion"""
    from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

    if key_type == "ed25519":
        key: ed25519.Ed25519PublicKey = (
            ed25519.Ed25519PrivateKey.generate().public_key()
        )
        expected_crv: str = "Ed25519"
    else:
        key: x25519.X25519PublicKey = x25519.X25519PrivateKey.generate().public_key()
        expected_crv = "X25519"

    jwk: Dict[str, Any] = key_to_jwk(key, f"test-{key_type}")

    assert jwk["kty"] == "OKP"
    assert jwk["crv"] == expected_crv
    assert jwk["kid"] == f"test-{key_type}"
    assert jwk["use"] == expected_use
    assert "x" in jwk


def test_generate_did_web_id() -> None:
    """Test DID web ID generation"""
    did: str = generate_did_web_id("test@example.com", "syftbox.net")
    assert did == "did:web:syftbox.net:test%40example.com"

    # Test with special characters
    did = generate_did_web_id("test+user@example.com", "custom.domain")
    assert did == "did:web:custom.domain:test%2Buser%40example.com"


def test_did_path(alice_client: Client) -> None:
    """Test DID path generation"""
    path: Path = did_path(alice_client)
    expected: Path = (
        alice_client.datasites / alice_client.config.email / "public" / "did.json"
    )
    assert path == expected

    # Test with specific user
    path = did_path(alice_client, "bob@example.com")
    expected = alice_client.datasites / "bob@example.com" / "public" / "did.json"
    assert path == expected


def test_save_and_get_did_document(unbootstrapped_client: Client) -> None:
    """Test saving and retrieving DID documents"""
    client: Client = unbootstrapped_client

    # Create a test DID document
    test_did: Dict[str, Any] = {
        "@context": ["https://www.w3.org/ns/did/v1"],
        "id": f"did:web:test:{client.config.email}",
        "test": "document",
    }

    # Save it
    save_path: Path = save_did_document(client, test_did)
    assert save_path.exists()

    # Retrieve it
    retrieved: Dict[str, Any] = get_did_document(client, client.config.email)
    assert retrieved == test_did


def test_get_did_document_not_found(unbootstrapped_client: Client) -> None:
    """Test error when DID document doesn't exist"""
    with pytest.raises(FileNotFoundError, match="No DID document found"):
        get_did_document(unbootstrapped_client, "nonexistent@example.com")


def test_did_document_field_validation(alice_client: Client) -> None:
    """Test that DID document fields are properly validated"""
    did_doc = get_did_document(alice_client, alice_client.config.email)

    # Test context validation
    assert "@context" in did_doc
    assert "https://www.w3.org/ns/did/v1" in did_doc["@context"]

    # Test ID validation
    assert did_doc["id"].startswith("did:web:")

    # Test verification method validation
    verification_method = did_doc["verificationMethod"][0]
    required_vm_fields = ["id", "type", "controller", "publicKeyJwk"]
    for field in required_vm_fields:
        assert (
            field in verification_method
        ), f"Missing verification method field: {field}"

    # Test key agreement validation
    ka = did_doc["keyAgreement"][0]
    required_ka_fields = ["id", "type", "controller", "publicKeyJwk"]
    for field in required_ka_fields:
        assert field in ka, f"Missing key agreement field: {field}"

    # Test public key JWK structure
    identity_jwk = verification_method["publicKeyJwk"]
    spk_jwk = ka["publicKeyJwk"]

    for jwk in [identity_jwk, spk_jwk]:
        assert "kty" in jwk
        assert "crv" in jwk
        assert "x" in jwk
        assert jwk["kty"] == "OKP"

    # Verify signature in signed prekey
    assert "signature" in spk_jwk


def test_multiple_clients_have_different_private_keys(
    alice_client: Client, bob_client: Client, eve_client: Client
) -> None:
    """Test that each client gets their own unique private keys even when sharing the same workspace"""

    # Ensure all clients have been bootstrapped
    assert keys_exist(alice_client), "Alice should have keys from fixture"
    assert keys_exist(bob_client), "Bob should have keys from fixture"
    assert keys_exist(eve_client), "Eve should have keys from fixture"

    # Get private key storage paths for each client
    alice_key_path = private_key_path(alice_client)
    bob_key_path = private_key_path(bob_client)
    eve_key_path = private_key_path(eve_client)

    # Verify each client has a different private key file path
    assert (
        alice_key_path != bob_key_path
    ), "Alice and Bob should have different private key paths"
    assert (
        alice_key_path != eve_key_path
    ), "Alice and Eve should have different private key paths"
    assert (
        bob_key_path != eve_key_path
    ), "Bob and Eve should have different private key paths"

    # Verify all private key files exist
    assert (
        alice_key_path.exists()
    ), f"Alice's private keys not found at {alice_key_path}"
    assert bob_key_path.exists(), f"Bob's private keys not found at {bob_key_path}"
    assert eve_key_path.exists(), f"Eve's private keys not found at {eve_key_path}"

    # Load and compare the actual private key contents
    with open(alice_key_path, "r") as f:
        alice_keys = json.load(f)
    with open(bob_key_path, "r") as f:
        bob_keys = json.load(f)
    with open(eve_key_path, "r") as f:
        eve_keys = json.load(f)

    # Verify each client has different identity keys
    alice_identity = alice_keys["identity_key"]
    bob_identity = bob_keys["identity_key"]
    eve_identity = eve_keys["identity_key"]

    assert (
        alice_identity["x"] != bob_identity["x"]
    ), "Alice and Bob should have different identity keys"
    assert (
        alice_identity["x"] != eve_identity["x"]
    ), "Alice and Eve should have different identity keys"
    assert (
        bob_identity["x"] != eve_identity["x"]
    ), "Bob and Eve should have different identity keys"

    # Verify each client has different signed prekeys
    alice_spk = alice_keys["signed_prekey"]
    bob_spk = bob_keys["signed_prekey"]
    eve_spk = eve_keys["signed_prekey"]

    assert (
        alice_spk["x"] != bob_spk["x"]
    ), "Alice and Bob should have different signed prekeys"
    assert (
        alice_spk["x"] != eve_spk["x"]
    ), "Alice and Eve should have different signed prekeys"
    assert (
        bob_spk["x"] != eve_spk["x"]
    ), "Bob and Eve should have different signed prekeys"

    # Verify the directory structure uses different hashes
    alice_hash = alice_key_path.parent.name
    bob_hash = bob_key_path.parent.name
    eve_hash = eve_key_path.parent.name

    assert (
        alice_hash != bob_hash
    ), f"Alice and Bob should have different directory hashes: {alice_hash} vs {bob_hash}"
    assert (
        alice_hash != eve_hash
    ), f"Alice and Eve should have different directory hashes: {alice_hash} vs {eve_hash}"
    assert (
        bob_hash != eve_hash
    ), f"Bob and Eve should have different directory hashes: {bob_hash} vs {eve_hash}"

    # Verify each hash is 8 characters (from partitionHash[:8])
    assert len(alice_hash) == 8, f"Alice's hash should be 8 characters: {alice_hash}"
    assert len(bob_hash) == 8, f"Bob's hash should be 8 characters: {bob_hash}"
    assert len(eve_hash) == 8, f"Eve's hash should be 8 characters: {eve_hash}"


def test_ensure_bootstrap_fails_when_did_exists_but_keys_missing(
    temp_workspace: Path,
) -> None:
    """Test that ensure_bootstrap fails when DID exists but private keys are missing

    This is the core cryptobug scenario:
    - Container restart without persistent volume
    - DID synced from server but private keys lost
    - Should FAIL FAST with clear error, not silently regenerate
    """
    # Create a client and bootstrap it
    client: Client = create_temp_client("test@example.com", temp_workspace)
    bootstrap_user(client)

    # Verify keys and DID exist
    assert keys_exist(client)
    assert did_path(client).exists()

    # Simulate key loss (e.g., container restart without volume)
    key_file: Path = private_key_path(client)
    key_file.unlink()  # Delete private keys

    # Verify DID still exists but keys don't
    assert did_path(client).exists()
    assert not keys_exist(client)

    # Try to ensure_bootstrap without force flag - should FAIL
    with pytest.raises(RuntimeError) as exc_info:
        ensure_bootstrap(client)

    # Verify error message contains helpful guidance
    error_message: str = str(exc_info.value)
    assert "DID DOCUMENT EXISTS BUT PRIVATE KEYS NOT FOUND" in error_message
    assert "MOUNT PERSISTENT VOLUME" in error_message
    assert "IMPORT KEYS" in error_message
    assert "RECREATE KEYS" in error_message
    assert "force_recreate_crypto_keys=True" in error_message


def test_ensure_bootstrap_force_recreate_archives_old_did(
    temp_workspace: Path,
) -> None:
    """Test that force_recreate_crypto_keys archives old DID and creates new identity

    Scenario: User explicitly chooses to recreate identity after key loss
    Expected: Old DID archived, new keys created, data loss acknowledged
    """
    # Create client and bootstrap
    client: Client = create_temp_client("test@example.com", temp_workspace)
    bootstrap_user(client)

    # Save original DID for comparison
    original_did: Dict[str, Any] = get_did_document(client, client.config.email)
    original_spk: str = original_did["keyAgreement"][0]["publicKeyJwk"]["x"]
    did_file: Path = did_path(client)

    # Simulate key loss
    key_file: Path = private_key_path(client)
    key_file.unlink()

    # Force recreate identity
    ensure_bootstrap(client, force_recreate_crypto_keys=True)

    # Verify new keys were created
    assert keys_exist(client)

    # Verify new DID was created with different SPK
    new_did: Dict[str, Any] = get_did_document(client, client.config.email)
    new_spk: str = new_did["keyAgreement"][0]["publicKeyJwk"]["x"]
    assert new_spk != original_spk, "New SPK should be different from original"

    # Verify old DID was archived (not deleted)
    did_dir: Path = did_file.parent
    archived_files: list[Path] = list(did_dir.glob("did.retired.*.json"))
    assert len(archived_files) >= 1, "Old DID should be archived"

    # Verify archived DID contains original SPK
    with open(archived_files[0], "r") as f:
        archived_did: Dict[str, Any] = json.load(f)
    archived_spk: str = archived_did["keyAgreement"][0]["publicKeyJwk"]["x"]
    assert archived_spk == original_spk, "Archived DID should contain original SPK"


def test_ensure_bootstrap_detects_did_conflict(temp_workspace: Path) -> None:
    """Test that ensure_bootstrap detects and fails on DID conflicts

    Scenario: did.conflict.json exists (from SyftBox detecting version conflict)
    Expected: FAIL with clear message to manually resolve conflict
    """
    # Create client and bootstrap
    client: Client = create_temp_client("test@example.com", temp_workspace)
    bootstrap_user(client)

    # Get DID document
    did_file: Path = did_path(client)
    with open(did_file, "r") as f:
        did_content: str = f.read()

    # Create a conflict file (simulate SyftBox detecting conflict)
    conflict_file: Path = did_file.parent / "did.conflict.json"
    with open(conflict_file, "w") as f:
        f.write(did_content)

    # Try to ensure_bootstrap - should FAIL on conflict
    with pytest.raises(RuntimeError) as exc_info:
        ensure_bootstrap(client)

    # Verify error message
    error_message: str = str(exc_info.value)
    assert "DID conflict detected" in error_message
    assert "did.conflict.json" in str(conflict_file)
    assert "Manual resolution required" in error_message


def test_ensure_bootstrap_fresh_start_succeeds(unbootstrapped_client: Client) -> None:
    """Test normal bootstrap when neither DID nor keys exist

    Scenario: Fresh deployment, no previous identity
    Expected: Successfully bootstrap new identity
    """
    # Verify no keys or DID initially
    assert not keys_exist(unbootstrapped_client)
    assert not did_path(unbootstrapped_client).exists()

    # Ensure bootstrap should create new identity
    result: Client = ensure_bootstrap(unbootstrapped_client)

    # Verify keys and DID were created
    assert result == unbootstrapped_client
    assert keys_exist(unbootstrapped_client)
    assert did_path(unbootstrapped_client).exists()

    # Verify DID is valid
    did_doc: Dict[str, Any] = get_did_document(
        unbootstrapped_client, unbootstrapped_client.config.email
    )
    assert "keyAgreement" in did_doc
    assert "verificationMethod" in did_doc


def test_ensure_bootstrap_preserves_existing_keys(alice_client: Client) -> None:
    """Test that ensure_bootstrap preserves existing keys and DID

    Scenario: Normal operation, keys and DID both exist
    Expected: No regeneration, idempotent behavior
    """
    # Alice already has keys from fixture
    original_did: Dict[str, Any] = get_did_document(
        alice_client, alice_client.config.email
    )
    original_spk: str = original_did["keyAgreement"][0]["publicKeyJwk"]["x"]

    # Load original private keys
    original_identity_key, original_spk_key = load_private_keys(alice_client)
    original_identity_bytes: bytes = (
        original_identity_key.public_key().public_bytes_raw()
    )
    original_spk_bytes: bytes = original_spk_key.public_key().public_bytes_raw()

    # Call ensure_bootstrap
    ensure_bootstrap(alice_client)

    # Verify DID unchanged
    current_did: Dict[str, Any] = get_did_document(
        alice_client, alice_client.config.email
    )
    current_spk: str = current_did["keyAgreement"][0]["publicKeyJwk"]["x"]
    assert current_spk == original_spk, "SPK should not change"

    # Verify private keys unchanged
    current_identity_key, current_spk_key = load_private_keys(alice_client)
    current_identity_bytes: bytes = current_identity_key.public_key().public_bytes_raw()
    current_spk_bytes: bytes = current_spk_key.public_key().public_bytes_raw()

    assert (
        current_identity_bytes == original_identity_bytes
    ), "Identity key should not change"
    assert current_spk_bytes == original_spk_bytes, "SPK key should not change"


def test_private_keys_lost(temp_workspace: Path) -> None:
    """
    This test simulates this scenario:

    1. Client bootstraps successfully
    2. DID syncs to datasites (persisted)
    3. Client accidentally removes `.syftbox/` directory
    4. Client tries to initialize

    Expected: Clear error preventing silent regeneration
    """
    # Step 1: Initial bootstrap (first container run)
    client: Client = create_temp_client("user@example.com", temp_workspace)
    bootstrap_user(client)

    did_file: Path = did_path(client)
    original_did: Dict[str, Any] = get_did_document(client, client.config.email)

    # Simulate DID sync to datasites (already done by bootstrap)
    assert did_file.exists()

    # Step 2: `.syftbox/` directory lost
    key_file: Path = private_key_path(client)
    syftbox_dir: Path = key_file.parent.parent  # .syftbox directory
    shutil.rmtree(syftbox_dir)

    # Verify: DID still exists (synced) but keys gone
    assert did_file.exists(), "DID should remain in datasites"
    assert not key_file.exists(), "Keys should be gone"

    # Step 3: Try to initialize (would call ensure_bootstrap)
    # This should FAIL FAST, not silently regenerate
    with pytest.raises(RuntimeError) as exc_info:
        ensure_bootstrap(client)

    error_message: str = str(exc_info.value)
    assert "DID DOCUMENT EXISTS BUT PRIVATE KEYS NOT FOUND" in error_message

    # Verify DID was NOT changed
    current_did: Dict[str, Any] = get_did_document(client, client.config.email)
    assert current_did == original_did, "DID should not be modified on failure"


def test_force_recreate_allows_successful_encryption_decryption(
    temp_workspace: Path,
) -> None:
    """Test complete key lifecycle: original keys work → loss → recreation → new keys work

    This validates the entire cryptobug fix lifecycle:
    PHASE 1: Original keys work (baseline)
    PHASE 2: Key loss event (cryptobug scenario)
    PHASE 3: Force recreation
    PHASE 4: New keys work (recovery validated)
    """

    # Setup: Create DO (Data Owner) and DS (Data Scientist) clients
    do_client: Client = create_temp_client("do@example.com", temp_workspace)
    ds_client: Client = create_temp_client("ds@example.com", temp_workspace)

    # Bootstrap both clients
    bootstrap_user(do_client)
    bootstrap_user(ds_client)

    # ==================== PHASE 1: Test Original Keys Work ====================
    # This establishes baseline that encryption/decryption works with original keys

    original_message: str = "Message encrypted with ORIGINAL keys"

    # DS encrypts to DO using original public keys
    original_encrypted: EncryptedPayload = encrypt_message(
        original_message,
        do_client.config.email,
        ds_client,
    )

    # DO decrypts using original private keys
    original_decrypted: str = decrypt_message(
        original_encrypted,
        do_client,
    )

    # Verify original keys work perfectly
    assert original_decrypted == original_message, "Original keys should work"

    # Save original DID for comparison
    original_did: Dict[str, Any] = get_did_document(do_client, do_client.config.email)
    original_spk: str = original_did["keyAgreement"][0]["publicKeyJwk"]["x"]

    # ==================== PHASE 2: Simulate Key Loss ====================
    # DO's key directory lost (simulates container restart for DO only)

    do_key_file: Path = private_key_path(do_client)
    do_key_dir: Path = do_key_file.parent  # Just DO's hash directory
    shutil.rmtree(do_key_dir)  # Only delete DO's keys, not DS's

    # Verify cryptobug scenario: DID exists but keys gone
    assert did_path(do_client).exists(), "DID should remain (synced)"
    assert not keys_exist(do_client), "DO keys should be lost"
    assert keys_exist(ds_client), "DS keys should still exist"

    # ==================== PHASE 3: Force Recreate Keys ====================

    # DO explicitly chooses to recreate identity
    ensure_bootstrap(do_client, force_recreate_crypto_keys=True)

    # Verify new keys and DID created
    assert keys_exist(do_client), "New keys should exist"
    new_did: Dict[str, Any] = get_did_document(do_client, do_client.config.email)
    new_spk: str = new_did["keyAgreement"][0]["publicKeyJwk"]["x"]

    # Verify SPK changed (new cryptographic identity)
    assert new_spk != original_spk, "New SPK should be different from original"

    # Verify old DID was archived
    did_dir: Path = did_path(do_client).parent
    archived_files: list[Path] = list(did_dir.glob("did.retired.*.json"))
    assert len(archived_files) >= 1, "Old DID should be archived"

    # ==================== PHASE 4: Test New Keys Work ====================
    # Validate complete recovery - new crypto system functional

    new_message: str = "Message encrypted with NEW keys after force recreation"

    # DS encrypts to DO using NEW public keys (from updated DID)
    new_encrypted: EncryptedPayload = encrypt_message(
        new_message,
        do_client.config.email,
        ds_client,
    )

    # DO decrypts using NEW private keys
    new_decrypted: str = decrypt_message(
        new_encrypted,
        do_client,
    )

    # Verify new keys work perfectly
    assert new_decrypted == new_message, "New keys should work after recreation"

    # ==================== PHASE 5: Test Bidirectional Communication ====================
    # Ensure DO can also send messages back to DS

    response_message: str = "DS, I can send you encrypted messages with my new keys!"

    encrypted_response: EncryptedPayload = encrypt_message(
        response_message,
        ds_client.config.email,
        do_client,
    )

    decrypted_response: str = decrypt_message(
        encrypted_response,
        ds_client,
    )

    assert decrypted_response == response_message, "DO→DS communication should work"

    # ==================== Summary ====================
    # ✅ Original keys worked
    # ✅ Key loss detected
    # ✅ Force recreation succeeded
    # ✅ New keys work perfectly
    # ✅ Complete recovery validated - no InvalidTag errors!


def test_regenerate_did_when_missing_but_keys_exist(temp_workspace: Path) -> None:
    """Test that DID is automatically regenerated if keys exist but DID is missing

    Scenario: Private keys preserved but DID (public and identity keys) deleted
    Expected: Auto-regenerate DID from existing private keys (safe operation)
    """
    # Bootstrap normally
    client: Client = create_temp_client("test@example.com", temp_workspace)
    bootstrap_user(client)

    # Save original DID for comparison
    original_did: Dict[str, Any] = get_did_document(client, client.config.email)
    original_spk: str = original_did["keyAgreement"][0]["publicKeyJwk"]["x"]
    original_identity_key: str = original_did["verificationMethod"][0]["publicKeyJwk"][
        "x"
    ]

    # Delete DID but keep keys
    did_file: Path = did_path(client)
    did_file.unlink()

    # Verify keys exist but DID doesn't
    assert keys_exist(client), "Keys should exist"
    assert not did_file.exists(), "DID should be deleted"

    # Call ensure_bootstrap - should auto-regenerate DID
    ensure_bootstrap(client)

    # Verify DID was regenerated
    assert did_file.exists(), "DID should be regenerated"
    regenerated_did: Dict[str, Any] = get_did_document(client, client.config.email)
    regenerated_spk: str = regenerated_did["keyAgreement"][0]["publicKeyJwk"]["x"]
    regenerated_identity_key: str = regenerated_did["verificationMethod"][0][
        "publicKeyJwk"
    ]["x"]

    # Verify regenerated DID matches original (deterministic)
    assert (
        regenerated_spk == original_spk
    ), "Regenerated SPK should match original (deterministic)"
    assert (
        regenerated_identity_key == original_identity_key
    ), "Regenerated identity key should match original"
    assert regenerated_did["id"] == original_did["id"], "DID ID should match"

    # Verify encryption still works with regenerated DID
    test_client: Client = create_temp_client("test2@example.com", temp_workspace)
    bootstrap_user(test_client)

    # Test bidirectional encryption
    encrypted: EncryptedPayload = encrypt_message(
        "test message", client.config.email, test_client
    )
    decrypted: str = decrypt_message(encrypted, client)
    assert decrypted == "test message", "Encryption should work with regenerated DID"

    # Reverse direction
    encrypted_reverse: EncryptedPayload = encrypt_message(
        "reverse test", test_client.config.email, client
    )
    decrypted_reverse: str = decrypt_message(encrypted_reverse, test_client)
    assert decrypted_reverse == "reverse test", "Reverse encryption should also work"


def test_cryptobug_detection_keys_dont_match(temp_workspace: Path):
    """CRYPTOBUG: Keys exist, DID exists, but they don't match → Should FAIL proactively"""

    # ==================== PHASE 1: Normal Bootstrap ====================
    client = create_temp_client("user@example.com", temp_workspace)
    bootstrap_user(client)

    # Verify normal state
    assert keys_exist(client), "Keys should exist"
    assert did_path(client).exists(), "DID should exist"

    # ensure_bootstrap should succeed (keys match DID)
    ensure_bootstrap(client)

    # ==================== PHASE 2: Simulate Keys Replaced ====================
    # Replace private keys with NEW keys while keeping the OLD DID
    # This simulates the scenario where keys were regenerated but old DID still exists

    # Generate NEW keys (different from the ones in DID)
    new_identity_private = ed25519.Ed25519PrivateKey.generate()
    new_spk_private = x25519.X25519PrivateKey.generate()

    # Overwrite the private keys file with NEW keys
    save_private_keys(client, new_identity_private, new_spk_private)

    # ==================== PHASE 3: Verify Cryptobug Detection ====================
    # ensure_bootstrap should now FAIL because keys don't match DID
    with pytest.raises(RuntimeError) as exc_info:
        ensure_bootstrap(client)

    # Verify error message
    error_msg = str(exc_info.value)
    assert "Crypto keys mismatch detected" in error_msg, "Should detect keys mismatch"
    assert "Private keys don't match DID document" in error_msg
    assert "SOLUTIONS" in error_msg, "Should provide solutions"


def test_key_did_verification_with_encryption(temp_workspace: Path):
    """Verify that key-DID mismatch causes encryption to fail (validates our detection logic)"""

    # ==================== PHASE 1: Normal Setup ====================
    sender = create_temp_client("sender@example.com", temp_workspace)
    receiver = create_temp_client("receiver@example.com", temp_workspace)

    bootstrap_user(sender)
    bootstrap_user(receiver)

    # Test that encryption works with matching keys
    test_message = "test message"
    encrypted = encrypt_message(test_message, receiver.config.email, sender)
    decrypted = decrypt_message(encrypted, receiver)
    assert decrypted == test_message, "Encryption should work with matching keys"

    # ==================== PHASE 2: Create Key-DID Mismatch for Receiver ====================
    from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
    from syft_crypto.key_storage import save_private_keys

    # Replace receiver's keys (but keep old DID)
    new_identity_private = ed25519.Ed25519PrivateKey.generate()
    new_spk_private = x25519.X25519PrivateKey.generate()
    save_private_keys(receiver, new_identity_private, new_spk_private)

    # ==================== PHASE 3: Verify Detection at Bootstrap ====================
    # ensure_bootstrap should fail before we even try encryption
    with pytest.raises(RuntimeError) as exc_info:
        ensure_bootstrap(receiver)

    assert "Crypto keys mismatch detected" in str(exc_info.value)

    # ==================== PHASE 4: Verify Encryption Would Also Fail ====================
    # Even if we skip the verification, decryption would fail
    # (This validates that our detection is catching a real problem)
    encrypted_after_mismatch = encrypt_message(
        "another message", receiver.config.email, sender
    )

    # Decryption should fail because receiver has wrong keys
    with pytest.raises(ValueError) as decrypt_exc:
        decrypt_message(encrypted_after_mismatch, receiver)

    assert "Decryption failed" in str(
        decrypt_exc.value
    ), "Decryption should fail with mismatched keys"
