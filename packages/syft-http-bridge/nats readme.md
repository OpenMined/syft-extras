- I've parked nats in syft-http-bridge for now, just to keep development easy. Moving it to something like `syft-mq` when its ready.

## Launching NATS:

```
docker run -p 4222:4222 -v ./nats_data:/data nats -js -sd /data

# OR

docker compose up
```

### Jetstream

Native nats does not do offline messaging. this is all handled by Jetstream, their persistence layer. There's a few small differences in how you interact with Jetstream, but it's mostly the same.

## RPC Subjects

All RPC patterns have 2 roles:
- requester
- responder

Apps are identified by:
- app_name
- responder name

```
1. Client requests to server app
pub to requests.{requester}.{responder}.{app_name}

1. Server app listens for incoming requests
sub to requests.*.{responder}.{app_name}

1. Server responds to client
pub to responses.{requester}.{responder}.{app_name}.{request_id}

1. Client listens for responses
sub to responses.{requester}.{responder}.{app_name}.{request_id}
```

note on request_id being used in the topic name: When we get many requests this might not be efficient, but it makes the implementation easier when listening for responses. We can change this later if needed.

## Permissions

NATS supports JWT tokens for authentication. We can use this to restrict access to certain subjects. For the above request/response pattern.

The `*` wildcard matches a single subject token, the `>` wildcard matches multiple tokens.

```
# Client-side permissions to send requests and receive responses
pub requests.{username}.>
sub responses.{username}.>

# Server-side permissions to receive requests and send responses
sub requests.*.{username}.>
pub responses.*.{username}.>
```


## TODO

- [x] cleanup + fix benchmark
- [x] test ping-pong with online/offline client/server
- [x] setup + test with syft-http-bridge 
  - [x] server https://github.com/OpenMined/syft-extras/blob/main/packages/syft-http-bridge/src/syft_http_bridge/bridge.py
  - [ ] client https://github.com/OpenMined/syft-extras/blob/main/packages/syft-http-bridge/src/syft_http_bridge/client.py
- [x] deploy + test on staging
  - [ ] TLS?
- [ ] integrate with fraggle
  - [ ] https://github.com/OpenMined/fraggle/blob/nsai-demo/syftbox-rag/src/fraggle/syft_utils.py
- [ ] Link up to syftbox
  - [ ] infer nats url from syftbox config?
- [ ] 

- [ ] benchmark local and deployed Nats
  - [ ] simple FastAPI pingpong, measure request/response roundtrip time
- [ ] simple auth + access control
- [ ] wrap async NATS client with a non-async interface
  - [ ] check out starlette testclient, they solve the same problem with anyio BlockingPortal
- [ ] syft-rpc?