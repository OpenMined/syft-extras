// -------------- TYPES --------------
/**
 * @typedef {Object} RPCSendRequest
 * @property {string} app_name - Name of the application
 * @property {string} url - Target URL
 * @property {any} body - The request body
 * @property {Object.<string, string>} headers - Request headers
 * @property {string} expiry - Expiry time
 * @property {boolean} cache - Cache flag
 */

/**
 * @typedef {Object} RPCReturnedRequest
 * @property {string} id - UUID of the request
 * @property {string} sender - Email of the sender
 * @property {string} url - Syft URL
 * @property {string} body - JSON stringified body
 * @property {Object.<string, string>} headers - Request headers
 * @property {string} method - HTTP method
 * @property {string} created - ISO timestamp of creation
 * @property {string} expires - ISO timestamp of expiration
 */

/**
 * @typedef {Object} RPCReturnedResponse
 * @property {string} id - UUID of the response (matches request)
 * @property {string} sender - Email of the sender
 * @property {string} url - Syft URL
 * @property {string} body - JSON stringified body
 * @property {Object.<string, string>} headers - Response headers
 * @property {string} created - ISO timestamp of creation
 * @property {string} expires - ISO timestamp of expiration
 * @property {number} status_code - HTTP status code
 */

// -------------- CONSTS --------------
const SYFT_PROXY_URL = "https://syftbox.localhost:9081";
const SyftRPCStatusCode = {
  PENDING: "RPC_PENDING",
  NOT_FOUND: "RPC_NOT_FOUND",
  COMPLETED: "RPC_COMPLETED",
  ERROR: "RPC_ERROR",
};

// -------------- UTILITY FUNCTIONS --------------
/**
 * Decodes a URL-safe base64 string to its original string representation.
 * Handles missing padding and URL-safe character replacements with standard base64 characters.
 * @param urlSafeStr - The URL-safe base64 encoded string to decode
 * @returns The decoded string
 * @throws {Error} If the input string cannot be properly decoded
 */
function parseUrlSafeBase64(urlSafeStr) {
  if (!urlSafeStr) {
    return undefined;
  }

  try {
    // Step 1: Add padding if missing
    const padding = urlSafeStr.length % 4;
    const paddedStr = padding
      ? urlSafeStr + "=".repeat(4 - padding)
      : urlSafeStr;

    // Step 2: Replace URL-safe characters with standard base64 characters
    const base64Str = paddedStr.replace(/-/g, "+").replace(/_/g, "/");

    // Step 3: Decode using built-in atob function
    const decoded = atob(base64Str);

    return decoded;
  } catch (error) {
    throw new Error(`Failed to decode base64 string: ${error.message}`);
  }
}

// -------------- CLASSES --------------
class SyftRPCError extends Error {
  constructor(message, result) {
    super(message);
    this.result = result;
  }
}

class SyftRPCResponse {
  constructor(response) {
    this.data = response;
    this._bodyContent = parseUrlSafeBase64(this.response?.body);
  }

  get id() {
    return this.data.id;
  }

  get status() {
    return this.data.status;
  }

  get status_code() {
    return this.response?.status_code;
  }

  get request() {
    return this.data.request;
  }

  get response() {
    return this.data.response;
  }

  get headers() {
    return this.response?.headers;
  }

  get body() {
    return this._bodyContent; // Return the stored _bodyContent
  }

  text() {
    return this.body;
  }

  json() {
    return this.text() && JSON.parse(this.text());
  }
}

class SyftRPCSDK {
  constructor(appName) {
    this.appName = appName;
  }

  /**
   * Constructs a Syft RPC URL from components
   * @param {string} datasite - The datasite identifier
   * @param {string} appName - The application name
   * @param {string} endpoint - The RPC endpoint name
   * @returns {string} The fully constructed Syft RPC URL
   * @example
   * makeURL("info@openmined.org", "pingpong", "ping")
   * // Returns: 'syft://info@openmined.org/api_data/pingpong/rpc/ping'
   */
  makeURL(datasite, appName, endpoint) {
    return `syft://${datasite}/api_data/${appName}/rpc/${endpoint}`;
  }

