# Consolidated PingPong Client

An enhanced example demonstrating bidirectional request-response functionality between SyftBox instances in a single application.

## Overview

The Consolidated PingPong client is an all-in-one solution that combines the functionality of both the Ping Client and Pong Server from the original PingPong example:

- **Server Functionality**: Listens for ping requests and responds with a pong message
- **Client Functionality**: Sends ping requests to a specified datasite and displays the response
- **Dual Mode**: Can simultaneously act as both client and server

This integrated approach simplifies testing and demonstrates how a single SyftBox instance can both provide and consume services.

## Features

- **Flexible Operation Modes**:
  - **Dual Mode**: Run as both client and server simultaneously
  - **Server-Only Mode**: Run as just a pong server
  - **Client-Only Mode**: Run as just a ping client
  - **One-Time Ping**: Send a single ping and exit

- **Improved User Experience**:
  - Interactive menus for sending pings
  - Clear console output with status indicators
  - Automatic listing of available datasites

## Quick Start Guide

### Step 1: Set up a Test Environment

Use the same configuration as the original PingPong example:

```bash
# Create Alice's config
cat > ~/.syft_alice_config.json << EOL
{
    "data_dir": "${HOME}/Desktop/SyftBoxAlice",
    "server_url": "https://syftboxstage.openmined.org/",
    "client_url": "http://127.0.0.1:8082/",
    "email": "alice@openmined.org",
    "token": "0",
    "access_token": "YOUR_ALICE_ACCESS_TOKEN",
    "client_timeout": 5.0
}
EOL

# Create Bob's config
cat > ~/.syft_bob_config.json << EOL
{
    "data_dir": "${HOME}/Desktop/SyftBoxBob",
    "server_url": "https://syftboxstage.openmined.org/",
    "client_url": "http://127.0.0.1:8081/",
    "email": "bob@openmined.org",
    "token": "0",
    "access_token": "YOUR_BOB_ACCESS_TOKEN",
    "client_timeout": 5.0
}
EOL
```

### Step 2: Start SyftBox Clients

Start one or more SyftBox clients (each in a separate terminal):

```bash
# Terminal 1: Start first client with Alice's account
rm -rf ~/Desktop/SyftBoxAlice
syftbox client --server https://syftboxstage.openmined.org \
              --email alice@openmined.org \
              --sync_folder ~/Desktop/SyftBoxAlice \
              --port 8082 \
              --config ~/.syft_alice_config.json
```

```bash
# Terminal 2 (optional): Start second client with Bob's account
rm -rf ~/Desktop/SyftBoxBob
syftbox client --server https://syftboxstage.openmined.org \
              --email bob@openmined.org \
              --sync_folder ~/Desktop/SyftBoxBob \
              --port 8081 \
              --config ~/.syft_bob_config.json
```

### Step 3: Run the Consolidated PingPong Client

You can run the consolidated client in several different ways:

#### Dual Mode (Client and Server)

```bash
# Run in dual mode with Alice's account
just run-pingpong --config ~/.syft_alice_config.json

# Run in dual mode with Bob's account
just run-pingpong --config ~/.syft_bob_config.json
```

#### Server-Only Mode

```bash
# Run as just a pong server using Alice's account
just run-pingpong-server ~/.syft_alice_config.json
```

#### Client-Only Mode

```bash
# Run as just a ping client using Bob's account
just run-pingpong-client ~/.syft_bob_config.json
```

#### One-Time Ping

```bash
# Send a single ping from Bob to Alice and exit
just run-pingpong-to alice@openmined.org ~/.syft_bob_config.json
```

## Command Reference

```bash
# Run in dual mode (both client and server)
just run-pingpong [--config /path/to/config.json]

# Run in server-only mode
just run-pingpong-server [/path/to/config.json]

# Run in client-only mode
just run-pingpong-client [/path/to/config.json]

# Send a one-time ping
just run-pingpong-to [user@example.com] [/path/to/config.json]

# Run with direct command-line arguments
uv run examples/pingpong_consolidated/pingpong_client.py [--server-only] [--client-only] [--ping user@example.com] [--config /path/to/config.json]
```

## Testing Multiple Instances

The consolidated client makes it easy to test bi-directional communication between two SyftBox instances:

1. Start two SyftBox clients (Alice and Bob) as described in Step 2
2. In one terminal, run Alice's instance in dual mode:
   ```bash
   just run-pingpong --config ~/.syft_alice_config.json
   ```
3. In another terminal, run Bob's instance in dual mode:
   ```bash
   just run-pingpong --config ~/.syft_bob_config.json
   ```
4. From Alice's terminal, select option 1 and ping Bob's datasite
5. From Bob's terminal, select option 1 and ping Alice's datasite

Each client can now both send and receive pings simultaneously!

## Troubleshooting

### Connection Issues
- Ensure both SyftBox clients are running and connected to the server
- Check that the client has started in the correct mode (dual, server-only, or client-only)
- Verify your access tokens are valid

### Invalid Datasite Errors
- Wait a moment for datasites to be discovered by the network
- Check for typos in the datasite email address
- The client automatically lists available datasites when prompting for input

### Server Not Responding
- Ensure the target datasite has the integrated client running in either dual or server-only mode
- Check network connectivity between the clients

## Understanding the Code

The consolidated client combines the functionality of both the ping client and pong server:

1. **Models**: Defines the PingRequest and PongResponse data structures
2. **Server Component**: Implements a pong server that responds to ping requests
3. **Client Component**: Provides functions to send pings and interact with the user
4. **Main Program**: Integrates both components and provides different operation modes

The server component runs in a separate thread when operating in dual mode, allowing the client to both send and receive pings simultaneously.
