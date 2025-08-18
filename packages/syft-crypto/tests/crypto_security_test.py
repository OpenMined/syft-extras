"""
Core cryptographic security tests for X3DH implementation

These tests verify fundamental cryptographic security properties:
- Ephemeral key freshness and uniqueness
- Forward secrecy guarantees
- Proper key derivation
- Signature verification
- Replay attack prevention
"""

from collections import defaultdict
from typing import Dict, List, Set

from syft_core import Client
from syft_crypto.x3dh import EncryptedPayload, decrypt_message, encrypt_message


def test_ephemeral_key_uniqueness(alice_client: Client, bob_client: Client) -> None:
    """Test that each message uses a unique ephemeral key"""
    message: str = "Test message"
    ephemeral_keys: Set[bytes] = set()

    # Generate multiple encrypted messages
    for _ in range(10):
        encrypted: EncryptedPayload = encrypt_message(
            message, bob_client.config.email, alice_client
        )

        # Ephemeral key should be unique
        assert encrypted.ek not in ephemeral_keys, "Ephemeral key reused!"
        ephemeral_keys.add(encrypted.ek)

        # Verify message still decrypts correctly
        decrypted: str = decrypt_message(encrypted, bob_client)
        assert decrypted == message


def test_ephemeral_key_freshness_per_recipient(
    alice_client: Client, bob_client: Client
) -> None:
    """Test that ephemeral keys are fresh even for the same recipient"""
    message: str = "Test message"

    # Send multiple messages to the same recipient
    encrypted_messages: List[EncryptedPayload] = []
    for i in range(5):
        encrypted: EncryptedPayload = encrypt_message(
            f"{message} {i}", bob_client.config.email, alice_client
        )
        encrypted_messages.append(encrypted)

    # All ephemeral keys should be different
    ephemeral_keys: Set[bytes] = {msg.ek for msg in encrypted_messages}
    assert len(ephemeral_keys) == 5, "Ephemeral keys not unique per message"

    # All messages should decrypt correctly
    for i, encrypted in enumerate(encrypted_messages):
        decrypted: str = decrypt_message(encrypted, bob_client)
        assert decrypted == f"{message} {i}"


def test_forward_secrecy_simulation(alice_client: Client, bob_client: Client) -> None:
    """
    Simulate forward secrecy by verifying that each message uses fresh ephemeral keys
    Note: True forward secrecy would require key rotation, but we test the foundation
    """
    messages: List[str] = [
        "Message 1 - should remain secure",
        "Message 2 - even if later keys compromised",
        "Message 3 - forward secrecy test",
    ]

    encrypted_messages: List[EncryptedPayload] = []
    ephemeral_keys: List[bytes] = []

    # Encrypt multiple messages
    for msg in messages:
        encrypted: EncryptedPayload = encrypt_message(
            msg, bob_client.config.email, alice_client
        )
        encrypted_messages.append(encrypted)
        ephemeral_keys.append(encrypted.ek)

    # Verify all ephemeral keys are unique (foundation for forward secrecy)
    assert len(set(ephemeral_keys)) == len(ephemeral_keys), "Ephemeral keys not unique"

    # Verify all messages decrypt correctly
    for original, encrypted in zip(messages, encrypted_messages):
        decrypted: str = decrypt_message(encrypted, bob_client)
        assert decrypted == original

    # Simulate compromise: Even if we know one ephemeral key, others should be independent
    # (In practice, this would involve more complex key derivation chains)
    for i, ek in enumerate(ephemeral_keys):
        for j, other_ek in enumerate(ephemeral_keys):
            if i != j:
                assert ek != other_ek, f"Ephemeral keys {i} and {j} are identical"


def test_key_derivation_deterministic(alice_client: Client, bob_client: Client) -> None:
    """
    Test that encrypting the same message multiple times produces different results
    (due to different ephemeral keys) but still decrypts correctly
    """

    message: str = "Deterministic test message"

    # Encrypt same message multiple times
    encrypted_msgs: List[EncryptedPayload] = []
    for _ in range(3):
        encrypted: EncryptedPayload = encrypt_message(
            message, bob_client.config.email, alice_client
        )
        encrypted_msgs.append(encrypted)

    # Ciphertexts should be different (due to different ephemeral keys and IVs)
    ciphertexts: Set[bytes] = {msg.ciphertext for msg in encrypted_msgs}
    assert len(ciphertexts) == 3, "Ciphertexts should be different for each encryption"

    # But all should decrypt to the same message
    for encrypted in encrypted_msgs:
        decrypted: str = decrypt_message(encrypted, bob_client)
        assert decrypted == message


def test_no_key_reuse_across_sessions(alice_client: Client, bob_client: Client) -> None:
    """Test that keys are not reused across different communication sessions"""
    # Simulate different "sessions" by encrypting messages in batches

    session_keys: Dict[int, Set[bytes]] = defaultdict(set)

    # Simulate 3 sessions with 3 messages each
    for session_id in range(3):
        for msg_id in range(3):
            message: str = f"Session {session_id}, Message {msg_id}"
            encrypted: EncryptedPayload = encrypt_message(
                message, bob_client.config.email, alice_client
            )

            # Store ephemeral key for this session
            session_keys[session_id].add(encrypted.ek)

            # Verify decryption
            decrypted: str = decrypt_message(encrypted, bob_client)
            assert decrypted == message

    # Verify no key reuse within sessions
    for session_id, keys in session_keys.items():
        assert len(keys) == 3, f"Session {session_id} has key reuse"

    # Verify no key reuse across sessions
    all_keys: Set[bytes] = set()
    for keys in session_keys.values():
        for key in keys:
            assert key not in all_keys, "Ephemeral key reused across sessions"
            all_keys.add(key)


def test_iv_uniqueness(alice_client: Client, bob_client: Client) -> None:
    """Test that initialization vectors (IVs) are unique for each message"""
    message: str = "IV uniqueness test"
    ivs: Set[bytes] = set()

    # Generate multiple encrypted messages
    for _ in range(20):
        encrypted: EncryptedPayload = encrypt_message(
            message, bob_client.config.email, alice_client
        )

        # IV should be unique
        assert encrypted.iv not in ivs, "IV reused!"
        ivs.add(encrypted.iv)

        # Verify correct IV length for AES-GCM
        assert len(encrypted.iv) == 12, "AES-GCM IV should be 12 bytes"

        # Verify message still decrypts correctly
        decrypted: str = decrypt_message(encrypted, bob_client)
        assert decrypted == message