  #makeRpcBody(url, options) {
    const { body, headers = {}, cache = true, expiry = "15m" } = options;
    return {
      app_name: this.appName,
      url: url,
      body: body,
      headers: headers,
      cache: cache,
      expiry: expiry,
    };
  }

  // -------------- Local Storage --------------
  /**
   * We use the appName to partition the localStorage for that app. So we will have something like:
   * localStorage = {
   *  app1_futureID1: '1',
   *  app1_futureID2: '1',
   *  app2_futureID1: '1',
   *  app2_futureID2: '1',
   * }
   * This is a hash map with O(1) for look up, insert and delete.
   */

  get localStoragePrefix() {
    return `${this.appName}_`;
  }

  /**
   * Saves a future ID to localStorage
   * @param {string} futureID
   * @returns {void}
   */
  #saveFuture(futureID) {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem(`${this.localStoragePrefix}${futureID}`, 1);
  }

  /**
   * Gets a future ID from localStorage
   * @param {string} futureID
   * @returns {string|null}
   */
  #getFuture(futureID) {
    if (typeof localStorage === "undefined") return;
    return localStorage.getItem(`${this.localStoragePrefix}${futureID}`);
  }

  /**
   * Removes a future ID from localStorage
   * @param {string} futureID
   * @returns {void}
   */
  #deleteFuture(futureID) {
    if (typeof localStorage === "undefined") return;
    localStorage.removeItem(`${this.localStoragePrefix}${futureID}`);
  }

  /**
   * Returns array of all stored future IDs
   * @returns {string[]}
   */
  #listFutures() {
    if (typeof localStorage === "undefined") return;
    return Object.keys(localStorage)
      .filter((key) => key.startsWith(this.localStoragePrefix))
      .map((key) => key.split("_")[1]);
  }

  /**
   * Removes all stored future IDs
   * @returns {void}
   */
  #clearFutures() {
    if (typeof localStorage === "undefined") return;
    this.#listFutures().forEach((futureID) => this.#deleteFuture(futureID));
  }

  listFutures() {
    return this.#listFutures();
  }

  // -------------- RPC Functions --------------

  /**
   * Pings the Syft proxy server to check connectivity
   */
  async ping() {
    const proxyURL = `${SYFT_PROXY_URL}?sdk_ping=true`;
    const response = await fetch(proxyURL, {
      method: "GET",
    });

    if (!response.ok) {
      const err = await response.json();
      throw new Error(`HTTP error ${response.status}: ${err.detail}`);
    }

    return await response.text();
  }

  /**
   * Sends an RPC request to the Syft proxy
   */
  async send(url, options = {}) {
    const blocking = options.blocking || false;
    const proxyURL = `${SYFT_PROXY_URL}/rpc?blocking=${blocking}`;
    const rpbBody = JSON.stringify(this.#makeRpcBody(url, options), null, 2);
    const response = await fetch(proxyURL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: rpbBody,
    });

    const data = await response.json();

    if (!response.ok) {
      if (data.detail && !data.id) {
        // simple HTTP error response (not an RPC one)
        throw new Error(
          `HTTP error ${response.status}: ${JSON.stringify(data.detail)}`,
        );
      }
    }

    const syftRPCResponse = new SyftRPCResponse(data);

    if (syftRPCResponse.status === SyftRPCStatusCode.ERROR) {
      throw new SyftRPCError(
        `${syftRPCResponse.status} ${
          syftRPCResponse.status_code
        }: ${syftRPCResponse.text()}`,
        syftRPCResponse,
      );
    }

    if (syftRPCResponse.status === SyftRPCStatusCode.PENDING) {
      this.#saveFuture(syftRPCResponse.id);
    }

    return syftRPCResponse;
  }

  /**
   * Checks the status of an RPC request based on its ID / returned future ID
   */
  async status(futureID) {
    const proxyURL = `${SYFT_PROXY_URL}/rpc/status/${futureID}`;
    const response = await fetch(proxyURL, {
      method: "GET",
    });

    const data = await response.json();

    if (!response.ok) {
      if (data.detail && !data.id) {
        // simple HTTP error response (not an RPC one)
        throw new Error(
          `HTTP error ${response.status}: ${JSON.stringify(data.detail)}`,
        );
      }
    }

    const syftRPCResponse = new SyftRPCResponse(data);

    if (syftRPCResponse.status !== SyftRPCStatusCode.PENDING) {
      this.#deleteFuture(futureID);
    }

    if (syftRPCResponse.status === SyftRPCStatusCode.ERROR) {
      throw new SyftRPCError(
        `${syftRPCResponse.status} ${
          syftRPCResponse.status_code
        }: ${syftRPCResponse.text()}`,
        syftRPCResponse,
      );
    }

    return syftRPCResponse;
  }

  // Keeps checking the status of a future every interval until the it is resolved
  async pollFuture(futureID, interval = 5000) {
    const response = await this.status(futureID);
    if (response.status == SyftRPCStatusCode.PENDING) {
      await new Promise((resolve) => setTimeout(resolve, interval)); // Sleep for interval
      return await this.pollFuture(futureID, interval);
    }
    return response;
  }
}

class SyftProxySDK {
  constructor(appName) {
    this.appName = appName;
    this.rpc = new SyftRPCSDK(appName);
  }
}

if (typeof window !== "undefined") {
  window.SyftProxySDK = SyftProxySDK;
} else {
  module.exports = SyftProxySDK;
}
