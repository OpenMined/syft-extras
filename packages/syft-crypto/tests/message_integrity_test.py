"""
Advanced message integrity tests for X3DH implementation

These tests verify message integrity protection against sophisticated attacks:
- Comprehensive bit-flipping attacks
- Truncation and extension attacks
- Substitution and splicing attacks
- Message ordering and replay attacks
- Ciphertext malleability tests
"""

import pytest
from syft_core import Client
from syft_crypto.x3dh import decrypt_message, encrypt_message


def test_single_bit_flip_attacks(alice_client: Client, bob_client: Client) -> None:
    """Test that single bit flips (the smallest modifications to encrypted data) in any part
    of the message are detected
    """

    message = "Bit flip integrity test message"
    encrypted = encrypt_message(message, bob_client.config.email, alice_client)

    # Test bit flips in different components
    components = [
        ("ek", encrypted.ek),
        ("iv", encrypted.iv),
        ("ciphertext", encrypted.ciphertext),
        ("tag", encrypted.tag),
    ]

    for component_name, component_data in components:
        # Test flipping each bit position
        for byte_pos in range(min(len(component_data), 8)):  # Test first 8 bytes
            for bit_pos in range(8):  # Test each bit in the byte
                # Create a copy and flip one bit
                tampered_data = bytearray(component_data)
                tampered_data[byte_pos] ^= 1 << bit_pos

                # Create tampered message
                tampered = encrypted.model_copy()
                setattr(tampered, component_name, bytes(tampered_data))

                # Should fail to decrypt
                with pytest.raises(ValueError, match="Decryption failed"):
                    decrypt_message(tampered, bob_client)


def test_byte_substitution_attacks(alice_client: Client, bob_client: Client) -> None:
    """Test that byte substitutions are detected"""

    message = "Byte substitution test message"
    encrypted = encrypt_message(message, bob_client.config.email, alice_client)

    components = ["ek", "iv", "ciphertext", "tag"]

    for component_name in components:
        component_data = getattr(encrypted, component_name)

        # Test substituting bytes at different positions
        for pos in range(min(len(component_data), 5)):  # Test first 5 positions
            tampered_data = bytearray(component_data)

            # Substitute with a different byte value
            original_byte = tampered_data[pos]
            new_byte = (original_byte + 1) % 256  # Different byte value
            tampered_data[pos] = new_byte

            # Create tampered message
            tampered = encrypted.model_copy()
            setattr(tampered, component_name, bytes(tampered_data))

            # Should fail to decrypt
            with pytest.raises(ValueError, match="Decryption failed"):
                decrypt_message(tampered, bob_client)


def test_truncation_attacks(alice_client: Client, bob_client: Client) -> None:
    """Test that truncated messages are detected"""

    message = "Truncation attack test message"
    encrypted = encrypt_message(message, bob_client.config.email, alice_client)

    components = ["ek", "iv", "ciphertext", "tag"]

    for component_name in components:
        component_data = getattr(encrypted, component_name)

        # Test truncating to different lengths
        if len(component_data) > 1:
            for truncate_length in [
                1,
                len(component_data) // 2,
                len(component_data) - 1,
            ]:
                truncated_data = component_data[:truncate_length]

                # Create tampered message
                tampered = encrypted.model_copy()
                setattr(tampered, component_name, truncated_data)

                # Should fail to decrypt
                with pytest.raises(ValueError):
                    decrypt_message(tampered, bob_client)


def test_extension_attacks(alice_client: Client, bob_client: Client) -> None:
    """Test that extended messages are detected"""

    message = "Extension attack test message"
    encrypted = encrypt_message(message, bob_client.config.email, alice_client)

    components = ["ek", "iv", "ciphertext", "tag"]

    for component_name in components:
        component_data = getattr(encrypted, component_name)

        # Test extending with different data
        extensions = [b"\x00", b"\xff", b"AAAA", bytes(range(16))]

        for extension in extensions:
            extended_data = component_data + extension

            # Create tampered message
            tampered = encrypted.model_copy()
            setattr(tampered, component_name, extended_data)

            # Should fail to decrypt
            with pytest.raises(ValueError):
                decrypt_message(tampered, bob_client)


