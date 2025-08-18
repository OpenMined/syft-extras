"""
Test X3DH encryption/decryption functionality
"""

import json
from pathlib import Path
from typing import List, Tuple

import pytest
from loguru import logger
from syft_core import Client
from syft_crypto.did_utils import did_path, get_public_key_from_did
from syft_crypto.x3dh import (
    EncryptedPayload,
    decrypt_message,
    encrypt_message,
)


def test_self_encrypt_decrypt(alice_client: Client) -> None:
    """Test encrypting and decrypting a message to oneself"""
    message: str = "Hello, this is a self-encrypted message!"

    # Encrypt to self
    encrypted: EncryptedPayload = encrypt_message(
        message=message, to=alice_client.config.email, client=alice_client
    )

    # Verify payload structure
    assert isinstance(encrypted, EncryptedPayload)
    assert encrypted.sender == alice_client.config.email
    assert encrypted.receiver == alice_client.config.email
    assert len(encrypted.ek) == 32  # X25519 public key size
    assert len(encrypted.iv) == 12  # AES-GCM IV size
    assert len(encrypted.tag) == 16  # AES-GCM tag size
    assert len(encrypted.ciphertext) > 0

    # Decrypt
    decrypted: str = decrypt_message(encrypted, alice_client)
    assert decrypted == message


def test_alice_to_bob_encryption(alice_client: Client, bob_client: Client) -> None:
    """Test Alice encrypting a message for Bob"""
    message: str = "Secret message from Alice to Bob 🔐"

    # Alice encrypts for Bob
    encrypted: EncryptedPayload = encrypt_message(
        message=message, to=bob_client.config.email, client=alice_client
    )

    assert encrypted.sender == alice_client.config.email
    assert encrypted.receiver == bob_client.config.email

    # Bob decrypts
    decrypted: str = decrypt_message(encrypted, bob_client)
    assert decrypted == message


def test_bidirectional_encryption(alice_client: Client, bob_client: Client) -> None:
    """Test bidirectional encryption between Alice and Bob"""
    # Alice -> Bob
    alice_msg: str = "Hello Bob, this is Alice!"
    encrypted_to_bob: EncryptedPayload = encrypt_message(
        alice_msg, bob_client.config.email, alice_client
    )
    decrypted_by_bob: str = decrypt_message(encrypted_to_bob, bob_client)
    assert decrypted_by_bob == alice_msg

    # Bob -> Alice (response)
    bob_msg: str = "Hi Alice, Bob here! Got your message."
    encrypted_to_alice: EncryptedPayload = encrypt_message(
        bob_msg, alice_client.config.email, bob_client
    )
    decrypted_by_alice: str = decrypt_message(encrypted_to_alice, alice_client)
    assert decrypted_by_alice == bob_msg


def test_wrong_recipient_fails(alice_client: Client, bob_client: Client) -> None:
    """Test that decryption fails if you're not the intended recipient"""
    # Alice encrypts for herself
    encrypted: EncryptedPayload = encrypt_message(
        "Private message", alice_client.config.email, alice_client
    )

    # Bob tries to decrypt (should fail)
    with pytest.raises(ValueError, match=f"Message is for {alice_client.email}"):
        decrypt_message(encrypted, bob_client)


@pytest.mark.parametrize(
    "message",
    [
        "Hello, World!",
        "This is a secret message 🔐",
        "Unicode test: 你好世界 مرحبا بالعالم",
        "Special chars: !@#$%^&*()_+-=[]{}|;:',.<>?/`~",
        "Multi\nline\nmessage\ntest",
        "Empty next: ",
        " " * 100,  # Long whitespace
        "a" * 1000,  # Long message
    ],
)
def test_various_message_types(alice_client: Client, message: str) -> None:
    """Test encryption with various message types"""
    logger.debug(f"Test encrypting message: {message}")
    encrypted: EncryptedPayload = encrypt_message(
        message, alice_client.config.email, alice_client
    )
    decrypted: str = decrypt_message(encrypted, alice_client)
    assert decrypted == message


def test_encrypted_payload_serialization(alice_client: Client) -> None:
    """Test that EncryptedPayload can be serialized to/from JSON"""
    message: str = "Test serialization"

    # Create encrypted payload
    encrypted: EncryptedPayload = encrypt_message(
        message, alice_client.config.email, alice_client
    )

    # Serialize to JSON
    json_str: str = encrypted.model_dump_json()
    logger.debug(f"Serialized encrypted payload: {json_str}")
    json_data: dict = json.loads(json_str)

    # Verify JSON structure
    assert "ek" in json_data
    assert "iv" in json_data
    assert "ciphertext" in json_data
    assert "tag" in json_data
    assert "sender" in json_data
    assert "receiver" in json_data
    assert "version" in json_data

    # Deserialize back
    restored: EncryptedPayload = EncryptedPayload.model_validate_json(json_str)

    # Verify it still decrypts
    decrypted: str = decrypt_message(restored, alice_client)
    assert decrypted == message


def test_missing_did_document_fails(
    alice_client: Client, unbootstrapped_client: Client
) -> None:
    """Test that encryption fails if recipient has no DID document"""
    with pytest.raises(
        FileNotFoundError,
        match=f"No DID document found for {unbootstrapped_client.email}",
    ):
        encrypt_message(
            "Test message", unbootstrapped_client.config.email, alice_client
        )


