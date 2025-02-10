from pydantic import BaseModel
from syft_rpc.protocol import SyftResponse
from syft_rpc.rpc import serialize


class DummyObject(BaseModel):
    utf8: list[str]


def test_utf8_dict():
    obj = {"utf8": ["👍", "🆗"]}
    response = SyftResponse(
        url="syft://test@domain.com/test",
        status_code=200,
        sender="test",
        headers={},
        body=serialize(obj),
    )

    assert response.text() == '{"utf8": ["👍", "🆗"]}'
    assert response.json()["utf8"] == ["👍", "🆗"]
    assert '"eyJ1dGY4IjogWyLwn5GNIiwgIvCfhpciXX0=' in response.model_dump_json()


def test_utf8_pydantic():
    obj = DummyObject(utf8=["👍", "🆗"])

    response = SyftResponse(
        url="syft://test@domain.com/test",
        status_code=200,
        sender="test",
        headers={},
        body=serialize(obj),
    )

    assert response.text() == '{"utf8":["👍","🆗"]}'
    assert response.json()["utf8"] == ["👍", "🆗"]
    assert "eyJ1dGY4IjpbIvCfkY0iLCLwn4aXIl19" in response.model_dump_json()


def test_rebuild_utf8_dict():
    obj = {"utf8": ["👍", "🆗"]}
    response = SyftResponse(
        url="syft://test@domain.com/test",
        status_code=200,
        sender="test",
        headers={},
        body=serialize(obj),
    )
    serialized_response = response.dumps()

    rebuilt_response = SyftResponse.loads(serialized_response)

    assert rebuilt_response.json()["utf8"] == ["👍", "🆗"]
    assert rebuilt_response.text() == '{"utf8": ["👍", "🆗"]}'


def test_rebuild_utf8_pydantic():
    obj = DummyObject(utf8=["👍", "🆗"])

    response = SyftResponse(
        url="syft://test@domain.com/test",
        status_code=200,
        sender="test",
        headers={},
        body=serialize(obj),
    )
    serialized_response = response.dumps()

    rebuilt_response = SyftResponse.loads(serialized_response)
    assert rebuilt_response.json()["utf8"] == ["👍", "🆗"]
    assert rebuilt_response.text() == '{"utf8":["👍","🆗"]}'
