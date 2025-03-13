import base64


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode()


def b64_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s)


def norm_string(s: str) -> bytes:
    return s.strip().lower().encode("utf-8")
