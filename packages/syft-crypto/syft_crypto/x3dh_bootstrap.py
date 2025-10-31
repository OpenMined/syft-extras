#!/usr/bin/env python3
"""
X3DH bootstrap module for generating keys and DID documents for SyftBox users
"""

from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from loguru import logger
from syft_core import Client

from syft_crypto.did_utils import (
    create_x3dh_did_document,
    get_did_document,
    get_identity_public_key_from_did,
    get_public_key_from_did,
    save_did_document,
)
from syft_crypto.key_storage import (
    keys_exist,
    load_private_keys,
    private_key_path,
    save_private_keys,
)


def bootstrap_user(client: Client, force: bool = False) -> bool:
    """Generate X3DH keypairs and create DID document for a user

    Args:
        client: SyftBox client instance
        force: If True, regenerate keys even if they exist

    Returns:
        bool: True if keys were generated, False if they already existed
    """
    pks_path = private_key_path(client)

    # Check if keys already exist
    if pks_path.exists():
        if not force:
            logger.info(
                f"✅ Private keys already exist for '{client.config.email}' at {pks_path}. Skip bootstrapping ⏩"
            )
            return False
        else:
            logger.info(
                f"⚠️ Private keys already exist for '{client.config.email}'. Force replace them at {pks_path} ⏩"
            )

    logger.info(f"🔧 X3DH keys bootstrapping for '{client.config.email}'")

    # Generate Identity Key (long-term Ed25519 key pair)
    identity_private_key = ed25519.Ed25519PrivateKey.generate()
    identity_public_key = identity_private_key.public_key()

    # Generate Signed Pre Key (X25519 key pair)
    spk_private_key = x25519.X25519PrivateKey.generate()
    spk_public_key = spk_private_key.public_key()

    # Sign the Signed Pre Key with the Identity Key
    spk_public_bytes = spk_public_key.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    spk_signature = identity_private_key.sign(spk_public_bytes)

    # Save private keys securely
    save_private_keys(client, identity_private_key, spk_private_key)

    # Create and save DID document
    did_doc = create_x3dh_did_document(
        client.config.email,
        client.config.server_url.host,
        identity_public_key,
        spk_public_key,
        spk_signature,
    )

    did_file = save_did_document(client, did_doc)

    logger.info(f"✅ Generated DID: {did_doc['id']}")
    logger.info(f"📄 DID document saved to: {did_file}")
    logger.info(f"🔐 Private keys saved to: {pks_path}")

    return True


def ensure_bootstrap(client: Optional[Client] = None) -> Client:
    """Ensure user has been bootstrapped with crypto keys

    Args:
        client: Optional SyftBox client instance

    Returns:
        Client: The client instance (loaded if not provided)

    Raises:
        RuntimeError: If DID exists but keys don't
        RuntimeError: If unresolved DID conflicts exist
        RuntimeError: If keys don't match DID document
    """
    if client is None:
        client = Client.load()

    # Construct paths to DID files
    did_file = client.datasites / client.config.email / "public" / "did.json"

    # Check for DID conflicts first
    did_conflict_file = (
        client.datasites / client.config.email / "public" / "did.conflict.json"
    )
    if did_conflict_file.exists():
        raise RuntimeError(
            f"❌ DID conflict detected: {did_conflict_file}\n"
            f"\n"
            f"Multiple versions of your identity exist.\n"
            f"\n"
            f"RESOLUTION:\n"
            f"  1. Check which DID matches your private keys\n"
            f"  2. Keep the correct version, delete: {did_conflict_file}\n"
            f"  3. Or delete both DIDs to recreate identity (⚠️ old encrypted data will become undecryptable):\n"
            f"     rm {did_file}\n"
            f"     rm {did_conflict_file}\n"
            f"     # Then restart application\n"
            f"\n"
        )

    # Auto-recovery: Keys exist but DID doesn't (safe to regenerate)
    if keys_exist(client) and not did_file.exists():
        logger.info(
            f"Private keys exist but DID missing for {client.config.email}. "
            f"Regenerating DID from existing keys..."
        )
        _regenerate_did_from_existing_keys(client)
        return client

    # Critical case: did.json exists but keys don't
    if did_file.exists() and not keys_exist(client):
        # Fail with comprehensive guidance
        key_path = private_key_path(client)
        raise RuntimeError(
            f"❌ PRIVATE KEYS MISSING BUT DID document EXISTS\n"
            f"\n"
            f"Your DID document exists but private keys are missing.\n"
            f"This usually happens in one of these scenarios:\n"
            f"\n"
            f"DID location: {did_file}\n"
            f"Expected keys: {key_path}\n"
            f"\n"
            f"🐳 DOCKER/CONTAINER SETUP (most common):\n"
            f"   Add persistent volumes for keys:\n"
            f"     docker run \\\n"
            f"       --volume syftbox-keys:/home/syftboxuser/.syftbox \\\n"
            f"       --volume syftbox-data:/home/syftboxuser/SyftBox \\\n"
            f"       [other options...]\n"
            f"\n"
            f"💻 NEW DEVICE SETUP:\n"
            f"   Import keys from your other device:\n"
            f"     # On original device:\n"
            f"     tar czf keys-backup.tar.gz ~/.syftbox/*/pvt.jwks.json\n"
            f"     # Transfer and restore on new device:\n"
            f"     tar xzf keys-backup.tar.gz -C ~/\n"
            f"\n"
            f"🗑️  KEYS DELETED/LOST:\n"
            f"   Restore from backup (if available):\n"
            f"     ls ~/.syftbox/backups/\n"
            f"   Or recreate identity (⚠️ old encrypted data will become undecryptable):\n"
            f"     rm {did_file}\n"
            f"     # Then restart application\n"
            f"\n"
            f"💬 Support: https://openmined.org/get-involved/\n"
        )

    # Safe to bootstrap - no DID exists
    if not keys_exist(client):
        logger.info(f"No keys found. Bootstrapping {client.config.email}...")
        bootstrap_user(client)
    else:
        logger.debug(f"✅ Keys exist for {client.config.email}")

    # Verify keys match DID (if both exist)
    if keys_exist(client) and did_file.exists():
        if not _verify_key_pair_matches(client):
            key_path = private_key_path(client)
            raise RuntimeError(
                f"❌ Crypto keys mismatch detected: Private keys don't match DID document\n"
                f"\n"
                f"Your local private keys don't match the public keys in your DID.\n"
                f"This happens when keys were regenerated but old DID still exists.\n"
                f"\n"
                f"DID location: {did_file}\n"
                f"Keys location: {key_path}\n"
                f"\n"
                f"SOLUTIONS:\n"
                f"\n"
                f"1. RESTORE ORIGINAL KEYS (if you have a backup):\n"
                f"   Copy the correct keys to: {key_path}\n"
                f"   Then restart\n"
                f"\n"
                f"2. RECREATE KEYS AND DID (⚠️ old encrypted data becomes undecryptable!):\n"
                f"   Delete DID manually:\n"
                f"     rm {did_file}\n"
                f"   Then restart application (will bootstrap fresh)\n"
                f"\n"
                f"💬 Support: https://openmined.org/get-involved/\n"
            )
        logger.debug(f"✅ Keys match DID for {client.config.email}")

    return client


