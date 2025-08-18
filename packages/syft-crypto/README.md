# SyftCrypto: End-to-End Encryption for SyftBox

SyftCrypto provides cryptography utilities for SyftBox, implementing a simplified X3DH protocol for secure, asynchronous communication between federated computation participants.

## Overview

SyftCrypto enables secure message exchange in SyftBox using a custom implementation of the X3DH (Extended Triple Diffie-Hellman) protocol. This implementation provides forward secrecy, mutual authentication, and asynchronous communication capabilities tailored for federated computation use cases.


![x3dh-overview](./docs/e2e-encryption.png)


## Key Features

- **= Forward Secrecy**: Fresh ephemeral keys per message prevent retroactive decryption
- **= Mutual Authentication**: Signed prekeys provide cryptographic proof of identity  
- **=� Asynchronous Communication**: DID documents enable offline key exchange
- **=� Deniability**: No permanent signatures on message contents (only on prekeys)
- **=� Simplified Protocol**: 2 DH operations instead of 4 for better performance
- **=� Standards-Based**: Uses W3C DID documents and JWK key formats

## Architecture

The protocol flow consists of four main phases:

### Phase 0: Keys Bootstrapping & Publishing
Both Alice and Bob generate their cryptographic identities:
1. Generate Identity Key (Ed25519) for signing prekeys
2. Generate Signed PreKey (X25519) for key exchange  
3. Sign the prekey with the identity key
4. Save private keys securely to `~/.syftbox/{hash}/pvt.jwks.json`
5. Create DID document at `{datasite}/public/did.json`

### Phase 1: Alice Sends Encrypted Message
1. Download Bob's DID document to get his signed prekey
2. Generate ephemeral key pair for this message
3. Perform custom X3DH key exchange:
   - `DH1 = DH(SPK_alice, SPK_bob)` - Authentication  
   - `DH2 = DH(EK_alice, SPK_bob)` - Forward secrecy
4. Derive shared secret: `shared_key = HKDF(DH1 || DH2)`
5. Encrypt message using AES-GCM with shared key
6. Upload encrypted payload: `{ek, iv, ciphertext, tag, sender, receiver}`

### Phase 2: Bob Decrypts Message  
1. Download encrypted payload from Alice
2. Load Alice's DID document to get her signed prekey
3. Reconstruct Alice's ephemeral key from payload
4. Perform same X3DH operations to derive identical shared key
5. Decrypt message using AES-GCM

### Phase 3: Secure Bidirectional Communication
The same process enables Bob to send encrypted responses to Alice, establishing secure bidirectional communication.

## Installation

```bash
pip install syft-crypto
```

## Quick Start

### 1. Bootstrap User Keys
```python
from syft_crypto import bootstrap_user, ensure_bootstrap
from syft_core import Client

# Load SyftBox client
client = Client.load()

# Generate keys and DID document
bootstrap_user(client)

# Or ensure keys exist (generates if needed)
client = ensure_bootstrap()
```

### 2. Encrypt a Message
```python
from syft_crypto import encrypt_message

# Encrypt message for recipient
encrypted_payload = encrypt_message(
    message="Hello Bob!",
    to="bob@example.com", 
    client=client,
    verbose=True
)

# encrypted_payload is ready to send via SyftBox
```

### 3. Decrypt a Message
```python
from syft_crypto import decrypt_message

# Decrypt received payload
plaintext = decrypt_message(
    payload=encrypted_payload,
    client=client,
    verbose=True
)

print(f"Decrypted: {plaintext}")
```

## API Reference

### Core Functions

#### `bootstrap_user(client: Client, force: bool = False) -> bool`
Generate X3DH keypairs and create DID document for a user.

**Parameters:**
- `client`: SyftBox client instance
- `force`: If True, regenerate keys even if they exist

**Returns:**
- `bool`: True if keys were generated, False if they already existed

#### `encrypt_message(message: str, to: str, client: Client, verbose: bool = False) -> EncryptedPayload`
Encrypt message using X3DH protocol.

**Parameters:**
- `message`: The plaintext message to encrypt
- `to`: Email of the recipient
- `client`: SyftBox client instance
- `verbose`: If True, log status messages

**Returns:**
- `EncryptedPayload`: The encrypted message payload

#### `decrypt_message(payload: EncryptedPayload, client: Client, verbose: bool = False) -> str`
Decrypt message using X3DH protocol.

**Parameters:**
- `payload`: The encrypted message payload
- `client`: SyftBox client instance  
- `verbose`: If True, log status messages

**Returns:**
- `str`: The decrypted plaintext message

### Data Structures

#### `EncryptedPayload`
```python
class EncryptedPayload(BaseModel):
    ek: bytes          # Ephemeral key
    iv: bytes          # Initialization vector
    ciphertext: bytes  # Encrypted message
    tag: bytes         # Authentication tag
    sender: str        # Sender's email
    receiver: str      # Receiver's email  
    version: str       # Protocol version
```

### Utility Functions

#### DID Document Management
- `create_x3dh_did_document()`: Create DID document with X3DH keys
- `get_did_document()`: Load user's DID document
- `save_did_document()`: Save DID document to appropriate location
- `get_public_key_from_did()`: Extract public key from DID document

#### Key Storage
- `save_private_keys()`: Save private keys securely as JWKs
- `load_private_keys()`: Load private keys from JWK storage
- `keys_exist()`: Check if private keys exist
- `key_to_jwk()`: Convert public key to JWK format

