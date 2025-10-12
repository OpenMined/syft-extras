from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError
from syft_core.url import SyftBoxURL
from syft_core.workspace import SyftWorkspace


class UrlModel(BaseModel):
    """Test model to verify SyftBoxURL works with Pydantic V2"""

    url: SyftBoxURL


def test_valid_urls():
    """Test that valid syft:// URLs are accepted"""
    valid_urls = [
        "syft://user@example.com/path/to/file",
        "syft://test.user@domain.org/data",
        "syft://admin@server.io",
        "syft://user+tag@example.com/file",
        "syft://user_name@example.com/path",
    ]

    for url_str in valid_urls:
        # Test direct instantiation
        url = SyftBoxURL(url_str)
        assert str(url) == url_str

        # Test in Pydantic model
        model = UrlModel(url=url_str)
        assert isinstance(model.url, SyftBoxURL)
        assert str(model.url) == url_str


def test_invalid_urls():
    """Test that invalid URLs are rejected"""
    invalid_urls = [
        "http://example.com",
        "https://example.com",
        "ftp://user@example.com",
        "syft://invalid",
        "not_a_url",
        "syft://no-at-sign.com",
        "",
    ]

    for url_str in invalid_urls:
        # Test direct instantiation fails
        with pytest.raises(ValueError):
            SyftBoxURL(url_str)

        # Test Pydantic validation fails
        with pytest.raises(ValidationError):
            UrlModel(url=url_str)


def test_url_properties():
    """Test URL property accessors"""
    url = SyftBoxURL("syft://user@example.com/path/to/file")

    assert url.protocol == "syft://"
    assert url.host == "user@example.com"
    assert url.path == "/path/to/file"


def test_url_query_params():
    """Test query parameter parsing"""
    url = SyftBoxURL("syft://user@example.com/path?key1=value1&key2=value2")

    query = url.query
    assert query["key1"] == "value1"
    assert query["key2"] == "value2"


def test_url_no_query_params():
    """Test URL without query parameters"""
    url = SyftBoxURL("syft://user@example.com/path")

    assert url.query == {}


def test_to_local_path(tmp_path: Path):
    """Test conversion to local filesystem path"""
    datasites_path = tmp_path / "datasites"
    url = SyftBoxURL("syft://user@example.com/data/file.txt")

    local_path = url.to_local_path(datasites_path)

    expected = (datasites_path / "user@example.com" / "data" / "file.txt").resolve()
    assert local_path == expected


def test_as_http_params():
    """Test HTTP parameter conversion"""
    url = SyftBoxURL("syft://user@example.com/path/to/file")

    params = url.as_http_params()

    assert params["method"] == "get"
    assert params["datasite"] == "user@example.com"
    assert params["path"] == "/path/to/file"


def test_to_http_get():
    """Test HTTP GET URL conversion"""
    url = SyftBoxURL("syft://user@example.com/path")

    http_url = url.to_http_get("http://rpc.example.com")

    assert "rpc.example.com" in http_url
    assert "method=get" in http_url
    assert "datasite=user%40example.com" in http_url
    assert "path=%2Fpath" in http_url


def test_from_path(tmp_path: Path):
    """Test creating URL from filesystem path"""
    datasites_path = tmp_path / "datasites"
    datasites_path.mkdir(parents=True, exist_ok=True)

    # Create a test file path
    test_path = datasites_path / "user@example.com" / "data" / "file.txt"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.touch()

    # Create workspace
    workspace = SyftWorkspace(tmp_path)

    # Convert path to URL
    url = SyftBoxURL.from_path(test_path, workspace)

    assert str(url).startswith("syft://")
    assert "user@example.com" in str(url)


def test_pydantic_json_schema():
    """Test that JSON schema is properly defined"""
    schema = UrlModel.model_json_schema()

    assert "url" in schema["properties"]
    url_schema = schema["properties"]["url"]
    assert url_schema["type"] == "string"
    assert url_schema["format"] == "uri"


def test_pydantic_serialization():
    """Test that SyftBoxURL serializes correctly in Pydantic models"""
    url_str = "syft://user@example.com/path"
    model = UrlModel(url=url_str)

    # Test model_dump
    dumped = model.model_dump()
    assert dumped["url"] == url_str

    # Test model_dump_json
    json_str = model.model_dump_json()
    assert url_str in json_str
