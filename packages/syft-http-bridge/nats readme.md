## Why NATS
I did a quick survey of MQ options, with the following constraints:
- I don't want to build a proxy around the message queue for the prototype. This means:
  - Must support direct client connections
  - TLS
  - Auth + permissions
  - websockets (optional, for browser clients)
- Should be simple to setup (ie, no kafka)

RabbitMQ makes the above possible with some plugins, NATS seemed simpler and has more support out of the box.

Downsides of NATS:
- Only an async python client, so we'll need to wrap it for notebook use etc
- Docs are pretty hard to follow, auth and configuration are not simple

## Launching NATS:

```
docker run -p 4222:4222 -v ./nats_data:/data nats -js -sd /data

# OR

docker compose up
```

### Jetstream

Native nats does not do offline messaging. this is all handled by Jetstream, their persistence layer. There's a few small differences in how you interact with Jetstream, but it's mostly the same.

## Example use

`examples/nats_bridge/server.py` contains a full example using the NATS http bridge with FastAPI


## HTTP bridge architecture

Bit more convoluted than needed, it needs some cleanup and refactoring once it works. I've parked nats in syft-http-bridge for now, just to keep development easy. Moving it to something like `syft-mq` when its ready.


General layout:


`nats_client.py`
- `SyftNatsClient`, wraps `nats-py` with the request/response patterns for syft apps
  - `nats-py` is fully async, so all our client/server code is async as well
  - can use `anyio` if we want a synchronous server/client, see `fastapi` `TestClient` implementation they do the same trick
  - Will work out of the box for syft-rpc as well, or any other request/response pattern
- `create_nats_httpx_client`, implements clientside logic for HTTP request/response over NATS

`async_bridge.py`
- `AsyncHttpProxy`, async version of `bridge.py`. not NATS specific, this will eventually replace `bridge.py`
- `SyftNatsBridge`, implements serverside logic for HTTP request/response over NATS. HTTPX-based, so we can mock with starlette testclients instead of HTTP


`fraggle.syft_utils`
- Adds NATS communication to any existing FastAPI app. FastAPI listens to messages from NATS and sends them to the app as if they were normal HTTP.


`fraggle.clients.base_client`
- (WIP) `Client.for_nats` implements NATS communication for the client. WIP because the old client implementation is not async


### Full flow, NATS-based HTTP requests
The full flow that happens under the hood when sending a http request over NATS is:

**Clientside**
1. User creates a client with `nats_client.create_nats_httpx_client(...)` -> `httpx.AsyncClient`
2. `await client.post("/my/endpoint")`
3. the client transport is a NATS transport, which sends the request to the correct NATS subject and starts listening for a response

**Serverside**
1. `FastAPI` starts a `SyftNatsBridge` on startup (in `def lifespan`), which subscribes to the correct NATS subject to receive requests
2. When a request is received, the bridge forwards it to the `FastAPI` app as if it was a normal HTTP request
3. The `FastAPI` app processes the request and returns a response.
4. The bridge receives the response and pubs it to the correct NATS subject for the client to receive it.


## RPC Subjects

All RPC subjects have 2 roles:
- requester
- responder

Apps are identified by:
- app_name
- responder name

```
1. Client requests to server app, with a request_id and expires_at in the header
pub to requests.{requester}.{responder}.{app_name}

2. Server app listens for incoming requests
sub to requests.*.{responder}.{app_name}

3. Server responds to client
pub to responses.{requester}.{responder}.{app_name}.{request_id}

4. Client listens for responses
sub to responses.{requester}.{responder}.{app_name}.{request_id}
```

note on request_id being used in the topic name: When we get many requests this might create too many topics for NATS, but it makes the implementation easier when listening for responses. We can change this later if it becomes a problem.

## Permissions (TODO)

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

**to make fraggle communicate over NATS**
- [x] cleanup + fix benchmark
- [x] test ping-pong with online/offline client/server
- [x] setup + test with syft-http-bridge 
  - [x] server https://github.com/OpenMined/syft-extras/blob/main/packages/syft-http-bridge/src/syft_http_bridge/bridge.py
  - [x] client https://github.com/OpenMined/syft-extras/blob/main/packages/syft-http-bridge/src/syft_http_bridge/client.py
- [x] deploy + test on staging
  - [x] TLS
- [ ] integrate with fraggle (in progress)
  - [ ] https://github.com/OpenMined/fraggle/blob/nsai-demo/syftbox-rag/src/fraggle/syft_utils.py
- [ ] Link up to syftbox
  - [ ] infer nats url from syftbox config?
  
**lower priority**
- [ ] benchmark local and deployed Nats
  - [ ] simple FastAPI pingpong, measure request/response roundtrip time
- [ ] simple auth + access control.
- [ ] wrap async NATS client with a non-async interface
  - [ ] check out starlette testclient, they solve the same problem with anyio BlockingPortal
- [ ] Integrate with syft-rpc