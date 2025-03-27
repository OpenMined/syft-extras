import statistics
import time
from typing import Self

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncBaseTransport, Request, Response
from syft_http_bridge.async_bridge import SyftNatsBridge
from syft_http_bridge.nats_client import NatsRPCClient
from syft_http_bridge.serde import deserialize_response, serialize_request

app = FastAPI()


@app.get("/")
async def read_root():
    return "Hello World"


class NatsTransport(AsyncBaseTransport):
    def __init__(
        self,
        requester: str,
        responder: str,
        app_name: str,
        nats_url: str = "nats://localhost:4222",
    ):
        self.nats_client = NatsRPCClient(
            requester=requester,
            responder=responder,
            app_name=app_name,
            nats_url=nats_url,
        )

    async def handle_async_request(self, request: Request) -> Response:
        req_id = await self.nats_client.send_request(serialize_request(request))
        response = await self.nats_client.wait_for_response(req_id)
        response = deserialize_response(response)
        return response

    async def __aenter__(self) -> Self:
        await self.nats_client.connect()
        return self

    async def aclose(self) -> None:
        await self.nats_client.close()


async def benchmark(client, n=100):
    times = []

    # Warmup (optional)
    await client.get("/")

    # Main benchmark
    t0 = time.time()
    futures = []
    for _ in range(n):
        start = time.time()
        futures.append(client.get("/"))
        times.append((time.time() - start) * 1000)

    results = await asyncio.gather(*futures)

    print(results[10].text)
    total = time.time() - t0

    # Calculate statistics
    avg_time = statistics.mean(times)
    min_time = min(times)
    max_time = max(times)
    median_time = statistics.median(times)
    stddev = statistics.stdev(times) if len(times) > 1 else 0

    print(f"Results for {n} requests: {total} s")
    print(f"  Average: {avg_time:.2f} ms")
    print(f"  Median: {median_time:.2f} ms")
    print(f"  Min: {min_time:.2f} ms")
    print(f"  Max: {max_time:.2f} ms")
    print(f"  StdDev: {stddev:.2f} ms")

    return times


async def main():
    client = TestClient(app)
    bridge = SyftNatsBridge(
        app_name="my-http-app",
        responder="host@openmined.org",
        http_client=client,
    )
    await bridge.start()

    client = NatsRPCClient(
        requester="me@openmined.org",
        responder="host@openmined.org",
        app_name="my-http-app",
    )

    client = httpx.AsyncClient(
        base_url="http://syft",
        transport=NatsTransport(
            requester="me@openmined.org",
            responder="host@openmined.org",
            app_name="my-http-app",
        ),
    )

    await benchmark(client, n=1000)
    await bridge.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