def _verify_key_pair_matches(client: Client) -> bool:
    """Verify that local private keys match the public keys in DID document

    Args:
        client: SyftBox client instance

    Returns:
        bool: True if keys match DID, False otherwise
    """
    try:
        # Load private keys
        identity_private_key, spk_private_key = load_private_keys(client)

        # Derive public keys from private keys (deterministic)
        derived_identity_public = identity_private_key.public_key()
        derived_spk_public = spk_private_key.public_key()

        # Load DID document
        did_doc = get_did_document(client, client.config.email)

        # Extract public keys from DID
        did_identity_public = get_identity_public_key_from_did(did_doc)
        did_spk_public = get_public_key_from_did(did_doc)

        # Compare identity keys
        derived_identity_bytes = derived_identity_public.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        did_identity_bytes = did_identity_public.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        identity_match = derived_identity_bytes == did_identity_bytes

        # Compare SPK keys
        derived_spk_bytes = derived_spk_public.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        did_spk_bytes = did_spk_public.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        spk_match = derived_spk_bytes == did_spk_bytes

        if not identity_match:
            logger.error(
                f"❌ Identity key mismatch:\n"
                f"   Local key:  {derived_identity_bytes[:8].hex()}...\n"
                f"   DID key:    {did_identity_bytes[:8].hex()}..."
            )

        if not spk_match:
            logger.error(
                f"❌ SPK mismatch:\n"
                f"   Local key:  {derived_spk_bytes[:8].hex()}...\n"
                f"   DID key:    {did_spk_bytes[:8].hex()}..."
            )

        return identity_match and spk_match

    except Exception as e:
        logger.error(f"Failed to verify keys against DID: {e}")
        return False


def _regenerate_did_from_existing_keys(client: Client) -> None:
    """Regenerate DID document from existing private keys

    This is safe because DID is deterministically derived from keys.
    Use when keys exist but DID document is missing.

    Args:
        client: SyftBox client instance with existing private keys

    Raises:
        FileNotFoundError: If private keys don't exist
    """
    # Load existing private keys
    identity_private_key, spk_private_key = load_private_keys(client)

    # Get public keys from private keys (deterministic)
    identity_public_key = identity_private_key.public_key()
    spk_public_key = spk_private_key.public_key()

    # Sign the SPK with identity key (deterministic with same keys)
    spk_public_bytes = spk_public_key.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    spk_signature = identity_private_key.sign(spk_public_bytes)

    # Create DID document (will be identical to original)
    did_doc = create_x3dh_did_document(
        client.config.email,
        client.config.server_url.host,
        identity_public_key,
        spk_public_key,
        spk_signature,
    )

    # Save regenerated DID
    did_file = save_did_document(client, did_doc)
    logger.info(f"✅ Regenerated DID from existing keys: {did_file}")


if __name__ == "__main__":
    """Allow running bootstrap directly"""
    client = Client.load()
    bootstrap_user(client)
