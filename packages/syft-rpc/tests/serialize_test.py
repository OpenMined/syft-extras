from pydantic import AnyHttpUrl, IPvAnyAddress
from syft_rpc.rpc import serialize


def test_simple():
    assert serialize(1) == b"1"
    assert serialize(1.111112) == b"1.111112"
    assert serialize([1, 2, 3]) == b"[1, 2, 3]"
    assert serialize("test_string") == b"test_string"
    assert serialize(None) is None


def test_dict():
    assert serialize({"key": "value"}) == b'{"key":"value"}'
    assert serialize({"key": {"nested": [1, 2, 3]}}) == b'{"key":{"nested":[1,2,3]}}'


def test_pydantic():
    from pydantic import BaseModel

    class NestedModel(BaseModel):
        url: AnyHttpUrl
        ip: IPvAnyAddress

    class Model(BaseModel):
        key: str
        value: NestedModel

    obj = Model(
        key="test",
        value=NestedModel(
            url="https://syftbox.openmined.org/",
            ip=IPvAnyAddress("127.0.0.1"),
        ),
    )

    assert (
        serialize(obj)
        == b'{"key":"test","value":{"url":"https://syftbox.openmined.org/","ip":"127.0.0.1"}}'
    )


def test_dataclass():
    from dataclasses import dataclass

    @dataclass
    class NestedModel:
        items: list

    @dataclass
    class Model:
        key: str
        value: NestedModel

    obj = Model(
        key="test",
        value=NestedModel(items=[1, 2, 3]),
    )

    assert serialize(obj) == b'{"key":"test","value":{"items":[1,2,3]}}'