def test_message_splicing_attacks(alice_client: Client, bob_client: Client) -> None:
    """
    Test to verify that the cryptographic system prevents message splicing attacks,
    where an attacker tries to combine parts from different encrypted messages to
    create a new, potentially valid-looking message.
    """

    # Create two different encrypted messages
    message1 = "First message for splicing test"
    message2 = "Second message for splicing test"

    encrypted1 = encrypt_message(message1, bob_client.config.email, alice_client)
    encrypted2 = encrypt_message(message2, bob_client.config.email, alice_client)

    # Test splicing different components between messages
    splice_tests = [
        ("ek", encrypted2.ek),
        ("iv", encrypted2.iv),
        ("ciphertext", encrypted2.ciphertext),
        ("tag", encrypted2.tag),
    ]

    for component_name, component_from_msg2 in splice_tests:
        # Create spliced message (mix components from both messages)
        spliced = encrypted1.model_copy()
        setattr(spliced, component_name, component_from_msg2)

        # Should fail to decrypt
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_message(spliced, bob_client)


def test_ciphertext_block_reordering(alice_client: Client, bob_client: Client) -> None:
    """Test that reordering ciphertext blocks is detected"""

    # Use a longer message to ensure multiple blocks
    message = "This is a longer message for block reordering test. " * 5
    encrypted = encrypt_message(message, bob_client.config.email, alice_client)

    ciphertext = encrypted.ciphertext

    # Test reordering bytes in the ciphertext
    if len(ciphertext) >= 16:  # Need at least 16 bytes to reorder
        # Swap first and last 8 bytes
        reordered = bytearray(ciphertext)
        reordered[:8], reordered[-8:] = reordered[-8:], reordered[:8]

        tampered = encrypted.model_copy()
        tampered.ciphertext = bytes(reordered)

        # Should fail to decrypt
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_message(tampered, bob_client)


def test_no_replay_protection_at_crypto_level(
    alice_client: Client, bob_client: Client
) -> None:
    """Test that the same encrypted message can be decrypted multiple times (no replay protection at crypto level)
    Note that X3DH itself doesn't provide replay protection - that's typically handled at the application layer.
    This test verifies that the same encrypted message can be decrypted multiple times.
    """

    message = "Replay test message"
    encrypted = encrypt_message(message, bob_client.config.email, alice_client)

    # Decrypt the same message multiple times
    for _ in range(5):
        decrypted = decrypt_message(encrypted, bob_client)
        assert decrypted == message


def test_timing_attack_resistance_basic(
    alice_client: Client, bob_client: Client
) -> None:
    """Basic test for timing attack resistance.
    This test measures the time taken to decrypt two messages of the same length but different content.
    The timing should be relatively similar, indicating that the decryption process is
    not significantly affected by the content of the message.
    """

    import time

    # Create messages of the same length but different content
    message1 = "A" * 100
    message2 = "z" * 100

    encrypted1 = encrypt_message(message1, bob_client.config.email, alice_client)
    encrypted2 = encrypt_message(message2, bob_client.config.email, alice_client)

    # Measure decryption times
    times1 = []
    times2 = []

    for _ in range(10):
        # Time decryption of first message
        start = time.perf_counter()
        decrypted1 = decrypt_message(encrypted1, bob_client)
        end = time.perf_counter()
        times1.append(end - start)
        assert decrypted1 == message1

        # Time decryption of second message
        start = time.perf_counter()
        decrypted2 = decrypt_message(encrypted2, bob_client)
        end = time.perf_counter()
        times2.append(end - start)
        assert decrypted2 == message2

    # Calculate average times
    avg_time1 = sum(times1) / len(times1)
    avg_time2 = sum(times2) / len(times2)

    # Times should be relatively similar (within 50% difference)
    # This is a basic check - real timing attack resistance requires more sophisticated testing
    max_time = max(avg_time1, avg_time2)
    min_time = min(avg_time1, avg_time2)

    if max_time > 0:  # Avoid division by zero
        time_ratio = max_time / min_time
        assert time_ratio < 2.0, f"Significant timing difference detected: {time_ratio}"


