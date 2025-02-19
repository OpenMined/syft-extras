## Running the examples

1. Run the proxy with `just start-proxy` (may need to install `mkcert` and make `uv` executable with `sudo`),
   go to `https://syftbox.localhost:9081/` on the browser and accept the certificate
2. Serve the static files with `just serve-static-files` which will serve the files in the `js-sdk` directory on `http://127.0.0.1:8000/`
3. Open the served html files, `http://127.0.0.1:8000/examples/pingpong.html`
4. For the `pingpong.html` example, we need to run the pong server, e.g.`just run-pong`
5. For the indexer example (`indexer.html`), we also need a syftbox stage client running in the background

## Running the tests

1. Need to run the proxy and the pong server
2. Run `just test-scenarios` to run the scenario tests
