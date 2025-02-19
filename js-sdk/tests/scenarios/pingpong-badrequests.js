const SyftProxySDK = require("../../src/sdk.js");
const { DATASITE } = require("./test-configs");

process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";

async function testSendErrors() {
  const syft = new SyftProxySDK("test-pingpong-bad-requests");
  const url = syft.rpc.makeURL(DATASITE, "pingpong", "ping");
  let testsFailed = false;

  // Test cases
  const tests = [
    {
      name: "Invalid URL",
      fn: () => syft.rpc.send("not-a-url", {}),
    },
    {
      name: "Missing body",
      fn: () => syft.rpc.send(url, { body: undefined }),
    },
    {
      name: "Invalid expiry format",
      fn: () =>
        syft.rpc.send(url, {
          body: { msg: "test" },
          expiry: "invalid",
        }),
    },
    {
      name: "Invalid blocking parameter",
      fn: () =>
        syft.rpc.send(url, {
          body: { msg: "test" },
          blocking: "not-boolean",
        }),
    },
  ];

  // Run tests
  for (const test of tests) {
    try {
      await test.fn();
      console.error(`❌ test ${test.name} is expected to fail but succeeded`);
      testsFailed = true;
    } catch (error) {
      console.log(
        `✅ test ${test.name} failed as expected. Error message: ${error.message}`,
      );
    }
  }

  if (testsFailed) {
    process.exit(1); // Exit with error code
  }
}

async function main() {
  try {
    await testSendErrors();
    console.log("All error tests passed!");
  } catch (error) {
    console.error("Test failed:", error);
    process.exit(1);
  }
}

main();
