from secrets import token_bytes

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def encrypt_data(data: bytes, bitlen=256) -> tuple[bytes, bytes, bytes]:
    key = AESGCM.generate_key(bit_length=bitlen)
    aesgcm = AESGCM(key)
    nonce = token_bytes(16)
    ct = aesgcm.encrypt(nonce, data, None)
    return key, nonce, ct


def decrypt_data(key: bytes, nonce: bytes, ct: bytes) -> bytes:
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None)
