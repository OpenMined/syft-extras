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
    uv sync
    # Install packages for AutoMail
    uv pip install "numpy<2.0" requests loguru
    # Check if Ollama is installed and running
    echo "Checking Ollama installation..."
    if ! command -v ollama &> /dev/null; then \
        echo "{{ _yellow }}Ollama is not installed or not in PATH. AI responses won't be available.{{ _nc }}"; \
        echo "To enable AI responses, install Ollama from https://ollama.com/download"; \
    else \
        if ! curl -s -o /dev/null http://localhost:11434; then \
            echo "{{ _yellow }}Ollama server doesn't seem to be running. AI responses won't be available.{{ _nc }}"; \
            echo "To enable AI responses, run 'ollama serve' in a separate terminal."; \
        fi; \
    fi
    # Start AutoMail client
    uv run examples/automail/automail.py

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

run-automail-p2p-server:
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
    # Start the P2P server
    uv run examples/automail/automail_server.py

run-automail-p2p-cli:
    uv sync
    uv pip install requests loguru
    # Run the CLI client
    uv run examples/automail/automail_client.py

run-automail-p2p-web:
    uv sync
    uv pip install flask requests loguru
    # Run the web interface
    uv run examples/automail/automail_web.py

# For convenience, a command to run both server and web in separate terminals
run-automail-p2p *args="":
    # First, start the server in a new terminal
    if command -v gnome-terminal &> /dev/null; then \
        gnome-terminal -- just run-automail-p2p-server; \
    elif command -v osascript &> /dev/null; then \
        osascript -e 'tell app "Terminal" to do script "cd \"'$(pwd)'\" && just run-automail-p2p-server"'; \
    elif command -v xterm &> /dev/null; then \
        xterm -e "cd $(pwd) && just run-automail-p2p-server" &; \
    else \
        echo "{{ _yellow }}Could not detect terminal emulator. Please run the server separately with 'just run-automail-p2p-server'{{ _nc }}"; \
    fi
    
    # Wait a moment for the server to start
    sleep 2
    
    # Then run the web interface
    just run-automail-p2p-web {{ args }}

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
