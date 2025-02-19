const SyftProxySDK = require("../../src/sdk.js");
const assert = require("assert");
const { DATASITE } = require("./test-configs");

// Disable SSL verification
process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";

async function main() {
  const syft = new SyftProxySDK("test-pingpong-blocking");
  const url = syft.rpc.makeURL(DATASITE, "pingpong", "ping");
  console.log("Sending request to:", url);
  const result = await syft.rpc.send(url, {
    body: {
      msg: "Ping!",
      ts: new Date().toISOString(),
    },
    cache: true,
    expiry: "1m",
    blocking: true,
  });

  assert(result.id, "Response must have an id");
  assert(result.status, "Response must have a status");
  assert(result.status === "RPC_COMPLETED");
  assert(
    typeof result.text() === "string",
    "response.text() must return a string",
  );
  assert(
    typeof result.json() === "object",
    "response.json() must return an object",
  );
  console.log("request", result.id, result.status);
  console.log("as text", result.text());
  console.log("as object", result.json());

  // Test status call - should throw
  try {
    const result2 = await syft.rpc.status(result.id);
  } catch (error) {
    console.log(
      `✅ Got expected HTTP error from checking the ` +
        `status of "${result.id}" since it was resolved`,
    );
  }
}

main();
