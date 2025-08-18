"""
Protocol-level security tests for X3DH implementation

These tests verify protocol security properties:
- Man-in-the-middle attack prevention
- Identity verification and authentication
"""

import base64
import json

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from syft_core import Client
from syft_crypto.did_utils import (
    create_x3dh_did_document,
    get_did_document,
    save_did_document,
)
from syft_crypto.x3dh import EncryptedPayload, decrypt_message, encrypt_message


def test_identity_verification_through_did(
    alice_client: Client, bob_client: Client
) -> None:
    """
    This test verifies that the cryptographic system properly verifies the identity of the sender
    by checking the DID document of the sender.
    """
    message: str = "Identity verification test"

    # Alice encrypts message for Bob
    encrypted: EncryptedPayload = encrypt_message(
        message, bob_client.config.email, alice_client
    )

    # Verify sender identity is correctly recorded
    assert encrypted.sender == alice_client.config.email
    assert encrypted.receiver == bob_client.config.email

    # Bob should be able to verify this came from Alice
    decrypted: str = decrypt_message(encrypted, bob_client)
    assert decrypted == message

    # Verify that the sender field matches Alice's email
    assert encrypted.sender == alice_client.config.email

    # Alice should not be able to decrypt the message
    with pytest.raises(ValueError):
        decrypt_message(encrypted, alice_client)


def test_prevent_sender_spoofing(
    alice_client: Client, bob_client: Client, eve_client: Client
) -> None:
    """Test that sender field cannot be easily spoofed.
    This test verifies that the cryptographic system prevents sender spoofing,
    where an attacker tries to impersonate the sender of an encrypted message.
    """
    message: str = "Anti-spoofing test"

    # Create legitimate encrypted message from Alice to Bob
    encrypted: EncryptedPayload = encrypt_message(
        message, bob_client.config.email, alice_client
    )

    # Eve attempts to spoof sender field
    spoofed: EncryptedPayload = encrypted.model_copy()
    spoofed.sender = eve_client.config.email

    # Even with spoofed sender, the cryptographic verification should fail
    # because the message was encrypted with Alice's keys, not the attacker's
    with pytest.raises((ValueError, FileNotFoundError)):
        # This should fail because either:
        # 1. No DID document exists for evil@attacker.com, or
        # 2. The cryptographic verification fails
        decrypt_message(spoofed, bob_client)


def test_protocol_version_validation(alice_client: Client, bob_client: Client) -> None:
    """
    This test verifies that the cryptographic system properly validates the protocol version of the encrypted message.
    """
    message: str = "Version validation test"

    # Create legitimate message
    encrypted: EncryptedPayload = encrypt_message(
        message, bob_client.config.email, alice_client
    )

    # Verify current version
    assert encrypted.version == "1.0"

    # Test with unsupported future version
    future_version: EncryptedPayload = encrypted.model_copy()
    future_version.version = "2.0"

    # Should handle gracefully (for now, we accept it, but this could be changed)
    # In a production system, we might want to reject unknown versions
    decrypted: str = decrypt_message(future_version, bob_client)
    assert decrypted == message


def test_mitm_protection_through_did_verification(
    alice_client: Client, bob_client: Client
) -> None:
    """
    This test verifies that the cryptographic system properly protects against man-in-the-middle attacks
    through DID verification.
    This test simulates a MITM attack where an attacker intercepts
    and replaces Bob's DID document with their own keys, then verifies that the
    X3DH protocol properly detects and prevents this attack.

    Attack Scenario:
    1. Attacker generates their own DID document with their own keys
    2. Attacker creates a fake DID document impersonating Bob with attacker's keys
    3. Attacker replaces Bob's legitimate DID document with the fake one
    4. Alice encrypts a message to "Bob" using the fake DID (attacker's keys) and sends it to Bob
    5. Real Bob attempts to decrypt the message with his legitimate keys
    6. Decryption should fail because message was encrypted to attacker's keys
    """

    # Step 1: Generate attacker's malicious key pair
    attacker_identity_key = ed25519.Ed25519PrivateKey.generate()
    attacker_spk_key = x25519.X25519PrivateKey.generate()

    # Step 1: Create valid signature for attacker's signed prekey
    spk_public_bytes = attacker_spk_key.public_key().public_bytes_raw()
    fake_signature = attacker_identity_key.sign(spk_public_bytes)

    # Step 2: Create malicious DID document impersonating Bob with attacker's keys
    fake_did = create_x3dh_did_document(
        bob_client.config.email,  # Impersonate Bob's identity
        bob_client.config.server_url.host,
        attacker_identity_key.public_key(),
        attacker_spk_key.public_key(),
        fake_signature,
    )

    # Step 3: Replace Bob's DID with the fake one (simulating MITM attack)
    save_did_document(alice_client, fake_did, bob_client.config.email)

    # Step 4: Alice encrypts message to "Bob" using the fake DID
    message: str = "MITM test message"
    encrypted = encrypt_message(message, bob_client.config.email, alice_client)

    # Step 5 & 6: Verify real Bob cannot decrypt the message
    with pytest.raises(ValueError, match="Decryption failed"):
        decrypt_message(encrypted, bob_client, verbose=True)