def test_missing_private_keys_fails(
    alice_client: Client, unbootstrapped_client: Client
) -> None:
    """Test that encryption fails if sender has no private keys"""
    with pytest.raises(
        FileNotFoundError,
        match="Private keys not found",
    ):
        encrypt_message(
            "Test message", alice_client.config.email, unbootstrapped_client
        )


def test_tampered_ciphertext_fails(alice_client: Client, bob_client: Client) -> None:
    """Test that tampered ciphertext fails to decrypt"""
    message: str = "Original message"
    encrypted: EncryptedPayload = encrypt_message(
        message, bob_client.config.email, alice_client
    )

    # Tamper with ciphertext
    tampered: EncryptedPayload = encrypted.model_copy()
    tampered.ciphertext = b"tampered" + encrypted.ciphertext[8:]
    with pytest.raises(ValueError, match="Decryption failed"):
        decrypt_message(tampered, bob_client)


def test_tampered_tag_fails(alice_client: Client) -> None:
    """Test that tampered authentication tag fails"""
    message: str = "Original message"
    encrypted: EncryptedPayload = encrypt_message(
        message, alice_client.config.email, alice_client
    )

    # Tamper with tag
    tampered: EncryptedPayload = encrypted.model_copy()
    tampered.tag = b"x" * 16

    with pytest.raises(ValueError, match="Decryption failed"):
        decrypt_message(tampered, alice_client)


def test_get_public_key_from_did(alice_client: Client) -> None:
    """Test extracting public key from DID document"""
    # Load Alice's DID document
    did_file: Path = did_path(alice_client)
    with open(did_file, "r") as f:
        did_doc: dict = json.load(f)

    # Extract public key
    public_key = get_public_key_from_did(did_doc)

    # Should be an X25519 public key
    assert public_key is not None
    from cryptography.hazmat.primitives.asymmetric import x25519

    assert isinstance(public_key, x25519.X25519PublicKey)


def test_protocol_version(alice_client: Client) -> None:
    """Test that protocol version is set correctly"""
    encrypted: EncryptedPayload = encrypt_message(
        "Test", alice_client.config.email, alice_client
    )

    assert encrypted.version == "1.0"


def test_ping_pong_exchange(alice_client: Client, bob_client: Client) -> None:
    """Simulate a ping-pong message exchange"""
    # Step 1: Alice sends "ping" to Bob
    ping_msg: str = "Ping from Alice! 🏓"
    ping_encrypted: EncryptedPayload = encrypt_message(
        ping_msg, bob_client.config.email, alice_client
    )
    logger.debug(f"Encrypted ping from Alice to Bob: {ping_encrypted}")

    # Step 2: Bob receives and decrypts ping
    ping_decrypted: str = decrypt_message(ping_encrypted, bob_client)
    assert ping_decrypted == ping_msg
    logger.debug(f"Decrypted ping from Alice Bob: {ping_decrypted}")

    # Step 3: Bob sends "pong" response to Alice
    pong_msg: str = f"Pong! Received: '{ping_decrypted}' 🏓"
    pong_encrypted: EncryptedPayload = encrypt_message(
        pong_msg, alice_client.config.email, bob_client
    )
    logger.debug(f"Encrypted pong from Bob to Alice: {pong_encrypted}")

    # Step 4: Alice receives and decrypts pong
    pong_decrypted: str = decrypt_message(pong_encrypted, alice_client)
    logger.debug(f"Decrypted pong from Bob to Alice: {pong_decrypted}")
    assert pong_msg == pong_decrypted
    assert "Ping from Alice!" in pong_decrypted


def test_multi_round_exchange(alice_client: Client, bob_client: Client) -> None:
    """Test multiple rounds of encrypted communication"""
    messages: List[Tuple[str, str]] = []

    # Multiple rounds of communication
    for round_num in range(5):
        logger.debug(f"--- Round {round_num} ---")
        if round_num % 2 == 0:
            # Alice sends to Bob
            msg: str = f"Message {round_num} from Alice"
            encrypted: EncryptedPayload = encrypt_message(
                msg, bob_client.config.email, alice_client
            )
            logger.debug(
                f"Encrypted message {round_num} from Alice to Bob: {encrypted}"
            )
            decrypted: str = decrypt_message(encrypted, bob_client)
            logger.debug(
                f"Decrypted message {round_num} from Alice to Bob: {decrypted}"
            )
        else:
            # Bob sends to Alice
            msg: str = f"Message {round_num} from Bob"
            encrypted: EncryptedPayload = encrypt_message(
                msg, alice_client.config.email, bob_client
            )
            logger.debug(
                f"Encrypted message {round_num} from Bob to Alice: {encrypted}"
            )
            decrypted: str = decrypt_message(encrypted, alice_client)
            logger.debug(
                f"Decrypted message {round_num} from Bob to Alice: {decrypted}"
            )

        messages.append((msg, decrypted))
        assert msg == decrypted

    # Verify all messages were correctly exchanged
    assert len(messages) == 5
    for original, decrypted in messages:
        assert original == decrypted
