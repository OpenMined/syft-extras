const SyftProxySDK = require("../../src/sdk.js");
const assert = require("assert");

// Store original fetch
const originalFetch = global.fetch;

async function mockRPCError() {
  // Replace fetch with mock
  global.fetch = async () => ({
    ok: true,
    json: async () => ({
      status: "RPC_ERROR",
      id: "test-id",
      request: {
        id: "test-id",
        sender: "test@test.com",
        url: "syft://test",
        body: "dGVzdA==", // base64 "test"
        headers: {},
        method: "POST",
        created: new Date().toISOString(),
        expires: new Date().toISOString(),
      },
      response: {
        id: "test-id",
        sender: "test@test.com",
        url: "syft://test",
        body: "dGVzdA==",
        headers: {},
        method: "POST",
        created: new Date().toISOString(),
        expires: new Date().toISOString(),
        status_code: 419,
      },
    }),
  });
  const syft = new SyftProxySDK("test-app");
  try {
    await syft.rpc.send("syft://test@test.com/test", {
      body: { test: "data" },
    });
    assert.fail("❌ Should have thrown RPC_ERROR");
  } catch (error) {
    assert(error.result.status === "RPC_ERROR", "Expected RPC_ERROR code");
    assert(error.result.id === "test-id", "Expected test-id");
    assert(
      error.result.request.url === "syft://test",
      "Wrong url for error.result.resquest.url",
    );
    assert(
      error.result.response.url === "syft://test",
      "Wrong url for error.result.response.url",
    );
    console.log(
      `✅ RPC_ERROR handled correctly.", id = ${error.result.id}, status = ${error.result.status}. message = ${error.message}"`,
    );
  } finally {
    // Restore original fetch
    global.fetch = originalFetch;
  }
}

async function main() {
  try {
    await mockRPCError();
    console.log("All tests passed!");
  } catch (error) {
    console.error("Test failed:", error);
    process.exit(1);
  }
}

main();
