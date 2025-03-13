from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from jwcrypto import jwk

from syft_encryption.utils import b64, b64_decode, norm_string


class KDF:
    def derive_master_key(email: bytes, token: bytes, salt: bytes) -> bytes:
        sha2 = hashes.SHA256()
        # email hmac
        hkdf = HKDF(algorithm=sha2, length=32, salt=salt, info=b"master-key-email")
        hmac_email = hkdf.derive(email)

        # token hmac
        hkdf = HKDF(algorithm=sha2, length=32, salt=salt, info=b"master-key-token")
        hmac_token = hkdf.derive(token)

        # xor the hmacs
        intermediate = bytes([a ^ b for a, b in zip(hmac_email, hmac_token)])

        # final hmac
        hkdf = HKDF(algorithm=sha2, length=32, salt=salt, info=b"master-key")
        return hkdf.derive(intermediate)

    def master_key_from_bytes(master_key: str) -> bytes:
        return b64_decode(master_key)

    def derive_user_identity(master_key: bytes) -> Ed25519PrivateKey:
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"user-identity-ed25519",
        )
        ed_seed = hkdf.derive(master_key)
        ed_private = Ed25519PrivateKey.from_private_bytes(ed_seed)
        return ed_private

    def derive_user_exchange_key(master_key: bytes) -> X25519PrivateKey:
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"user-exchange-x25519",
        )
        x_seed = hkdf.derive(master_key)
        x_private = X25519PrivateKey.from_private_bytes(x_seed)
        return x_private

    def derive_kek_pvt_key(master_key: bytes) -> bytes:
        hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"user-kek")
        return hkdf.derive(master_key)

    def create_jwks(
        ed_public: Ed25519PublicKey, x_public: X25519PublicKey, as_dict=True
    ) -> dict:
        ed_key = jwk.JWK.from_pyca(ed_public)
        x_key = jwk.JWK.from_pyca(x_public)

        ed_key.update({"use": "sig"})
        x_key.update({"use": "enc"})

        key_set = jwk.JWKSet()
        key_set.add(ed_key)
        key_set.add(x_key)

        return key_set.export(as_dict=as_dict, private_keys=False)

    def jwks_from_dict(jwks: dict) -> jwk.JWKSet:
        return jwk.JWKSet.from_json(jwks)


if __name__ == "__main__":
    datasite_token = b"SHOULD-BE-RANDOM-DATASITE-TOKEN"
    salt = b"some-random-salt"
    email = norm_string("TEST@OPENMINED.ORG")

    master_key = KDF.derive_master_key(email, datasite_token, salt)
    print("Email:", email)
    print("Datasite Token:", b64(datasite_token))
    print("Master Key:", b64(master_key))
    print(
        "Public JWKS:",
        KDF.create_jwks(
            KDF.derive_user_identity(master_key).public_key(),
            KDF.derive_user_exchange_key(master_key).public_key(),
        ),
    )
    print("Metadata KEK:", b64(KDF.derive_kek_pvt_key(master_key)))
