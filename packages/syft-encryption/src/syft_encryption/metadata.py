import base64
import json
import os
from dataclasses import dataclass
from secrets import token_bytes
from typing import List, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass
class FileMetadata:
    """Represents metadata for an encrypted file"""

    file_path: str
    file_hash: str
    aes_key: bytes  # The key used to encrypt the actual file
    aes_nonce: bytes

    def to_dict(self) -> dict:
        """Convert to dictionary with base64 encoded bytes"""
        return {
            "file_path": self.file_path,
            "file_hash": self.file_hash,
            "aes_key": base64.b64encode(self.aes_key).decode("utf-8"),
            "aes_nonce": base64.b64encode(self.aes_nonce).decode("utf-8"),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileMetadata":
        """Create instance from dictionary with base64 encoded bytes"""
        return cls(
            file_path=data["file_path"],
            file_hash=data["file_hash"],
            aes_key=base64.b64decode(data["aes_key"]),
            aes_nonce=base64.b64decode(data["aes_nonce"]),
        )


class MetadataTable:
    """Manages a table of encrypted file metadata"""

    NONCE_LEN = 16

    def __init__(self, kek: bytes, meta_path: str):
        self.entries: List[FileMetadata] = []
        self.kek = kek
        self.meta_path = meta_path

    def add(
        self,
        file_path: str,
        file_hash: str,
        aes_key: bytes,
        aes_nonce: bytes,
    ):
        """Add a new entry to the table"""
        entry = FileMetadata(file_path, file_hash, aes_key, aes_nonce)
        self.entries.append(entry)
        self.save()

    def get(self, file_path: str) -> Optional[FileMetadata]:
        """Retrieve an entry by file path"""
        for entry in self.entries:
            if entry.file_path == file_path:
                return entry
        return None

    def save(self):
        """Save the metadata table to disk, encrypted with the KEK"""
        # Convert entries to list of dicts
        data = [entry.to_dict() for entry in self.entries]
        json_data = json.dumps(data)

        # Encrypt the JSON data
        aesgcm = AESGCM(self.kek)
        nonce = token_bytes(self.NONCE_LEN)
        encrypted_data = aesgcm.encrypt(nonce, json_data.encode(), None)

        # Save encrypted data with nonce
        with open(self.meta_path, "wb") as f:
            f.write(nonce + encrypted_data)

    @classmethod
    def load(cls, meta_path: str, kek: bytes):
        """Load and decrypt the metadata table from disk using the KEK"""
        with open(meta_path, "rb") as f:
            data = f.read()

        # Split nonce and encrypted data
        nonce = data[: cls.NONCE_LEN]
        encrypted_data = data[cls.NONCE_LEN :]

        # Decrypt the data
        aesgcm = AESGCM(kek)
        json_data = aesgcm.decrypt(nonce, encrypted_data, None)

        # Parse the JSON and create entries
        data_list = json.loads(json_data)

        # Create instance and populate entries
        cls = cls(kek, meta_path)
        cls.entries = [FileMetadata.from_dict(item) for item in data_list]
        return cls


if __name__ == "__main__":
    kek = base64.b64decode("DEEoLmeLwSaRhDW7lOgX1MtpoK29TqJRR5bchz2+6Gs=")
    meta_path = "metadata.enc"
    if os.path.exists(meta_path):
        table = MetadataTable.load(meta_path, kek)
    # else:
    #     table = MetadataTable(kek, meta_path)
    # table.add(f"kdf-{token_hex(4)}.py", "import sys", token_bytes(32), token_bytes(16))
    # table.add(
    #     f"kdf-{token_hex(4)}.txt", "hello rasswanth", token_bytes(32), token_bytes(16)
    # )

    print(table.entries)
