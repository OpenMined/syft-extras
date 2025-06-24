# SyftBox Extras

Building blocks for SyftBox applications to communicate with each other and external services.

## Overview

SyftBox Extras provides essential packages that enable:
- 🔐 **Secure file permissions** with the new `syft.pub.yaml` format
- 🌐 **Inter-app communication** via `syft://` URLs
- 🔌 **External API integration** through HTTP bridging
- 📦 **Object serialization** for distributed communication
- 🏗️ **Application scaffolding** with client and workspace management

## Architecture

The packages serve different layers of the SyftBox communication stack:

```
┌─────────────────────────────────────────────────────────────────┐
│                      Application Layer                          │
│  • SyftBox Apps use these packages for communication            │
│  • Receive data via syft:// or http:// URLs                     │
│  • Use syft-core for permissions and client management          │
└─────────────────────────────────────────────────────────────────┘
                               │
┌─────────────────────────────────────────────────────────────────┐
│                    Communication Layer                          │
│  • syft-event: Handles syft:// URLs with routing                │
│  • syft-http-bridge: Bridges HTTP ↔ filesystem                  │
│  • syft-rpc: Request/Response serialization                     │
└─────────────────────────────────────────────────────────────────┘
                               │
┌─────────────────────────────────────────────────────────────────┐
│                   Infrastructure Layer                          │
│  • SyftBox Cache Server: Optional Encrypted data routing        │
│  • No direct TCP connections needed                             │
└─────────────────────────────────────────────────────────────────┘
```

## Packages

### [syft-core](docs/syft-core.md)
Foundation package providing client configuration, workspace management, and the new permissions system.

**Key Features:**
- 📝 New `syft.pub.yaml` permission format with terminal flags
- 🔄 Auto-conversion from old `syftperm.yaml` format
- 🏠 Workspace and datasite management
- 🔗 SyftBox URL handling

### [syft-event](docs/syft-event.md)
Event-driven RPC system for handling `syft://` URL requests between applications.

**Key Features:**
- 🚀 Simple routing with `@router.on_request()`
- 📨 Request/Response pattern
- 👀 Filesystem watching for events
- 🗺️ Automatic schema generation

### [syft-rpc](docs/syft-rpc.md)
Low-level serialization protocol supporting complex Python objects and RPC primitives.

**Key Features:**
- 🔄 Serialize/deserialize Python objects
- 📦 Support for Pydantic models and dataclasses
- 🌍 Full UTF-8 support
- 🔒 Type validation and security

### [syft-http-bridge](docs/syft-http-bridge.md)
Enables SyftBox apps to communicate with external HTTP APIs through filesystem transport.

**Key Features:**
- 🌐 HTTP client that works through filesystem
- 📤 Automatic request/response serialization
- 🔐 Host whitelisting for security
- ⚡ Connection pooling and caching

### [syft-proxy](docs/syft-proxy.md) (DEPRECATED)
Previously provided HTTP → syft:// translation. This functionality is now integrated into the SyftBox Cache Server.

## Quick Start

### Installation

Install all packages:
```bash
# Install the packages from PyPI
pip install syft-core
pip install syft-event
pip install syft-rpc
pip install syft-http-bridge

## Higher-Level Abstraction

For easier development, check out [FastSyftBox](https://github.com/OpenMined/fastsyftbox) - a FastAPI-compatible server template that combines syft-core, syft-rpc, syft-events, and syft-http-bridge into one cohesive system.

## Documentation

- 📖 [Architecture Overview](docs/architecture-overview.md)
- 📚 [syft-core Documentation](docs/syft-core.md)
- 📚 [syft-event Documentation](docs/syft-event.md)
- 📚 [syft-rpc Documentation](docs/syft-rpc.md)
- 📚 [syft-http-bridge Documentation](docs/syft-http-bridge.md)
- 📚 [syft-proxy Documentation](docs/syft-proxy.md) (Deprecated)

## Development

### Running Tests

Test all packages:
```bash
# Unix/macOS
./test.sh

# Windows
./test.ps1

# Or test individual packages
cd packages/syft-core
uv run pytest
```

### Linting

Run linting with auto-fix:
```bash
# Unix/macOS
./lint.sh

# Windows
./lint.ps1
```

## Examples

The original experimental examples are still available:

### RPC Ping Pong
Start the pong RPC server:
```bash
just run-pong
```

Make a ping RPC request to the pong server:
```bash
just run-ping
```

### HTTP Proxy (Deprecated)
The HTTP proxy functionality has been moved to the SyftBox Cache Server.

## Future Enhancements

- **syft-files** - File management package (not yet started)
- **Distributed Tracing** - Better debugging across services
- **Schema Registry** - Centralized type definitions

## Contributing

We welcome contributions! Please see our contributing guidelines (coming soon).

## License

Apache License 2.0