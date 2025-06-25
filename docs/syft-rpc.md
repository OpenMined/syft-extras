# Syft-RPC Package Documentation

## Overview

The `syft-rpc` package provides the foundational RPC (Remote Procedure Call) protocol and serialization mechanisms for the SyftBox ecosystem. It handles the low-level details of serializing Python objects, managing RPC communication, and ensuring data integrity across distributed systems.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          syft-rpc                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐ │
│  │   Protocol   │    │     RPC      │    │    RPC_DB        │ │
│  │              │    │              │    │                  │ │
│  │ - Serialize  │    │ - Server     │    │ - Store RPCs     │ │
│  │ - Deserialize│    │ - Client     │    │ - Track status   │ │
│  │ - Type map   │    │ - Handlers   │    │ - Query history  │ │
│  │ - Rebuild    │    │              │    │                  │ │
│  └──────────────┘    └──────────────┘    └──────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Type System                            │  │
│  │                                                           │  │
│  │  Basic Types: int, str, float, bool, bytes, None        │  │
│  │  Collections: list, tuple, dict, set                     │  │
│  │  Complex: Pydantic models, dataclasses, custom objects   │  │
│  │                                                           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Serialization Protocol

The protocol handles serialization of Python objects into a format that can be transmitted and reconstructed:

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│  Python Object  │      │  Serialized     │      │  Python Object  │
│                 │      │  Representation │      │                 │
│  - Native types │ ───► │  - Type info    │ ───► │  - Restored     │
│  - Pydantic     │      │  - Data bytes   │      │  - Same type    │
│  - Dataclasses  │      │  - Metadata     │      │  - Same value   │
└─────────────────┘      └─────────────────┘      └─────────────────┘
     serialize()              transmit              deserialize()
```

### Serialization Format

Each serialized object contains:
```python
{
    "__type__": "module.ClassName",      # Type identifier
    "__version__": 1,                     # Protocol version
    "data": {...},                        # Actual data
    "__metadata__": {...}                 # Optional metadata
}
```

## Core Components

### 1. Protocol Module

The protocol module handles the core serialization logic:

```python
from syft_rpc.protocol import serialize, deserialize, rebuild

# Serialize any Python object
data = {"users": ["alice", "bob"], "count": 2}
serialized = serialize(data)  # Returns bytes

# Deserialize back to Python object
restored = deserialize(serialized)
assert restored == data

# Rebuild with type information
from pydantic import BaseModel

class User(BaseModel):
    name: str
    email: str

user = User(name="Alice", email="alice@example.com")
serialized = serialize(user)

# On the receiving end
rebuilt_user = rebuild(deserialize(serialized))
assert isinstance(rebuilt_user, User)
assert rebuilt_user.name == "Alice"
```

### 2. Type Registration

The protocol maintains a registry of serializable types:

```python
from syft_rpc.protocol import register_type, get_type_string

# Register custom type
@register_type
class CustomData:
    def __init__(self, value):
        self.value = value
    
    def to_dict(self):
        return {"value": self.value}
    
    @classmethod
    def from_dict(cls, data):
        return cls(data["value"])

# Type string for serialization
type_string = get_type_string(CustomData)  # "module.CustomData"
```

### 3. RPC Communication

Basic RPC server and client implementation:

```python
from syft_rpc.rpc import RPCServer, RPCClient

# Server side
server = RPCServer()

@server.register
def add(a: int, b: int) -> int:
    return a + b

@server.register
def get_user(user_id: str) -> dict:
    return {"id": user_id, "name": "Alice"}

# Start server
server.serve(host="localhost", port=8000)

# Client side
client = RPCClient("localhost", 8000)

# Call remote functions
result = client.call("add", a=5, b=3)
print(result)  # 8

user = client.call("get_user", user_id="123")
print(user)  # {"id": "123", "name": "Alice"}
```

## Serialization Examples

### Basic Types

```python
from syft_rpc.protocol import serialize, deserialize

# Numbers
assert deserialize(serialize(42)) == 42
assert deserialize(serialize(3.14)) == 3.14

# Strings and bytes
assert deserialize(serialize("Hello")) == "Hello"
assert deserialize(serialize(b"Binary")) == b"Binary"

# Collections
data = {
    "list": [1, 2, 3],
    "tuple": (4, 5, 6),
    "set": {7, 8, 9},
    "dict": {"nested": True}
}
assert deserialize(serialize(data)) == data
```

### Pydantic Models

```python
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class Task(BaseModel):
    id: str
    title: str
    completed: bool = False
    tags: List[str] = []
    due_date: Optional[datetime] = None

