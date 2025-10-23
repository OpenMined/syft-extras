#!/usr/bin/env python3
"""
X3DH bootstrap module for generating keys and DID documents for SyftBox users
"""

from datetime import datetime
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from loguru import logger
from syft_core import Client

from syft_crypto.did_utils import create_x3dh_did_document, save_did_document
from syft_crypto.key_storage import keys_exist, private_key_path, save_private_keys


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


def ensure_bootstrap(
    client: Optional[Client] = None, force_recreate_crypto_keys: bool = False
) -> Client:
    """Ensure user has been bootstrapped with crypto keys

    Args:
        client: Optional SyftBox client instance
        force_recreate_crypto_keys: If True, recreate keys even if DID exists.
                                WARNING: Makes old encrypted data unrecoverable!

    Returns:
        Client: The client instance (loaded if not provided)

    Raises:
        RuntimeError: If DID exists but keys don't (without force flag)
        RuntimeError: If unresolved DID conflicts exist
    """
    if client is None:
        client = Client.load()

    # Construct paths to DID files
    did_file = client.datasites / client.config.email / "public" / "did.json"
    did_conflict_file = (
        client.datasites / client.config.email / "public" / "did.conflict.json"
    )

    # Check for DID conflicts first
    if did_conflict_file.exists():
        raise RuntimeError(
            f"❌ DID conflict detected: {did_conflict_file}\n"
            f"\n"
            f"Multiple versions of your identity exist.\n"
            f"Manual resolution required:\n"
            f"  1. Check which DID matches your private keys\n"
            f"  2. Keep the correct version, delete the other\n"
            f"  3. See CRYPTOBUG_FIX.md for instructions\n"
        )

    # Critical case: did.json exists but keys don't
    if did_file.exists() and not keys_exist(client):
        if force_recreate_crypto_keys:
            logger.warning(
                "⚠️  RECREATING CRYPTO KEYS (force_recreate_crypto_keys=True)\n"
                "Old encrypted messages will become UNRECOVERABLE!"
            )
            # Archive old DID
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_file = did_file.parent / f"did.retired.{timestamp}.json"
            did_file.rename(archive_file)
            logger.info(f"📦 Old DID archived to: {archive_file}")

            # Generate new keys and DID
            bootstrap_user(client, force=True)

        else:
            # Fail with clear instructions
            key_path = private_key_path(client)
            raise RuntimeError(
                f"❌ DID DOCUMENT EXISTS BUT PRIVATE KEYS NOT FOUND\n"
                f"\n"
                f"DID location: {did_file}\n"
                f"Expected keys: {key_path}\n"
                f"\n"
                f"Common causes:\n"
                f"  • Container restart without persistent volume\n"
                f"  • Setting up same account on new device\n"
                f"  • Keys were deleted/lost\n"
                f"\n"
                f"SOLUTIONS:\n"
                f"\n"
                f"1. MOUNT PERSISTENT VOLUME (recommended for containers):\n"
                f"   docker run -v syftbox-keys:/home/syftboxuser/.syftbox ...\n"
                f"   Then restore keys or bootstrap once\n"
                f"\n"
                f"2. IMPORT KEYS from another device:\n"
                f"   Copy keys from working device to: {key_path}\n"
                f"\n"
                f"3. RECREATE KEYS (⚠️  WARNING: old encrypted data becomes unrecoverable!):\n"
                f"   Python API:\n"
                f"     from syft_crypto import ensure_bootstrap\n"
                f"     ensure_bootstrap(client, force_recreate_crypto_keys=True)\n"
                f"   \n"
            )

    # Safe to bootstrap - no DID exists
    if not keys_exist(client):
        logger.info(f"No keys found. Bootstrapping {client.config.email}...")
        bootstrap_user(client)
    else:
        logger.debug(f"✅ Keys exist for {client.config.email}")

    return client


if __name__ == "__main__":
    """Allow running bootstrap directly"""
    client = Client.load()
    bootstrap_user(client)
