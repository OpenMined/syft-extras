"""
X3DH (Extended Triple Diffie-Hellman) protocol implementation for SyftBox
"""

import base64
import os
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from loguru import logger
from pydantic import BaseModel, Field, field_serializer, field_validator
from syft_core import Client

from syft_crypto.did_utils import get_did_document, get_public_key_from_did
from syft_crypto.key_storage import load_private_keys


class EncryptedPayload(BaseModel):
    """Encrypted message payload using X3DH protocol"""

    ek: bytes = Field(..., description="Ephemeral key")
    iv: bytes = Field(..., description="Initialization vector")
    ciphertext: bytes = Field(..., description="Encrypted message")
    tag: bytes = Field(..., description="Authentication tag")
    sender: str = Field(..., description="Sender's email")
    receiver: str = Field(..., description="Receiver's email")
    version: str = Field(default="1.0", description="Encryption protocol version")

    # Serialize bytes fields to base64 for JSON
    @field_serializer("ek", "iv", "ciphertext", "tag")
    def serialize_bytes(self, value: bytes) -> str:
        return base64.b64encode(value).decode("utf-8")

    # Validate and deserialize base64 strings back to bytes
    @field_validator("ek", "iv", "ciphertext", "tag", mode="before")
    @classmethod
    def validate_bytes(cls, value: Any) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            try:
                return base64.b64decode(value)
            except Exception as e:
                raise ValueError(f"Invalid base64 string: {e}")
        raise ValueError(f"Expected bytes or base64 string, got {type(value)}")


def _verify_signed_prekey(did_doc: dict, spk_public: x25519.X25519PublicKey) -> None:
    """Verify the signed prekey signature from DID document

    Args:
        did_doc: The DID document containing the signature
        spk_public: The signed prekey public key to verify

    Raises:
        ValueError: If signature verification fails
    """
    # Extract identity public key
    identity_jwk = did_doc["verificationMethod"][0]["publicKeyJwk"]
    identity_public = ed25519.Ed25519PublicKey.from_public_bytes(
        base64.urlsafe_b64decode(identity_jwk["x"] + "===")
    )

    # Extract signature from signed prekey
    spk_jwk = did_doc["keyAgreement"][0]["publicKeyJwk"]
    if "signature" not in spk_jwk:
        raise ValueError("No signature found on signed prekey")

    signature_bytes = base64.urlsafe_b64decode(spk_jwk["signature"] + "===")

    # Get the signed prekey public bytes
    spk_public_bytes = spk_public.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )

    # Verify signature - will raise exception if invalid
    try:
        identity_public.verify(signature_bytes, spk_public_bytes)
    except Exception as e:
        raise ValueError(f"Signed prekey signature verification failed: {e}")


def encrypt_message(
    message: str, to: str, client: Client, verbose: bool = False
) -> EncryptedPayload:
    """Encrypt message using X3DH protocol

    Args:
        message: The plaintext message to encrypt
        to: Email of the recipient
        client: SyftBox client instance
        verbose: If True, logger.info status messages

    Returns:
        EncryptedPayload: The encrypted message payload

    Raises:
        FileNotFoundError: If recipient's DID document not found
        ValueError: If recipient's DID document is invalid
    """
    # Load receiver's DID document
    receiver_did = get_did_document(client, to)

    # Extract receiver's public key
    receiver_spk_public = get_public_key_from_did(receiver_did)

    # Verify the signed prekey signature before proceeding
    _verify_signed_prekey(receiver_did, receiver_spk_public)

    # Load our private keys
    _, spk_private_key = load_private_keys(client)

    # Generate ephemeral key pair
    ephemeral_private = x25519.X25519PrivateKey.generate()
    ephemeral_public = ephemeral_private.public_key()

    # Perform X3DH key agreement
    # DH1 = DH(SPK_a, SPK_b) - our private signed prekey with their public signed prekey
    dh1 = spk_private_key.exchange(receiver_spk_public)

    # DH2 = DH(EK_a, SPK_b) - our private ephemeral key with their public signed prekey
    dh2 = ephemeral_private.exchange(receiver_spk_public)

    # Derive shared secret using HKDF
    shared_key_material = dh1 + dh2
    shared_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"X3DH-SyftBox",
        backend=default_backend(),
    ).derive(shared_key_material)

    # Encrypt the message using AES-GCM
    iv = os.urandom(
        12
    )  # nonce to prevent replay attacks (each encryption uses fresh randomness)
    cipher = Cipher(
        algorithms.AES(shared_key), modes.GCM(iv), backend=default_backend()
    )
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(message.encode()) + encryptor.finalize()

    # Create the encrypted payload
    encrypted_payload = EncryptedPayload(
        ek=ephemeral_public.public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        ),  # the public ephemeral key
        iv=iv,
        ciphertext=ciphertext,
        tag=encryptor.tag,
        sender=client.config.email,
        receiver=to,
    )

    if verbose:
        logger.info(f"🔒 Encrypted message for {to}")

    return encrypted_payload


def decrypt_message(
    payload: EncryptedPayload, client: Client, verbose: bool = False
) -> str:
    """Decrypt message using X3DH protocol

    Args:
        payload: The encrypted message payload
        client: SyftBox client instance
        verbose: If True, logger.info status messages

    Returns:
        str: The decrypted plaintext message

    Raises:
        FileNotFoundError: If sender's DID document not found
        ValueError: If decryption fails or payload is invalid
    """
    # Verify we are the intended recipient
    if payload.receiver != client.config.email:
        raise ValueError(
            f"Message is for {payload.receiver}, not {client.config.email}"
        )

    # Load sender's DID document
    sender_did = get_did_document(client, payload.sender)

    # Extract sender's public key
    sender_spk_public = get_public_key_from_did(sender_did)

    # Verify the sender's signed prekey signature
    _verify_signed_prekey(sender_did, sender_spk_public)

    # Reconstruct sender's ephemeral public key
    sender_ephemeral_public = x25519.X25519PublicKey.from_public_bytes(payload.ek)

    # Load our private keys
    _, spk_private_key = load_private_keys(client)

    # Perform X3DH key agreement (reverse of encryption)
    # DH1 = DH(SPK_b, SPK_a) - our signed prekey with their signed prekey
    dh1 = spk_private_key.exchange(sender_spk_public)

    # DH2 = DH(SPK_b, EK_a) - our signed prekey with their ephemeral key
    dh2 = spk_private_key.exchange(sender_ephemeral_public)

    # Derive shared secret using HKDF (it's a symmetric secret key (32 bytes))
    shared_key_material = dh1 + dh2
    shared_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"X3DH-SyftBox",
        backend=default_backend(),
    ).derive(shared_key_material)

    # Decrypt the message using AES-GCM
    cipher = Cipher(
        algorithms.AES(shared_key),
        modes.GCM(payload.iv, payload.tag),
        backend=default_backend(),
    )
    decryptor = cipher.decryptor()

    try:
        decrypted_bytes = decryptor.update(payload.ciphertext) + decryptor.finalize()
    except Exception as e:
        if verbose:
            logger.error(f"Decryption failed with error: {e}")
        raise ValueError(f"Decryption failed: {e}")

    message = decrypted_bytes.decode()

    if verbose:
        logger.info(f"🔓 Decrypted message from {payload.sender}")

    return message
