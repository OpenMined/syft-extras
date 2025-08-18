"""
Key storage and management utilities for SyftBox
"""

import hashlib
import json
from pathlib import Path
from typing import Tuple, Union

from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from jwcrypto import jwk
from syft_core import Client


def private_key_path(client: Client) -> Path:
    """Get the path to store private keys as JWKs securely

    Args:
        client: SyftBox client instance

    Returns:
        Path: Path to the private keys file
    """
    partition = f"{client.config.server_url}::{client.config.email}"
    partitionHash = hashlib.sha256(partition.encode()).hexdigest()
    syftbox_dir = client.workspace.data_dir.parent / ".syftbox" / partitionHash[:8]
    syftbox_dir.mkdir(exist_ok=True, parents=True)
    return syftbox_dir / "pvt.jwks.json"


def save_private_keys(client: Client, identity_private_key, spk_private_key) -> Path:
    """Save private keys securely as JWKs

    Args:
        client: SyftBox client instance
        identity_private_key: Ed25519 identity private key
        spk_private_key: X25519 signed prekey private key

    Returns:
        Path: Path where keys were saved
    """
    # Convert to JWK format
    identity_jwk = jwk.JWK.from_pyca(identity_private_key)
    spk_jwk = jwk.JWK.from_pyca(spk_private_key)

    private_keys = {
        "identity_key": identity_jwk.export(as_dict=True),
        "signed_prekey": spk_jwk.export(as_dict=True),
    }

    pks_path = private_key_path(client)
    pks_path.parent.mkdir(parents=True, exist_ok=True)

    with open(pks_path, "w") as f:
        json.dump(private_keys, f, indent=2)
    
    # Set restrictive permissions (owner read/write only)
    import os
    os.chmod(pks_path, 0o600)

    return pks_path


def load_private_keys(client: Client) -> Tuple:
    """Load private keys from JWK storage

    Args:
        client: SyftBox client instance

    Returns:
        tuple: (identity_private_key, spk_private_key)

    Raises:
        FileNotFoundError: If private keys have not been generated
        ValueError: If key file is invalid or corrupted
    """
    key_path = private_key_path(client)
    if not key_path.exists():
        raise FileNotFoundError(
            f"Private keys not found at {key_path}. Run bootstrap_user() first."
        )

    with open(key_path, "r") as f:
        keys_data = json.load(f)
    
    # Validate key structure
    if not isinstance(keys_data, dict):
        raise ValueError("Invalid key file: expected dictionary")
    
    if "identity_key" not in keys_data:
        raise KeyError("Missing identity_key in key file")
    
    if "signed_prekey" not in keys_data:
        raise KeyError("Missing signed_prekey in key file")
    
    # Validate each key is a dict with required fields
    for key_name in ["identity_key", "signed_prekey"]:
        key = keys_data[key_name]
        if not isinstance(key, dict):
            raise ValueError(f"{key_name} must be a dictionary")
        if "kty" not in key:
            raise KeyError(f"{key_name} missing required field 'kty'")

    # Reconstruct private keys from JWKs
    try:
        identity_jwk = jwk.JWK.from_json(json.dumps(keys_data["identity_key"]))
        spk_jwk = jwk.JWK.from_json(json.dumps(keys_data["signed_prekey"]))
    except (jwk.InvalidJWKType, jwk.InvalidJWKValue) as e:
        raise ValueError(f"Invalid JWK format: {e}")

    # Convert back to cryptography objects using correct jwcrypto API
    identity_private_key = identity_jwk.get_op_key("sign")  # Ed25519 for signing
    spk_private_key = spk_jwk.get_op_key("unwrapKey")  # X25519 for key exchange

    return identity_private_key, spk_private_key


def keys_exist(client: Client) -> bool:
    """Check if private keys exist for the client

    Args:
        client: SyftBox client instance

    Returns:
        bool: True if keys exist, False otherwise
    """
    return private_key_path(client).exists()


def key_to_jwk(
    public_key: Union[ed25519.Ed25519PublicKey, x25519.X25519PublicKey], key_id: str
) -> dict:
    """Convert a cryptography public key to JWK format using jwcrypto

    Args:
        public_key: The public key to convert
        key_id: Identifier for the key

    Returns:
        dict: JWK representation of the key
    """
    jwk_key = jwk.JWK.from_pyca(public_key)
    jwk_dict = jwk_key.export_public(as_dict=True)

    # Add metadata
    jwk_dict["kid"] = key_id
    if isinstance(public_key, ed25519.Ed25519PublicKey):
        jwk_dict["use"] = "sig"
    elif isinstance(public_key, x25519.X25519PublicKey):
        jwk_dict["use"] = "enc"

    return jwk_dict
