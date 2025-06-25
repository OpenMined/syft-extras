# SyftBox Extras Architecture Overview

## System Architecture

The SyftBox Extras packages provide building blocks for SyftBox applications to communicate with each other and external services. These packages don't all combine directly - instead, they serve different layers of the communication stack.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         Application Layer                                │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │                        SyftBox Apps                             │     │
│  │                                                                 │     │
│  │  Receive data via:                                             │     │
│  │  • syft:// URLs (via syft-event)                              │     │
│  │  • http:// URLs (via syft-http-bridge)                        │     │
│  │                                                                 │     │
│  │  Use syft-core for:                                           │     │
│  │  • Creating/checking permission files                          │     │
│  │  • Getting client handle                                       │     │
│  │  • Finding paths to local client                               │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│                         Communication Layer                              │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────┐    ┌──────────────────────────────────┐      │
│  │    syft-event        │    │      syft-http-bridge            │      │
│  │                      │    │                                   │      │
│  │  • Handles syft://   │    │  • Bridges HTTP ↔ filesystem     │      │
│  │  • File watching     │    │  • Serializes HTTP req/resp      │      │
│  │  • Route handlers    │    │  • MessagePack serialization     │      │
│  └──────────────────────┘    └──────────────────────────────────┘      │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────┐      │
│  │                         syft-rpc                              │      │
│  │                                                               │      │
│  │  • Request/Response system with HTTP headers/body support    │      │
│  │  • Serialization protocol                                     │      │
│  │  • No active TCP connection required                          │      │
│  └──────────────────────────────────────────────────────────────┘      │
│                                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│                         Infrastructure Layer                             │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────┐      │
│  │                  SyftBox Cache Server                         │      │
│  │                                                               │      │
│  │  • Central data routing                                       │      │
│  │  • HTTP proxy support (replaces syft-proxy)                  │      │
│  │  • Manages data flow between clients                         │      │
│  └──────────────────────────────────────────────────────────────┘      │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────┐      │
│  │                syft-proxy (DEPRECATED)                        │      │
│  │                                                               │      │
│  │  • Previously handled HTTP → syft:// translation              │      │
│  │  • Now replaced by SyftBox Cache Server HTTP support         │      │
│  └──────────────────────────────────────────────────────────────┘      │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

## Higher-Level Abstraction

For easier development, there's [FastSyftBox](https://github.com/OpenMined/fastsyftbox) - a FastAPI-compatible server template that combines syft-core, syft-rpc, syft-events, and syft-http-bridge into one cohesive system:

