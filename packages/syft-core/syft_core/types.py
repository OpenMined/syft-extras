from pathlib import Path
from typing import Iterable, Union
from pydantic import AfterValidator
from typing_extensions import Annotated

from typing_extensions import TypeAlias

__all__ = ["PathLike", "UserLike", "to_path", "RelativePath", "AbsolutePath"]

PathLike: TypeAlias = Union[str, Path]
UserLike: TypeAlias = Union[str, Iterable[str]]


def should_be_relative(v: Path) -> Path:
    if v.is_absolute():
        raise ValueError("path must be relative")
    return v


def should_be_absolute(v: Path) -> Path:
    if not v.is_absolute():
        raise ValueError("path must be absolute")
    return v


RelativePath = Annotated[Path, AfterValidator(should_be_relative)]

AbsolutePath = Annotated[Path, AfterValidator(should_be_absolute)]


def to_path(path: PathLike) -> Path:
    return Path(path).expanduser().resolve()
