from secrets import token_bytes

from rich import print
from syft_core import Client
from syft_encryption import KDF, norm_string
from syft_encryption.utils import b64_decode


def derive_datasite_keys(email: str, datasite_key: bytes, salt: bytes) -> dict:
    email = norm_string(email)
    master_key = KDF.derive_master_key(email, datasite_key, salt)
    kek = KDF.derive_kek_pvt_key(master_key)
    identity_key = KDF.derive_user_identity(master_key)
    xchange_key = KDF.derive_user_exchange_key(master_key)
    public = KDF.create_jwks(identity_key, xchange_key, as_dict=False)

    return {
        "master": master_key,
        "salt": salt,
        "kek": kek,
        "identity": identity_key,
        "exchange": xchange_key,
        "jwk": public,
    }


def main():
    client = Client.load()
    pubid_path = client.my_datasite / "public" / "pub.jwk"
    salt_path = client.my_datasite / "public" / "account.salt"

    # if pubid_path.exists() and salt_path.exists():
    #     print("Datasite keys have already been initialized")
    #     return

    datasite_key = token_bytes(32)
    salt = token_bytes(16)
    keys = derive_datasite_keys(client.email, datasite_key, salt)

    pubid_path.parent.mkdir(parents=True, exist_ok=True)

    salt_path.write_bytes(salt)
    pubid_path.write_text(keys["jwk"])

    print(f"\nYour unique datasite key: [bold green]{datasite_key.hex()}[/bold green]")
    print(
        "DO NOT SHARE."
        "It will be required to decrypt your files."
        "Save it in a secure location!"
    )
    print(f"\nPublic Keys generated at [white]{pubid_path}[white]")


def load():
    client = Client.load()
    pubid_path = client.my_datasite / "public" / "pub.jwk"
    salt_path = client.my_datasite / "public" / "account.salt"

    if not (pubid_path.exists() and salt_path.exists()):
        print("Error: Datasite keys haven't been initialized")
        return

    salt = salt_path.read_bytes()

    datasite_key = input("Enter your datasite key to unlock: ")
    datasite_key = b64_decode(datasite_key)
    keys = derive_datasite_keys(client.email, datasite_key, salt)

    salt_path = client.my_datasite / "public" / "account.salt"
    with salt_path.open("rb") as fp:
        salt = fp.read()

    vals = derive_datasite_keys(client.email, datasite_key, salt)
    print(vals)


if __name__ == "__main__":
    load()
