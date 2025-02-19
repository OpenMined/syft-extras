const SyftProxySDK = require("../../src/sdk.js");
const assert = require("assert");
const { DATASITE } = require("./test-configs");

// Disable SSL verification
process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";

async function main() {
  const syft = new SyftProxySDK("test-pingpong-nonblocking");
  const url = syft.rpc.makeURL(DATASITE, "pingpong", "ping");
  console.log("Sending request to:", url);
  const result = await syft.rpc.send(url, {
    body: {
      msg: "Ping!",
      ts: new Date().toISOString(),
    },
    cache: true,
    expiry: "1m",
    blocking: false,
  });
  assert(result.status === "RPC_PENDING");
  assert(
    result.text() === undefined,
    "response.text() is undefined for `RPC_PENDING` results",
  );
  assert(
    result.json() === undefined,
    "response.text() is undefined for `RPC_PENDING` results",
  );
  console.log("non-blocking response", result.id, result.status);

  console.log(
    "Wait for 3s so the non-blocking request can be processed by the pong server...",
  );
  await new Promise((resolve) => setTimeout(resolve, 2000));

  const result2 = await syft.rpc.status(result.id);
  assert(result2.status === "RPC_COMPLETED");
  assert(
    typeof result2.text() === "string",
    "response.text() must return a string",
  );
  assert(
    typeof result2.json() === "object",
    "response.json() must return an object",
  );
  assert(
    result2.json().msg.includes("Pong from"),
    'response.json().msg must include "Pong from"',
  );
  console.log("response", result2.id, result2.status);
  console.log("as text", result2.text());
  console.log("as object", result2.json());
}

main();