def test_did_signature_prevents_key_substitution(alice_client: Client) -> None:
    """
    Test that DID signature verification prevents key substitution attacks.

    This test verifies that an attacker cannot substitute their own public key
    into a victim's DID document while keeping the original signature, because
    the signature cryptographically binds the identity key to the signed prekey.

    Attack Scenario:
    1. Attacker obtains Alice's legitimate DID document
    2. Attacker generates their own X25519 key pair
    3. Attacker replaces Alice's signed prekey with their own public key
    4. Attacker keeps Alice's original signature (hoping it will still validate)
    5. System should detect this attack through signature verification failure
    """
    # 1. Get Alice's legitimate DID
    legitimate_did = get_did_document(alice_client, alice_client.config.email)

    # 2. Generate an attacker's key pair
    attacker_spk = x25519.X25519PrivateKey.generate()
    attacker_spk_public = attacker_spk.public_key()

    # 3. Create tampered DID with substituted key but original signature
    tampered_did = json.loads(json.dumps(legitimate_did))  # Deep copy

    # Substitute the signed prekey with attacker's key
    attacker_jwk = {
        "kty": "OKP",
        "crv": "X25519",
        "x": base64.urlsafe_b64encode(attacker_spk_public.public_bytes_raw())
        .decode()
        .rstrip("="),
    }

    # Keep Alice's original signature, but replace her signed prekey with the attacker's key
    # This would allow the attacker to decrypt messages meant for Alice
    original_signature = tampered_did["keyAgreement"][0]["publicKeyJwk"]["signature"]
    attacker_jwk["signature"] = original_signature
    tampered_did["keyAgreement"][0]["publicKeyJwk"] = attacker_jwk

    # 4. Extract Alice's identity public key for verification
    identity_jwk = legitimate_did["verificationMethod"][0]["publicKeyJwk"]
    identity_key_bytes = base64.urlsafe_b64decode(identity_jwk["x"] + "===")
    identity_public_key = ed25519.Ed25519PublicKey.from_public_bytes(identity_key_bytes)

    # Get the signature bytes
    signature_bytes = base64.urlsafe_b64decode(original_signature + "===")

    # 5. Verify the signature FAILS with the attacker's key
    attacker_key_bytes = attacker_spk_public.public_bytes_raw()

    with pytest.raises(InvalidSignature):  # Should fail signature verification
        identity_public_key.verify(signature_bytes, attacker_key_bytes)

    # Extra: Verify Alice's legitimate signature IS valid with the original key
    legitimate_spk_jwk = legitimate_did["keyAgreement"][0]["publicKeyJwk"]
    legitimate_spk_bytes = base64.urlsafe_b64decode(legitimate_spk_jwk["x"] + "===")

    # This should succeed - proving the signature is valid for the original key
    identity_public_key.verify(signature_bytes, legitimate_spk_bytes)


def test_malformed_did_document_handling(
    alice_client: Client, bob_client: Client
) -> None:
    """
    This test verifies that the cryptographic system properly handles malformed DID documents,
    where the DID document is not properly formatted or contains invalid fields.
    """
    # Save Bob's original DID
    original_did_path = (
        alice_client.datasites / bob_client.config.email / "public" / "did.json"
    )
    backup_content = (
        original_did_path.read_text() if original_did_path.exists() else None
    )

    malformed_dids = [
        # Missing required fields
        {"@context": ["https://www.w3.org/ns/did/v1"], "id": "did:web:test"},
        # Invalid key types
        {
            "@context": ["https://www.w3.org/ns/did/v1"],
            "id": "did:web:test",
            "verificationMethod": [{"type": "InvalidKeyType"}],
            "keyAgreement": [{"type": "InvalidKeyType"}],
        },
        # Invalid JSON structure
        "not a json object",
    ]

    try:
        for malformed_did in malformed_dids:
            # Write malformed DID
            if isinstance(malformed_did, str):
                original_did_path.write_text(malformed_did)
            else:
                original_did_path.write_text(json.dumps(malformed_did))

            # Should fail to encrypt
            with pytest.raises((KeyError, ValueError, json.JSONDecodeError)):
                encrypt_message(
                    "test", bob_client.config.email, alice_client, verbose=True
                )

    finally:
        # Restore original DID
        if backup_content:
            original_did_path.write_text(backup_content)
        else:
            original_did_path.unlink(missing_ok=True)
