import asyncio
import statistics
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from syft_http_bridge.async_bridge import SyftNatsBridge
from syft_http_bridge.nats_client import create_nats_httpx_client

app = FastAPI()


@app.get("/")
async def read_root():
    return "Hello World"


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
    requester = "alice@openmined.org"
    responder = "bob@openmined.org"
    app_name = "my-http-app"

    httpx_client = TestClient(app)
    bridge = SyftNatsBridge(
        app_name=app_name,
        responder=responder,
        http_client=httpx_client,
    )
    await bridge.start()

    # Client alice makes a client to talk to bob's app
    # `create_nats_httpx_client` returns a client with a NATS-based transport (instead of HTTP)
    syft_mq_client = create_nats_httpx_client(
        requester=requester,
        responder=responder,
        app_name=app_name,
    )

    res = await syft_mq_client.get("/")
    print(res.text)
    await bridge.close()


if __name__ == "__main__":
    asyncio.run(main())