# Create and serialize
task = Task(
    id="task-001",
    title="Write documentation",
    tags=["docs", "important"],
    due_date=datetime.now()
)

serialized = serialize(task)
restored_task = rebuild(deserialize(serialized))

assert isinstance(restored_task, Task)
assert restored_task.id == "task-001"
assert restored_task.tags == ["docs", "important"]
```

### Dataclasses

```python
from dataclasses import dataclass
from typing import List

@dataclass
class Product:
    name: str
    price: float
    categories: List[str]
    in_stock: bool = True

product = Product(
    name="Laptop",
    price=999.99,
    categories=["Electronics", "Computers"]
)

# Serialize and restore
serialized = serialize(product)
restored = rebuild(deserialize(serialized))

assert isinstance(restored, Product)
assert restored.price == 999.99
```

### Complex Nested Structures

```python
@dataclass
class Address:
    street: str
    city: str
    country: str

class Person(BaseModel):
    name: str
    age: int
    address: Address
    friends: List['Person'] = []

# Create complex structure
alice_addr = Address("123 Main St", "Boston", "USA")
alice = Person(name="Alice", age=30, address=alice_addr)

bob_addr = Address("456 Oak Ave", "Seattle", "USA")
bob = Person(name="Bob", age=28, address=bob_addr)

alice.friends.append(bob)
bob.friends.append(alice)

# Serialize with circular references
serialized = serialize(alice)
restored_alice = rebuild(deserialize(serialized))

assert restored_alice.name == "Alice"
assert restored_alice.friends[0].name == "Bob"
assert isinstance(restored_alice.address, Address)
```

## UTF-8 Support

The protocol fully supports UTF-8 encoded data:

```python
from syft_rpc.protocol import serialize, deserialize

# International characters
data = {
    "english": "Hello",
    "spanish": "Hola",
    "chinese": "你好",
    "arabic": "مرحبا",
    "emoji": "👋🌍"
}

serialized = serialize(data)
restored = deserialize(serialized)

for key, value in data.items():
    assert restored[key] == value
```

## RPC Database

Track and manage RPC calls with the database module:

```python
from syft_rpc.rpc_db import RPCDatabase

# Initialize database
db = RPCDatabase("rpc_history.db")

# Log RPC call
call_id = db.log_call(
    method="get_user",
    params={"user_id": "123"},
    caller="alice@example.com"
)

# Update with result
db.update_result(call_id, result={"name": "Alice", "id": "123"})

# Query history
recent_calls = db.get_recent_calls(limit=10)
user_calls = db.get_calls_by_method("get_user")
```

## Error Handling

The protocol includes comprehensive error handling:

```python
from syft_rpc.protocol import SerializationError, DeserializationError

try:
    # Attempt to serialize non-serializable object
    serialize(lambda x: x)  # Functions can't be serialized
except SerializationError as e:
    print(f"Serialization failed: {e}")

try:
    # Attempt to deserialize corrupted data
    deserialize(b"corrupted data")
except DeserializationError as e:
    print(f"Deserialization failed: {e}")

# Safe serialization with fallback
def safe_serialize(obj, fallback=None):
    try:
        return serialize(obj)
    except SerializationError:
        if fallback is not None:
            return serialize(fallback)
        return serialize({"error": "Could not serialize object"})
```

## Performance Optimization

### 1. Batch Operations

```python
from syft_rpc.protocol import serialize_batch, deserialize_batch

# Serialize multiple objects efficiently
objects = [
    {"id": 1, "data": "first"},
    {"id": 2, "data": "second"},
    {"id": 3, "data": "third"},
]

# Batch serialization
serialized_batch = serialize_batch(objects)

# Batch deserialization
restored_objects = deserialize_batch(serialized_batch)
assert len(restored_objects) == 3
```

### 2. Compression

```python
import zlib
from syft_rpc.protocol import serialize, deserialize

def compress_serialize(obj):
    serialized = serialize(obj)
    compressed = zlib.compress(serialized)
    return compressed

def decompress_deserialize(compressed):
    decompressed = zlib.decompress(compressed)
    return deserialize(decompressed)

# Large data structure
large_data = {"items": [{"id": i, "data": "x" * 1000} for i in range(100)]}

# Compare sizes
normal = serialize(large_data)
compressed = compress_serialize(large_data)
print(f"Normal: {len(normal)} bytes")
print(f"Compressed: {len(compressed)} bytes")
print(f"Compression ratio: {len(compressed) / len(normal):.2%}")
```

### 3. Caching

```python
from functools import lru_cache
import hashlib

