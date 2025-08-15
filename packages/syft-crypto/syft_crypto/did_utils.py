"""
DID (Decentralized Identifier) utilities for SyftBox
"""

import base64
import json
import urllib.parse
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from syft_core import Client

from syft_crypto.key_storage import key_to_jwk


def generate_did_web_id(email: str, domain: str = "syftbox.net") -> str:
    """Generate a did:web identifier from email

    Args:
        email: User's email address
        domain: Domain for the DID (default: syftbox.net)

    Returns:
        str: The did:web identifier
    """
    encoded_email = urllib.parse.quote(email, safe="")
    return f"did:web:{domain}:{encoded_email}"


def did_path(client: Client, user: Optional[str] = None) -> Path:
    """Get the path to a user's DID document

    Args:
        client: SyftBox client instance
        user: Email of the user (defaults to current user)

    Returns:
        Path: Path to the DID document
    """
    if user is None:
        user = client.config.email
    return client.datasites / user / "public" / "did.json"


def get_did_document(client: Client, user: str) -> dict:
    """Load and return a user's DID document

    Args:
        client: SyftBox client instance
        user: Email of the user whose DID to load

    Returns:
        dict: The DID document

    Raises:
        FileNotFoundError: If DID document doesn't exist
        json.JSONDecodeError: If DID document is malformed
    """
    did_file = did_path(client, user)

    if not did_file.exists():
        raise FileNotFoundError(f"No DID document found for {user} at {did_file}")

    with open(did_file, "r") as f:
        return json.load(f)


def save_did_document(
    client: Client, did_doc: dict, user: Optional[str] = None
) -> Path:
    """Save a DID document to the appropriate location

    Args:
        client: SyftBox client instance
        did_doc: The DID document to save
        user: Email of the user (defaults to current user)

    Returns:
        Path: Path where the document was saved
    """
    did_file = did_path(client, user)
    did_file.parent.mkdir(parents=True, exist_ok=True)

    with open(did_file, "w") as f:
        json.dump(did_doc, f, indent=2)

    return did_file


def create_x3dh_did_document(
    email: str,
    domain: str,
    identity_public_key: ed25519.Ed25519PublicKey,
    signed_prekey_public_key: x25519.X25519PublicKey,
    spk_signature: bytes,
) -> dict:
    """Create a DID document with X3DH keys

    Args:
        email: User's email address
        domain: Domain for the DID
        identity_public_key: Ed25519 identity key
        signed_prekey_public_key: X25519 signed prekey
        spk_signature: Signature of the signed prekey

    Returns:
        dict: The DID document
    """
    did_id = generate_did_web_id(email, domain)

    # Convert keys to JWK format
    identity_jwk = key_to_jwk(identity_public_key, "identity-key")
    spk_jwk = key_to_jwk(signed_prekey_public_key, "signed-prekey")

    # Add signature to the SPK
    spk_jwk["signature"] = base64.urlsafe_b64encode(spk_signature).decode().rstrip("=")

    return {
        "@context": [
            "https://www.w3.org/ns/did/v1",
            "https://w3id.org/security/suites/ed25519-2020/v1",
            "https://w3id.org/security/suites/x25519-2020/v1",
        ],
        "id": did_id,
        "verificationMethod": [
            {
                "id": f"{did_id}#identity-key",
                "type": "Ed25519VerificationKey2020",
                "controller": did_id,
                "publicKeyJwk": identity_jwk,
            }
        ],
        "keyAgreement": [
            {
                "id": f"{did_id}#signed-prekey",
                "type": "X25519KeyAgreementKey2020",
                "controller": did_id,
                "publicKeyJwk": spk_jwk,
            }
        ],
    }


def get_public_key_from_did(
    did_doc: dict, key_type: str = "signed-prekey"
) -> x25519.X25519PublicKey:
    """Extract and reconstruct public key from DID document

    Args:
        did_doc: The DID document
        key_type: Type of key to extract ("signed-prekey" for X3DH)

    Returns:
        X25519PublicKey: The reconstructed public key

    Raises:
        ValueError: If key not found in DID document
    """
    key_jwk = None
    for key_agreement in did_doc.get("keyAgreement", []):
        if key_agreement["id"].endswith(f"#{key_type}"):
            key_jwk = key_agreement["publicKeyJwk"]
            break

    if not key_jwk:
        raise ValueError(f"No {key_type} found in DID document")

    # Reconstruct public key from JWK
    return x25519.X25519PublicKey.from_public_bytes(
        base64.urlsafe_b64decode(key_jwk["x"] + "===")
    )
