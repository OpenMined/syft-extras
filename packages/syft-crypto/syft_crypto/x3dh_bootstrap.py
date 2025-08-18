#!/usr/bin/env python3
"""
X3DH bootstrap module for generating keys and DID documents for SyftBox users
"""

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


def ensure_bootstrap(client: Optional[Client] = None) -> Client:
    """Ensure user has been bootstrapped with crypto keys

    Args:
        client: Optional SyftBox client instance

    Returns:
        Client: The client instance (loaded if not provided)
    """
    if client is None:
        client = Client.load()

    if not keys_exist(client):
        bootstrap_user(client)

    return client


if __name__ == "__main__":
    """Allow running bootstrap directly"""
    client = Client.load()
    bootstrap_user(client)
