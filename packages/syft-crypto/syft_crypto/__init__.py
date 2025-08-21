"""
SyftCrypto: Cryptography utilities for SyftBox
"""

# DID utilities
from syft_crypto.did_utils import (
    create_x3dh_did_document,
    did_path,
    generate_did_web_id,
    get_did_document,
    get_public_key_from_did,
    save_did_document,
)

# Key storage utilities
from syft_crypto.key_storage import (
    key_to_jwk,
    keys_exist,
    load_private_keys,
    private_key_path,
    save_private_keys,
)

# X3DH protocol implementation
from syft_crypto.x3dh import (
    EncryptedPayload,
    decrypt_message,
    encrypt_message,
)

# X3DH bootstrap utilities
from syft_crypto.x3dh_bootstrap import (
    bootstrap_user,
    ensure_bootstrap,
)

__all__ = [
    # DID utilities
    "create_x3dh_did_document",
    "did_path",
    "generate_did_web_id",
    "get_did_document",
    "save_did_document",
    "get_public_key_from_did",
    # Key storage
    "key_to_jwk",
    "keys_exist",
    "load_private_keys",
    "private_key_path",
    "save_private_keys",
    # X3DH protocol
    "EncryptedPayload",
    "decrypt_message",
    "encrypt_message",
    # X3DH bootstrap
    "bootstrap_user",
    "ensure_bootstrap",
]

__version__ = "0.1.1"