## File Locations

### Private Keys
Private keys are stored securely at:
```
~/.syftbox/{sha256(server::email)[:8]}/pvt.jwks.json
```

Example format:
```json
{
  "identity_key": {
    "kty": "OKP",
    "crv": "Ed25519", 
    "x": "adfasfxxx342",
    "d": "1231adfer334"
  },
  "signed_prekey": {
    "kty": "OKP",
    "crv": "X25519",
    "x": "X-HElnE4yZc0bMhAAqkyhAn4", 
    "d": "GBiBZnLVzEiZ2qN5T7adfaWQ"
  }
}
```

### Public Keys (DID Documents)
Public keys are published as W3C DID documents at:
```
{datasite}/public/did.json
```

Example DID document:
```json
{
  "@context": [
    "https://www.w3.org/ns/did/v1",
    "https://w3id.org/security/suites/ed25519-2020/v1", 
    "https://w3id.org/security/suites/x25519-2020/v1"
  ],
  "id": "did:web:syftbox.net:alice%40example.com",
  "verificationMethod": [{
    "id": "did:web:syftbox.net:alice%40example.com#identity-key",
    "type": "Ed25519VerificationKey2020",
    "controller": "did:web:syftbox.net:alice%40example.com",
    "publicKeyJwk": {
      "kty": "OKP",
      "crv": "Ed25519",
      "x": "oAXB82sUeKHqjKhqGOjsoed1OfksDD9rcZUyOjDnYrs",
      "kid": "identity-key",
      "use": "sig"
    }
  }],
  "keyAgreement": [{
    "id": "did:web:syftbox.net:alice%40example.com#signed-prekey", 
    "type": "X25519KeyAgreementKey2020",
    "controller": "did:web:syftbox.net:alice%40example.com",
    "publicKeyJwk": {
      "kty": "OKP",
      "crv": "X25519",
      "x": "X-HElnE48aUIpBjfyZesdT2gtM4a8c0bMhAAqkyhAn4",
      "kid": "signed-prekey", 
      "use": "enc",
      "signature": "b4XuL6T8SbLyFrNrhK18eB0_mU1D6CQ"
    }
  }]
}
```

## Security Properties

### Cryptographic Guarantees
- **Forward Secrecy**: Fresh ephemeral keys prevent retroactive decryption if long-term keys are compromised
- **Mutual Authentication**: Both parties' signed prekeys provide cryptographic proof of identity
- **Deniability**: Message contents aren't permanently signed, providing plausible deniability
- **Asynchronous Security**: Recipients don't need to be online during key exchange

### Key Management
- Private keys stored in secure local directories using SHA-256 hashed paths
- Public keys published in standardized W3C DID documents
- Identity keys used only for signing prekeys, never for direct encryption
- Ephemeral keys generated fresh for each message

### Protocol Security
The custom X3DH implementation uses:
- **2 DH operations** instead of full X3DH's 4 operations for better performance
- **HKDF-SHA256** for key derivation with domain separation
- **AES-GCM** for authenticated encryption
- **Ed25519** signatures for prekey authentication
- **X25519** for Elliptic Curve Diffie-Hellman operations

## Simplified vs Full X3DH Trade-offs

| Feature | Full X3DH | SyftCrypto |
|---------|-----------|------------|
| DH Operations | 4 | 2 |
| One-time PreKeys |  | L |
| Identity Key DH |  | L |
| Forward Secrecy |  |  |
| Mutual Authentication |  |  |
| Performance | Slower | Faster |
| Key Management | Complex | Simplified |

The simplified approach maintains core security properties while reducing complexity and improving performance for SyftBox's federated computation use cases.

## Dependencies

- `cryptography`: Core cryptographic primitives
- `jwcrypto`: JSON Web Key handling
- `pydantic`: Data validation and serialization  
- `syft-core`: SyftBox client integration
- `loguru`: Structured logging

## Development

### Running Tests
```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ -v --cov=syft_crypto --cov-report=term-missing

# Run specific test categories
pytest tests/x3dh_encryption_test.py  # Core encryption tests
pytest tests/bootstrap_test.py         # Key bootstrapping tests
pytest tests/crypto_security_test.py   # Security property tests
pytest tests/key_management_test.py    # Key lifecycle tests
pytest tests/message_integrity_test.py # Message integrity tests
pytest tests/protocol_security_test.py # Protocol security tests
pytest tests/attack_resilience_test.py # Attack resistance tests
```

### Project Structure
```
packages/syft-crypto/
   syft_crypto/
      __init__.py           # Public API exports
      x3dh.py              # Core X3DH encryption/decryption
      x3dh_bootstrap.py    # Key generation and bootstrapping
      did_utils.py         # DID document management
      key_storage.py       # Secure key storage utilities
   tests/                   # Test suite
   docs/                    # Documentation and diagrams
   README.md               # This file
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

This project is part of the OpenMined ecosystem. Please refer to the main repository for licensing information.

## References

- [X3DH Specification](https://signal.org/docs/specifications/x3dh/) - Original Signal protocol
- [W3C DID Core](https://www.w3.org/TR/did-core/) - Decentralized Identifier standard
- [RFC 7517](https://tools.ietf.org/html/rfc7517) - JSON Web Key (JWK) format
- [SyftBox Documentation](https://syftbox.openmined.org/) - Federated computation platform