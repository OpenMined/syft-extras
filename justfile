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

run-ping:
    uv sync
    uv run examples/pingpong/ping_request.py

run-crud-server:
    uv sync
    uv run examples/crud/crud_server.py

run-crud-client:
    uv sync
    uv run examples/crud/crud_client.py

run-automail-server:
    uv sync
    # Install packages for the Ollama integration
    uv pip install "numpy<2.0"
    uv pip install requests loguru
    # Check if Ollama is installed and running
    echo "Checking Ollama installation..."
    if ! command -v ollama &> /dev/null; then \
        echo "Ollama is not installed or not in PATH. Please install from https://ollama.com/download"; \
        echo "After installing, run: 'ollama serve' in a separate terminal"; \
        echo "Then run: 'ollama pull llama3' to download the model"; \
        exit 1; \
    fi
    # Try to ensure Ollama is running
    if ! curl -s -o /dev/null http://localhost:11434; then \
        echo "Ollama server doesn't seem to be running."; \
        echo "Please run 'ollama serve' in a separate terminal before starting the server."; \
        exit 1; \
    fi
    # Start the AI server
    uv run examples/automail/automail_ai_server.py

run-automail-monitor:
    # Create a simple venv for the monitor 
    rm -rf .monitor-env
    python3 -m venv .monitor-env
    .monitor-env/bin/pip install flask loguru requests
    .monitor-env/bin/python examples/automail/automail_monitor.py

run-automail:
    # uv sync
    uv pip install flask
    uv run examples/automail/automail_client.py

run-automail-unified:
    uv sync
    # Install packages for the unified app
    uv pip install "numpy<2.0" flask flask-socketio eventlet requests loguru
    # Check if Ollama is installed and running
    echo "Checking Ollama installation..."
    if ! command -v ollama &> /dev/null; then \
        echo "Ollama is not installed or not in PATH. Please install from https://ollama.com/download"; \
        echo "After installing, run: 'ollama serve' in a separate terminal"; \
        echo "Then run: 'ollama pull llama3' to download the model"; \
        exit 1; \
    fi
    # Try to ensure Ollama is running
    if ! curl -s -o /dev/null http://localhost:11434; then \
        echo "Ollama server doesn't seem to be running."; \
        echo "Please run 'ollama serve' in a separate terminal before starting the server."; \
        exit 1; \
    fi
    # Start the unified app
    uv run examples/automail/automail_unified.py

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
