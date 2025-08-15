"""
Test bootstrap functionality for X3DH key generation
"""

import json

import pytest
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


def test_bootstrap_private_keys(unbootstrapped_client):
    """Test that bootstrap creates all necessary files"""
    client = unbootstrapped_client

    # Verify no keys exist initially
    assert not keys_exist(client)
    assert not did_path(client).exists()

    # Bootstrap
    result = bootstrap_user(client)
    assert result is True

    # Verify keys were created
    assert keys_exist(client)
    assert did_path(client).exists()

    # Verify private key file structure
    key_file = private_key_path(client)
    with open(key_file, "r") as f:
        keys_data = json.load(f)

    assert "identity_key" in keys_data
    assert "signed_prekey" in keys_data
    assert keys_data["identity_key"]["kty"] == "OKP"
    assert keys_data["signed_prekey"]["kty"] == "OKP"
    assert keys_data["identity_key"]["crv"] == "Ed25519"
    assert keys_data["signed_prekey"]["crv"] == "X25519"


def test_bootstrap_creates_valid_did_document(unbootstrapped_client):
    """Test that bootstrap creates a valid DID document"""
    client = unbootstrapped_client
    bootstrap_user(client)

    # Load and verify DID document
    did_doc = get_did_document(client, client.config.email)

    # Check structure
    assert "@context" in did_doc
    assert "id" in did_doc
    assert "verificationMethod" in did_doc
    assert "keyAgreement" in did_doc

    # Check DID ID
    expected_did = generate_did_web_id(
        client.config.email, client.config.server_url.host
    )
    assert did_doc["id"] == expected_did

    # Check verification method (identity key)
    assert len(did_doc["verificationMethod"]) == 1
    vm = did_doc["verificationMethod"][0]
    assert vm["type"] == "Ed25519VerificationKey2020"
    assert "publicKeyJwk" in vm
    assert vm["publicKeyJwk"]["kty"] == "OKP"
    assert vm["publicKeyJwk"]["crv"] == "Ed25519"

    # Check key agreement (signed prekey)
    assert len(did_doc["keyAgreement"]) == 1
    ka = did_doc["keyAgreement"][0]
    assert ka["type"] == "X25519KeyAgreementKey2020"
    assert "publicKeyJwk" in ka
    assert ka["publicKeyJwk"]["kty"] == "OKP"
    assert ka["publicKeyJwk"]["crv"] == "X25519"
    assert "signature" in ka["publicKeyJwk"]


def test_bootstrap_idempotent(unbootstrapped_client):
    """Test that bootstrap doesn't overwrite existing keys"""
    client = unbootstrapped_client

    # First bootstrap
    result1 = bootstrap_user(client)
    assert result1 is True

    # Load original DID
    original_did = get_did_document(client, client.config.email)

    # Second bootstrap (should not regenerate)
    result2 = bootstrap_user(client)
    assert result2 is False

    # Verify DID unchanged
    current_did = get_did_document(client, client.config.email)
    assert original_did == current_did


def test_bootstrap_force_regenerate(unbootstrapped_client):
    """Test force regeneration of keys"""
    client = unbootstrapped_client

    # First bootstrap
    bootstrap_user(client)
    original_did = get_did_document(client, client.config.email)

    # Force regenerate
    result = bootstrap_user(client, force=True)
    assert result is True

    # Verify DID changed (new keys)
    new_did = get_did_document(client, client.config.email)
    assert (
        new_did["verificationMethod"][0]["publicKeyJwk"]
        != original_did["verificationMethod"][0]["publicKeyJwk"]
    )
    assert (
        new_did["keyAgreement"][0]["publicKeyJwk"]
        != original_did["keyAgreement"][0]["publicKeyJwk"]
    )


def test_ensure_bootstrap(unbootstrapped_client):
    """Test ensure_bootstrap creates keys if missing"""
    client = unbootstrapped_client

    # No keys initially
    assert not keys_exist(client)

    # Ensure bootstrap
    returned_client = ensure_bootstrap(client)

    # Should return same client
    assert returned_client == client

    # Keys should exist now
    assert keys_exist(client)