@lru_cache(maxsize=1000)
def cached_serialize(obj_hash):
    # Cache serialization results for repeated objects
    return _do_serialize(obj_hash)

def smart_serialize(obj):
    # Create hash of object
    obj_bytes = str(obj).encode()
    obj_hash = hashlib.sha256(obj_bytes).hexdigest()
    
    # Use cached result if available
    return cached_serialize(obj_hash)
```

## Security Considerations

### 1. Type Validation

```python
from syft_rpc.protocol import set_allowed_types, SerializationError

# Restrict allowed types for security
set_allowed_types([
    int, str, float, bool, list, dict,
    "myapp.models.User",  # Specific allowed class
    "myapp.models.Task",
])

# This will now fail
try:
    serialize(eval)  # Dangerous function
except SerializationError as e:
    print("Blocked dangerous type")
```

### 2. Size Limits

```python
from syft_rpc.protocol import set_size_limit

# Set maximum serialized size (10MB)
set_size_limit(10 * 1024 * 1024)

# Large objects will be rejected
huge_list = list(range(10_000_000))
try:
    serialize(huge_list)
except SerializationError as e:
    print("Object too large")
```

### 3. Sanitization

```python
def sanitize_before_deserialize(data: bytes) -> bytes:
    # Check for suspicious patterns
    if b"__import__" in data or b"eval" in data:
        raise ValueError("Potentially malicious data")
    return data

# Safe deserialization
def safe_deserialize(data: bytes):
    sanitized = sanitize_before_deserialize(data)
    return deserialize(sanitized)
```

## Integration with Other Packages

### With syft-event

```python
from syft_event import Request, Response
from syft_rpc.protocol import serialize, deserialize

# Serialize request for transport
request = Request(
    id="123",
    sender="alice@example.com",
    url=SyftBoxURL("syft://bob@example.com/app_data/api/rpc/data"),
    method="POST",
    body=serialize({"action": "get_data", "filters": {"active": True}})
)

# On receiving end
data = deserialize(request.body)
# Process data...
```

### With syft-proxy

```python
from syft_proxy.models import RPCSendRequest
from syft_rpc.protocol import serialize

# Prepare RPC request with serialized data
rpc_request = RPCSendRequest(
    app_name="data_processor",
    destination="carol@example.com",
    params=serialize({
        "operation": "aggregate",
        "data": [1, 2, 3, 4, 5]
    })
)
```

## Best Practices

1. **Always validate deserialized data** - Don't trust external data
2. **Use type hints** - Helps with serialization and documentation
3. **Handle errors gracefully** - Network issues can corrupt data
4. **Version your protocols** - For backward compatibility
5. **Monitor performance** - Serialization can be CPU intensive
6. **Implement timeouts** - For RPC calls
7. **Log important operations** - For debugging and auditing

## Testing

```python
import pytest
from syft_rpc.protocol import serialize, deserialize, rebuild

def test_round_trip():
    """Test that data survives serialization round trip."""
    test_data = {
        "string": "test",
        "number": 42,
        "float": 3.14,
        "bool": True,
        "none": None,
        "list": [1, 2, 3],
        "dict": {"nested": "value"}
    }
    
    serialized = serialize(test_data)
    restored = deserialize(serialized)
    
    assert restored == test_data

def test_pydantic_model():
    """Test Pydantic model serialization."""
    from pydantic import BaseModel
    
    class TestModel(BaseModel):
        name: str
        value: int
    
    model = TestModel(name="test", value=123)
    serialized = serialize(model)
    restored = rebuild(deserialize(serialized))
    
    assert isinstance(restored, TestModel)
    assert restored.name == "test"
    assert restored.value == 123

def test_error_handling():
    """Test error handling for invalid data."""
    with pytest.raises(Exception):
        deserialize(b"invalid data")
    
    with pytest.raises(Exception):
        deserialize(b"")
```

## Troubleshooting

Common issues and solutions:

1. **Import errors after deserialization**
   - Ensure all custom classes are imported before deserializing
   - Use `rebuild()` instead of raw `deserialize()`

2. **Circular reference errors**
   - The protocol handles most circular references
   - For complex cases, implement custom serialization

3. **Performance issues**
   - Use batch operations for multiple objects
   - Consider compression for large data
   - Profile serialization bottlenecks

4. **Type mismatch errors**
   - Ensure sender and receiver have same class definitions
   - Use version checking for protocol compatibility