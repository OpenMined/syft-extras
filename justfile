# Guidelines for new commands
# - Start with a verb
# - Keep it short (max. 3 words in a command)
# - Group commands by context. Include group name in the command name.
# - Mark things private that are util functions with [private] or _var
# - Don't over-engineer, keep it simple.
# - Don't break existing commands
# - Run just --fmt --unstable after adding new commands

set dotenv-load := true

# ---------------------------------------------------------------------------------------------------------------------
# Private vars

_red := '\033[1;31m'
_cyan := '\033[1;36m'
_green := '\033[1;32m'
_yellow := '\033[1;33m'
_nc := '\033[0m'

# ---------------------------------------------------------------------------------------------------------------------
# Aliases

alias ba := build-all
alias rj := run-jupyter

# ---------------------------------------------------------------------------------------------------------------------

@default:
    just --list

[group('build')]
build-all:
    uv build --all-packages

[group('utils')]
run-jupyter jupyter_args="":
    uv sync

    uv run --frozen --with "jupyterlab" \
        jupyter lab {{ jupyter_args }}

start-proxy *args:
    uv sync
    rm -rf certs
    sudo uv run syft_proxy bootstrap
    uv run syft_proxy start {{ args }}

run-pong:
    uv sync
    uv run examples/pingpong/pong_server.py

run-pong-with-config config="":
    uv sync
    if [ -n "{{ config }}" ]; then \
        uv run examples/pingpong/pong_server.py --config "{{ config }}"; \
    else \
        echo "{{ _yellow }}No config specified. Using default config.{{ _nc }}"; \
        uv run examples/pingpong/pong_server.py; \
    fi

run-ping *args:
    uv sync
    uv run examples/pingpong/ping_request.py {{ args }}

run-ping-with-config datasite="" config="":
    uv sync
    if [ -n "{{ config }}" ]; then \
        if [ -n "{{ datasite }}" ]; then \
            uv run examples/pingpong/ping_request.py --config "{{ config }}" "{{ datasite }}"; \
        else \
            uv run examples/pingpong/ping_request.py --config "{{ config }}"; \
        fi \
    else \
        echo "{{ _yellow }}No config specified. Using default config.{{ _nc }}"; \
        if [ -n "{{ datasite }}" ]; then \
            uv run examples/pingpong/ping_request.py "{{ datasite }}"; \
        else \
            uv run examples/pingpong/ping_request.py; \
        fi \
    fi

# Consolidated PingPong Client commands
run-pingpong *args:
    uv sync
    uv run examples/pingpong_consolidated/pingpong_client.py {{ args }}

run-pingpong-server config="":
    uv sync
    if [ -n "{{ config }}" ]; then \
        uv run examples/pingpong_consolidated/pingpong_client.py --server-only --config "{{ config }}"; \
    else \
        echo "{{ _yellow }}No config specified. Using default config.{{ _nc }}"; \
        uv run examples/pingpong_consolidated/pingpong_client.py --server-only; \
    fi

run-pingpong-client config="":
    uv sync
    if [ -n "{{ config }}" ]; then \
        uv run examples/pingpong_consolidated/pingpong_client.py --client-only --config "{{ config }}"; \
    else \
        echo "{{ _yellow }}No config specified. Using default config.{{ _nc }}"; \
        uv run examples/pingpong_consolidated/pingpong_client.py --client-only; \
    fi

run-pingpong-to datasite="" config="":
    uv sync
    if [ -n "{{ config }}" ]; then \
        if [ -n "{{ datasite }}" ]; then \
            uv run examples/pingpong_consolidated/pingpong_client.py --ping "{{ datasite }}" --config "{{ config }}"; \
        else \
            echo "{{ _yellow }}No datasite specified. Running in interactive mode.{{ _nc }}"; \
            uv run examples/pingpong_consolidated/pingpong_client.py --client-only --config "{{ config }}"; \
        fi \
    else \
        if [ -n "{{ datasite }}" ]; then \
            uv run examples/pingpong_consolidated/pingpong_client.py --ping "{{ datasite }}"; \
        else \
            echo "{{ _yellow }}No datasite specified. Running in interactive mode.{{ _nc }}"; \
            uv run examples/pingpong_consolidated/pingpong_client.py --client-only; \
        fi \
    fi

run-crud-server config="":
    uv sync
    if [ -n "{{ config }}" ]; then \
        uv run examples/crud/crud_server.py --config "{{ config }}"; \
    else \
        echo "{{ _yellow }}No config specified. Using default config.{{ _nc }}"; \
        uv run examples/crud/crud_server.py; \
    fi

run-crud-client config="":
    uv sync
    if [ -n "{{ config }}" ]; then \
        uv run examples/crud/crud_client.py --config "{{ config }}"; \
    else \
        echo "{{ _yellow }}No config specified. Using default config.{{ _nc }}"; \
        uv run examples/crud/crud_client.py; \
    fi

run-crud-sqlite-server config="" db="":
    uv sync
    if [ -n "{{ config }}" ] && [ -n "{{ db }}" ]; then \
        uv run examples/crud_sqlite/crud_sql_server.py --config "{{ config }}" --db "{{ db }}"; \
    elif [ -n "{{ config }}" ]; then \
        uv run examples/crud_sqlite/crud_sql_server.py --config "{{ config }}"; \
    elif [ -n "{{ db }}" ]; then \
        uv run examples/crud_sqlite/crud_sql_server.py --db "{{ db }}"; \
    else \
        echo "{{ _yellow }}No config or db specified. Using defaults.{{ _nc }}"; \
        uv run examples/crud_sqlite/crud_sql_server.py; \
    fi

run-crud-sqlite-client config="":
    uv sync
    if [ -n "{{ config }}" ]; then \
        uv run examples/crud_sqlite/crud_sql_client.py --config "{{ config }}"; \
    else \
        echo "{{ _yellow }}No config specified. Using default config.{{ _nc }}"; \
        uv run examples/crud_sqlite/crud_sql_client.py; \
    fi

[group('js-sdk')]
serve-static-files:
    cd js-sdk && python -m http.server 8000 --bind 127.0.0.1

[group('js-sdk')]
test-scenarios:
    # need to start the proxy and pong server first
    @for file in js-sdk/tests/scenarios/*.js; do \
        echo "{{ _cyan }}Running test: $file{{ _nc }}"; \
        if ! node "$file"; then \
            echo "{{ _red }}Test failed: $file{{ _nc }}"; \
            exit 1; \
        fi; \
    done
    @echo "{{ _green }}Congrats! All tests have passed!{{ _nc }}"