def test_chosen_ciphertext_attack_resistance(
    alice_client: Client, bob_client: Client
) -> None:
    """Test resistance to chosen ciphertext attacks.
    This test verifies that the cryptographic system prevents chosen ciphertext attacks,
    where an attacker tries to create new valid ciphertexts by combining parts from
    different encrypted messages.
    """

    # Generate some legitimate messages
    messages = ["Message 1", "Message 2", "Message 3"]
    encrypted_messages = []

    # Encrypt the messages
    for message in messages:
        encrypted = encrypt_message(message, bob_client.config.email, alice_client)
        encrypted_messages.append(encrypted)

    # Attacker tries to create new valid ciphertexts by combining parts from different encrypted messages
    # This should fail due to authentication
    for i, encrypted1 in enumerate(encrypted_messages):
        for j, encrypted2 in enumerate(encrypted_messages):
            if i != j:
                # Try combining different components
                combinations = [
                    # Use ciphertext from one, tag from another
                    (encrypted1.ciphertext, encrypted2.tag),
                    # Use IV from one, ciphertext from another
                    (encrypted2.ciphertext, encrypted1.tag),
                ]

                for ciphertext, tag in combinations:
                    attack_message = encrypted1.model_copy()
                    attack_message.ciphertext = ciphertext
                    attack_message.tag = tag

                    # Should fail to decrypt
                    with pytest.raises(ValueError, match="Decryption failed"):
                        decrypt_message(attack_message, bob_client)


def test_malleability_resistance(alice_client: Client, bob_client: Client) -> None:
    """
    This test verifies that the cryptographic system prevents malleability,
    where an attacker tries to modify the ciphertext to produce a related plaintext.
    """

    message = "0000000000000000"  # Predictable message
    encrypted = encrypt_message(message, bob_client.config.email, alice_client)

    # Try various modifications to the ciphertext that might create
    # predictable changes in a malleable scheme
    modifications = [
        # XOR with patterns
        b"\x00" * len(encrypted.ciphertext),  # XOR with zeros (no change)
        b"\x01" * len(encrypted.ciphertext),  # XOR with ones
        b"\xff" * len(encrypted.ciphertext),  # XOR with 0xFF
    ]

    for mod_pattern in modifications:
        if len(mod_pattern) == len(encrypted.ciphertext):
            # Apply XOR modification
            modified_ciphertext = bytes(
                a ^ b for a, b in zip(encrypted.ciphertext, mod_pattern)
            )

            tampered = encrypted.model_copy()
            tampered.ciphertext = modified_ciphertext

            # Should fail to decrypt (except for the all-zeros case which doesn't change anything)
            if mod_pattern != b"\x00" * len(encrypted.ciphertext):
                with pytest.raises(ValueError, match="Decryption failed"):
                    decrypt_message(tampered, bob_client)
            else:
                # All-zeros XOR should still decrypt to original message
                decrypted = decrypt_message(tampered, bob_client)
                assert decrypted == message


def test_ciphertext_indistinguishability(
    alice_client: Client, bob_client: Client
) -> None:
    """Test that ciphertexts don't leak information about plaintexts"""

    # Encrypt pairs of related messages
    message_pairs = [
        ("Hello World", "Hello World"),  # Identical messages
        ("Hello World", "Hello world"),  # Nearly identical
        ("AAAAAAAAAA", "BBBBBBBBBB"),  # Same length, different content
        ("Short", "Very long message with much more content"),  # Different lengths
    ]

    for msg1, msg2 in message_pairs:
        encrypted1 = encrypt_message(msg1, bob_client.config.email, alice_client)
        encrypted2 = encrypt_message(msg2, bob_client.config.email, alice_client)

        # Ciphertexts should appear random and unrelated
        # (even for identical plaintexts due to randomization)
        assert (
            encrypted1.ciphertext != encrypted2.ciphertext
        ), "Identical plaintexts produced identical ciphertexts"

        assert encrypted1.iv != encrypted2.iv, "IVs should be unique"

        assert encrypted1.ek != encrypted2.ek, "Ephemeral keys should be unique"

        # Verify both decrypt correctly
        decrypted1 = decrypt_message(encrypted1, bob_client)
        decrypted2 = decrypt_message(encrypted2, bob_client)

        assert decrypted1 == msg1
        assert decrypted2 == msg2
