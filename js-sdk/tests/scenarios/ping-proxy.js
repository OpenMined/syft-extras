const SyftProxySDK = require("../../src/sdk.js");
const assert = require("assert");

// Disable SSL verification
process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";

async function main() {
  const syft = new SyftProxySDK("test-pingpong-blocking");
  const response = await syft.rpc.ping();
  console.log("Proxy is reachable: \n", response);
  assert(typeof response === "string", "response must be a string");
}

main();