def test_ensure_bootstrap_preserves_existing(alice_client):
    """Test ensure_bootstrap doesn't regenerate existing keys"""
    # Alice already has keys from fixture
    original_did = get_did_document(alice_client, alice_client.config.email)

    # Ensure bootstrap
    ensure_bootstrap(alice_client)

    # Keys should be unchanged
    current_did = get_did_document(alice_client, alice_client.config.email)
    assert current_did == original_did


def test_key_signature_verification(alice_client):
    """Test that signed prekey has valid signature"""
    import base64

    from cryptography.hazmat.primitives.asymmetric import ed25519

    # Load DID document
    did_doc = get_did_document(alice_client, alice_client.config.email)

    # Extract identity public key
    identity_jwk = did_doc["verificationMethod"][0]["publicKeyJwk"]
    identity_key_bytes = base64.urlsafe_b64decode(identity_jwk["x"] + "===")
    identity_public_key = ed25519.Ed25519PublicKey.from_public_bytes(identity_key_bytes)

    # Extract signed prekey and signature
    spk_jwk = did_doc["keyAgreement"][0]["publicKeyJwk"]
    spk_bytes = base64.urlsafe_b64decode(spk_jwk["x"] + "===")
    signature = base64.urlsafe_b64decode(spk_jwk["signature"] + "===")

    # Verify signature
    try:
        identity_public_key.verify(signature, spk_bytes)
        # If no exception, signature is valid
        assert True
    except Exception:
        pytest.fail("Signed prekey signature verification failed")


def test_private_key_path_deterministic(alice_client):
    """Test that private key path is deterministic"""
    path1 = private_key_path(alice_client)
    path2 = private_key_path(alice_client)
    assert path1 == path2


def test_save_and_load_private_keys(unbootstrapped_client):
    """Test saving and loading private keys"""
    from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

    client = unbootstrapped_client

    # Generate test keys
    identity_key = ed25519.Ed25519PrivateKey.generate()
    spk_key = x25519.X25519PrivateKey.generate()

    # Save keys
    save_path = save_private_keys(client, identity_key, spk_key)
    assert save_path.exists()

    # Load keys back
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
def test_key_to_jwk(key_type, expected_use):
    """Test key to JWK conversion"""
    from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

    if key_type == "ed25519":
        key = ed25519.Ed25519PrivateKey.generate().public_key()
        expected_crv = "Ed25519"
    else:
        key = x25519.X25519PrivateKey.generate().public_key()
        expected_crv = "X25519"

    jwk = key_to_jwk(key, f"test-{key_type}")

    assert jwk["kty"] == "OKP"
    assert jwk["crv"] == expected_crv
    assert jwk["kid"] == f"test-{key_type}"
    assert jwk["use"] == expected_use
    assert "x" in jwk


def test_generate_did_web_id():
    """Test DID web ID generation"""
    did = generate_did_web_id("test@example.com", "syftbox.net")
    assert did == "did:web:syftbox.net:test%40example.com"

    # Test with special characters
    did = generate_did_web_id("test+user@example.com", "custom.domain")
    assert did == "did:web:custom.domain:test%2Buser%40example.com"


def test_did_path(alice_client):
    """Test DID path generation"""
    path = did_path(alice_client)
    expected = (
        alice_client.datasites / alice_client.config.email / "public" / "did.json"
    )
    assert path == expected

    # Test with specific user
    path = did_path(alice_client, "bob@example.com")
    expected = alice_client.datasites / "bob@example.com" / "public" / "did.json"
    assert path == expected


def test_save_and_get_did_document(unbootstrapped_client):
    """Test saving and retrieving DID documents"""
    client = unbootstrapped_client

    # Create a test DID document
    test_did = {
        "@context": ["https://www.w3.org/ns/did/v1"],
        "id": f"did:web:test:{client.config.email}",
        "test": "document",
    }

    # Save it
    save_path = save_did_document(client, test_did)
    assert save_path.exists()

    # Retrieve it
    retrieved = get_did_document(client, client.config.email)
    assert retrieved == test_did


def test_get_did_document_not_found(unbootstrapped_client):
    """Test error when DID document doesn't exist"""
    with pytest.raises(FileNotFoundError, match="No DID document found"):
        get_did_document(unbootstrapped_client, "nonexistent@example.com")
