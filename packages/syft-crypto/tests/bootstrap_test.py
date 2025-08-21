"""
Test bootstrap functionality for X3DH key generation
"""

import json
from pathlib import Path
from typing import Any, Dict

import pytest
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
from syft_crypto.x3dh_bootstrap import bootstrap_user, ensure_bootstrap


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
