# PingPong Example

A simple example demonstrating basic request-response functionality between SyftBox instances.

## Overview

The PingPong example consists of two components:
- **Pong Server**: Listens for ping requests and responds with a pong message
- **Ping Client**: Sends ping requests to a specified datasite and displays the response

This is an excellent tool for testing connectivity, configuration, and basic functionality between SyftBox instances.

## Quick Start Guide

### Step 1: Set up a Test Environment

Create a configuration file for the staging server:

```bash
# Create test config
cat > ~/.syft_test_config.json << EOL
{
    "data_dir": "${HOME}/Desktop/SyftBoxTest",
    "server_url": "https://syftboxstage.openmined.org/",
    "client_url": "http://127.0.0.1:8082/",
    "email": "alice@openmined.org",
    "token": "0",
    "access_token": "YOUR_ALICE_ACCESS_TOKEN",
    "client_timeout": 5.0
}
EOL

# Create a second config file (optional - for testing between two clients)
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
# Terminal 1: Start first client with test account
rm -rf ~/Desktop/SyftBoxAlice
syftbox client --server https://syftboxstage.openmined.org \
              --email alice@openmined.org \
              --sync_folder ~/Desktop/SyftBoxAlice \
              --port 8082 \
              --config ~/.syft_test_config.json
```

```bash
# Terminal 2 (optional): Start second client with your account
# Replace YOUR_BOB_ACCESS_TOKEN in the config file first!
rm -rf ~/Desktop/SyftBoxBob
syftbox client --server https://syftboxstage.openmined.org \
              --email bob@openmined.org \
              --sync_folder ~/Desktop/SyftBoxBob \
              --port 8081 \
              --config ~/.syft_bob_config.json
```

### Step 3: Run the Pong Server

In a new terminal, start the pong server:

```bash
# Run pong server using the test account
just run-pong-with-config ~/.syft_test_config.json
```

### Step 4: Send Ping Requests

In another terminal, send ping requests:

```bash
# Option 1: Send ping to alice@openmined.org using Bob's account config
just run-ping-with-config alice@openmined.org ~/.syft_bob_config.json

# Option 2: Send ping to alice@openmined.org using default config
just run-ping alice@openmined.org
```

## Alternative Setup (Local Testing)

If you want to test everything locally with default configurations:

```bash
# Terminal 1: Start pong server
just run-pong

# Terminal 2: Send ping request
just run-ping
# When prompted, enter your own email or another available datasite
```

## Command Reference

```bash
# Run pong server with default config
just run-pong

# Run pong server with custom config
just run-pong-with-config /path/to/config.json

# Run ping client with interactive datasite selection
just run-ping

# Run ping client with specified datasite
just run-ping user@example.com

# Run ping client with custom config
just run-ping-with-config datasite@example.com /path/to/config.json
```

## Troubleshooting

### Connection Issues
- Ensure both SyftBox clients are running and connected to the server
- Check that the pong server is running on the target datasite
- Verify your access tokens are valid

### Invalid Datasite Errors
- Wait a moment for datasites to be discovered by the network
- Check for typos in the datasite email address
- Run `just run-ping` without arguments to see a list of available datasites

### Configuration Problems
- Ensure the config file contains valid JSON
- Check that the specified ports are not in use by other applications
- Verify the data directories exist and have appropriate permissions

## Understanding the Code

The core components are:

1. **PingRequest**: A simple data class containing a message and timestamp
2. **PongResponse**: A model class for the response with message and timestamp
3. **Pong Server**: Listens for requests and responds with the server's email
4. **Ping Client**: Sends requests and displays responses

This example demonstrates the basic request-response pattern that can be extended for more complex applications.
