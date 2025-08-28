# SyftCrypto: End-to-End Encryption for SyftBox

SyftCrypto provides cryptography utilities for SyftBox, implementing a simplified X3DH protocol for secure, asynchronous communication between federated computation participants.

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
  - [Phase 0: Keys Bootstrapping & Publishing](#phase-0-keys-bootstrapping--publishing)
  - [Phase 1: Alice Sends Encrypted Message](#phase-1-alice-sends-encrypted-message)
  - [Phase 2: Bob Decrypts Message](#phase-2-bob-decrypts-message)
  - [Phase 3: Secure Bidirectional Communication](#phase-3-secure-bidirectional-communication)
- [Installation](#installation)
- [Quick Start](#quick-start)
  - [1. Bootstrap User Keys](#1-bootstrap-user-keys)
  - [2. Encrypt a Message](#2-encrypt-a-message)
  - [3. Decrypt a Message](#3-decrypt-a-message)
- [API Reference](#api-reference)
  - [Core Functions](#core-functions)
  - [Data Structures](#data-structures)
  - [Utility Functions](#utility-functions)
- [File Locations](#file-locations)
  - [Private Keys](#private-keys)
  - [Public Keys (DID Documents)](#public-keys-did-documents)
- [Security Properties](#security-properties)
  - [Cryptographic Guarantees](#cryptographic-guarantees)
  - [Key Management](#key-management)
  - [Protocol Security](#protocol-security)
- [Simplified vs Full X3DH Trade-offs](#simplified-vs-full-x3dh-trade-offs)
- [Dependencies](#dependencies)
- [Development](#development)
  - [Running Tests](#running-tests)
  - [Project Structure](#project-structure)
- [Contributing](#contributing)
- [End-to-End Encryption Integration in SyftBox](#end-to-end-encryption-integration-in-syftbox)
  - [Integration Overview](#integration-overview)
  - [Integration Architecture](#integration-architecture)
  - [How It Works](#how-it-works)
  - [Key Integration Points](#key-integration-points)
  - [Encryption Flow Example](#encryption-flow-example)
  - [Security Features](#security-features)
  - [Configuration Options](#configuration-options)
  - [Best Practices](#best-practices)
  - [Testing Encryption](#testing-encryption)
  - [Integration Summary](#integration-summary)
- [References](#references)

## Overview

SyftCrypto enables secure message exchange in SyftBox using a custom implementation of the X3DH (Extended Triple Diffie-Hellman) protocol. This implementation provides forward secrecy, mutual authentication, and asynchronous communication capabilities tailored for federated computation use cases.

![x3dh-overview](./docs/e2e-encryption.png)

## Key Features

- **Forward Secrecy**: Fresh ephemeral keys per message prevent retroactive decryption
- **Mutual Authentication**: Signed prekeys provide cryptographic proof of identity
- **Asynchronous Communication**: DID documents enable offline key exchange
- **Deniability**: No permanent signatures on message contents (only on prekeys)
- **Simplified Protocol**: 2 DH operations instead of 4 for better performance
- **Standards-Based**: Uses W3C DID documents and JWK key formats

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
  "verificationMethod": [
    {
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
    }
  ],
  "keyAgreement": [
    {
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
    }
  ]
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

| Feature               | Full X3DH | SyftCrypto |
| --------------------- | --------- | ---------- |
| DH Operations         | 4         | 2          |
| One-time PreKeys      |           | L          |
| Identity Key DH       |           | L          |
| Forward Secrecy       |           |            |
| Mutual Authentication |           |            |
| Performance           | Slower    | Faster     |
| Key Management        | Complex   | Simplified |

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
syft-crypto/
  ├── docs/                                   # Documentation and diagrams
  ├── syft_crypto/                           # Main package directory
  │   ├── __init__.py                        # Package initialization and public API exports
  │   ├── did_utils.py                       # DID document management and utilities
  │   ├── key_storage.py                     # Secure private key storage and JWK handling
  │   ├── x3dh_bootstrap.py                  # User key generation and bootstrapping
  │   └── x3dh.py                           # Core X3DH encryption/decryption protocol
  ├── tests/                                 # Test suite for all functionality
  ├── pyproject.toml                         # Project configuration and dependencies
  └── README.md                             # Documentation with API reference and examples
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

# End-to-End Encryption Integration in SyftBox

This section explains how syft-crypto's X3DH encryption is integrated into `syft-rpc` and `syft-event` for secure RPC communication.

## Integration Overview

SyftBox provides seamless end-to-end encryption for RPC messages using the X3DH protocol described above. The encryption layer is transparently integrated into the RPC stack, allowing applications to send encrypted messages with minimal code changes.

## Integration Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                       │
│  • Makes RPC calls with encrypt=True flag                  │
│  • Handles requests with auto-decryption                   │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                     syft-event Layer                       │
│  • Auto-detects encrypted requests                         │
│  • Decrypts before handler execution                       │
│  • Re-encrypts responses if needed                         │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      syft-rpc Layer                        │
│  • Serializes objects to bytes                             │
│  • Applies encryption if requested                         │
│  • Manages encryption parameters                           │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    syft-crypto Layer                       │
│  • X3DH key exchange protocol                              │
│  • AES-GCM encryption/decryption                           │
│  • DID document management                                 │
└─────────────────────────────────────────────────────────────┘
```

## How It Works

### 1. Sending Encrypted RPC Requests (syft-rpc)

When sending an RPC request with encryption:

```python
from syft_rpc.rpc import send, make_url

# Create encrypted request
future = send(
    url=make_url("bob@example.com", "myapp", "endpoint"),
    body={"secret": "data"},
    encrypt=True,  # Enable encryption
    client=alice_client
)
```

**Under the hood (syft_rpc/rpc.py):**

1. The `send()` function extracts the recipient from the URL
2. Calls `serialize()` with encryption parameters
3. `serialize()` converts the body to bytes, then:
   - Auto-bootstraps encryption keys if needed
   - Calls `encrypt_message()` from syft-crypto
   - Returns an `EncryptedPayload` as JSON bytes
4. The encrypted payload is written to the filesystem as a `.request` file

### 2. Receiving & Auto-Decrypting Requests (syft-event)

When receiving an encrypted request:

```python
from syft_event import SyftEvents

events = SyftEvents("myapp")

@events.on_request("/endpoint", auto_decrypt=True, encrypt_reply=False)  # Defaults to False for backward compatibility
def handle_request(data: dict):
    # data is automatically decrypted
    return {"response": "processed"}

# Or with encrypted replies
@events.on_request("/secure_endpoint", auto_decrypt=True, encrypt_reply=True)
def handle_secure(data: dict):
    # data is auto-decrypted, response will be auto-encrypted
    return {"secret_response": "confidential"}
```

**Under the hood (syft_event/server2.py):**

1. `SyftEvents` detects incoming `.request` files
2. `_process_encrypted_request()` checks if body is an `EncryptedPayload`
3. If encrypted and recipient matches:
   - Calls `decrypt_message()` from syft-crypto
   - Replaces request body with decrypted data
   - Adds headers to indicate decryption occurred
4. Handler receives plain decrypted data

### 3. Sending Encrypted Responses (syft-rpc)

When replying with encryption:

```python
from syft_rpc.rpc import reply_to

response = reply_to(
    request=received_request,
    body={"result": "secret_data"},
    encrypt=True,  # Encrypt response
    client=bob_client
)
```

**Under the hood:**

1. `reply_to()` extracts the original sender as recipient
2. Uses same `serialize()` mechanism as requests
3. Encrypted response written to filesystem

## Key Integration Points

### syft-rpc Integration

**File: `syft_rpc/rpc.py`**

- **`serialize()` function (lines 61-122):**

  - Accepts `encrypt`, `recipient`, and `client` parameters
  - Handles encryption after standard serialization
  - Auto-bootstraps keys via `ensure_bootstrap()`

- **`send()` function (lines 124-220):**

  - Accepts `encrypt` flag
  - Extracts recipient from URL
  - Disables caching for encrypted requests (ephemeral keys)

- **`reply_to()` function (lines 270-320):**
  - Supports `encrypt` flag for responses
  - Uses request sender as recipient

### syft-event Integration

**File: `syft_event/server2.py`**

- **`_process_encrypted_request()` method (lines 102-155):**

  - Auto-detects `EncryptedPayload` in request body
  - Decrypts if recipient matches current client
  - Preserves original sender in headers

- **`on_request()` decorator (lines 258-279):**

  - `auto_decrypt=True` by default - automatically tries to decrypt incoming requests
  - `encrypt_reply=False` by default - can be enabled to auto-encrypt responses
  - Both can be configured per handler

- **Automatic response encryption (lines 430-450):**
  - When `encrypt_reply=True`, responses are automatically encrypted
  - Uses original request sender as encryption recipient
  - Handles both success and error responses

## Encryption Flow Example

Here's a complete flow of an encrypted RPC call:

```python
# 1. Alice sends encrypted request to Bob
from syft_rpc import send, make_url

future = send(
    url=make_url("bob@example.com", "calculator", "add"),
    body={"a": 5, "b": 3},
    encrypt=True
)

# 2. Bob's event handler auto-decrypts request AND auto-encrypts response
from syft_event import SyftEvents

events = SyftEvents("calculator")

@events.on_request("/add", auto_decrypt=True, encrypt_reply=True)
def add_numbers(data: dict):
    # data is auto-decrypted: {"a": 5, "b": 3}
    result = data["a"] + data["b"]
    return {"result": result}  # Will be auto-encrypted back to Alice

# 3. The response is automatically encrypted and sent back
# No manual reply_to needed when using encrypt_reply=True!

# 4. Alice receives and needs to decrypt the response
# (Note: future.result() doesn't auto-decrypt, Alice needs to handle this)
```

## Security Features

### Automatic Key Bootstrapping

Both syft-rpc and syft-event automatically bootstrap encryption keys when needed:

```python
# In syft_rpc/rpc.py
if enc_params.encrypt:
    if not enc_params.client:
        enc_params.client = Client.load()

    # Auto-bootstrap keys if not present
    enc_params.client = ensure_bootstrap(enc_params.client)
```

### Encryption Metadata

Decrypted requests include metadata headers:

```python
# Added by syft-event after decryption
req.headers["X-Syft-Decrypted"] = "true"
req.headers["X-Syft-Original-Sender"] = encrypted_payload.sender
```

### Smart Caching

syft-rpc automatically disables caching for encrypted requests:

```python
# In send() function
if cache is None:
    cache = not encrypt  # Default to False when encrypting
```

This prevents ineffective caching since each encryption uses unique ephemeral keys.

## Configuration Options

### Disabling Auto-Decryption

For handlers that need to process encrypted payloads directly:

```python
@events.on_request("/raw_handler", auto_decrypt=False)
def handle_raw(request: SyftRequest):
    # request.body contains raw EncryptedPayload
    encrypted = EncryptedPayload.model_validate_json(request.body)
    # Manual processing...
```

### Debug Mode

Enable debug logging for encryption operations:

```python
events = SyftEvents("myapp", debug_mode=True)
```

## Best Practices

1. **Always use encryption for sensitive data:**

   ```python
   send(url=url, body=sensitive_data, encrypt=True)
   ```

2. **Let auto-decryption handle most cases:**

   - Default `auto_decrypt=True` works for most handlers
   - Only disable for special cases (e.g., proxy services)

3. **Don't cache encrypted requests:**

   - Each encryption uses unique ephemeral keys
   - Caching provides no benefit and wastes storage

4. **Bootstrap keys early:**

   ```python
   from syft_crypto import ensure_bootstrap
   client = ensure_bootstrap()  # Do this once at startup
   ```

5. **Check decryption headers when needed:**
   ```python
   @events.on_request("/handler")
   def handler(request: Request):
       if request.headers.get("X-Syft-Decrypted"):
           sender = request.headers["X-Syft-Original-Sender"]
           # Handle decrypted message
   ```

## Testing Encryption

### Unit Tests

Test encryption/decryption in isolation:

```python
from syft_crypto import encrypt_message, decrypt_message

# Test encryption
encrypted = encrypt_message("test", "bob@example.com", alice_client)
assert encrypted.sender == "alice@example.com"
assert encrypted.receiver == "bob@example.com"

# Test decryption
decrypted = decrypt_message(encrypted, bob_client)
assert decrypted == "test"
```

### Integration Tests

Test full RPC flow with encryption:

```python
def test_encrypted_roundtrip(alice_events, bob_client):
    # Setup handler with auto-encrypt response
    @alice_events.on_request("/secure", auto_decrypt=True, encrypt_reply=True)
    def secure_handler(data: dict, request: Request):
        # Verify decryption metadata
        assert request.headers["X-Syft-Decrypted"] == "true"
        assert request.headers["X-Syft-Original-Sender"] == bob_client.email
        return {"response": f"processed {data['message']}"}

    # Bob sends encrypted request to Alice
    encrypted_req = encrypt_message(
        json.dumps({"message": "secret"}),
        alice_events.client.email,
        bob_client
    )

    # Create and save request
    request = SyftRequest(
        sender=bob_client.email,
        url=make_url(alice_events.client.email, "app", "secure"),
        body=encrypted_req.model_dump_json().encode()
    )
    request.dump(request_path)

    # Process request (handler auto-decrypts and auto-encrypts response)
    alice_events._SyftEvents__handle_rpc(request_path, handler)

    # Load and verify encrypted response
    response = SyftResponse.load(response_path)
    encrypted_response = EncryptedPayload.model_validate_json(response.body)

    # Verify encryption addressing
    assert encrypted_response.sender == alice_events.client.email
    assert encrypted_response.receiver == bob_client.email

    # Bob decrypts response
    decrypted = decrypt_message(encrypted_response, bob_client)
    assert json.loads(decrypted)["response"] == "processed secret"
```

## Integration Summary

The integration provides:

- **Transparent encryption** - Just add `encrypt=True` to RPC calls
- **Automatic decryption** - Handlers receive plain data by default
- **Smart defaults** - Caching disabled for encrypted requests
- **Key auto-bootstrap** - Keys generated on first use
- **Metadata preservation** - Original sender tracked through decryption

This design makes end-to-end encryption simple to use while maintaining security and performance.

## References

- [X3DH Specification](https://signal.org/docs/specifications/x3dh/) - Original Signal protocol
- [W3C DID Core](https://www.w3.org/TR/did-core/) - Decentralized Identifier standard
- [RFC 7517](https://tools.ietf.org/html/rfc7517) - JSON Web Key (JWK) format
- [SyftBox Documentation](https://syftbox.openmined.org/) - Federated computation platform
