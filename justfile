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

[group('test')]
test package="":
    #!/bin/bash
    if [ -n "{{ package }}" ]; then \
        ./test.sh "{{ package }}"; \
    else \
        ./test.sh; \
    fi

# ---------------------------------------------------------------------------------------------------------------------
# Package Management Commands

# Show current versions of all packages
package-versions:
    @echo "{{ _cyan }}Current Package Versions:{{ _nc }}"
    @echo "{{ _green }}syft-core:{{ _nc }}"
    @grep '^version = ' packages/syft-core/pyproject.toml
    @echo "{{ _green }}syft-crypto:{{ _nc }}"
    @grep '^version = ' packages/syft-crypto/pyproject.toml
    @echo "{{ _green }}syft-rpc:{{ _nc }}"
    @grep '^version = ' packages/syft-rpc/pyproject.toml
    @echo "{{ _green }}syft-event:{{ _nc }}"
    @grep '^version = ' packages/syft-event/pyproject.toml

# Show dependency relationships
package-deps:
    @echo "{{ _cyan }}Package Dependencies:{{ _nc }}"
    @echo "{{ _green }}syft-core{{ _nc }} (base package)"
    @echo "{{ _green }}syft-crypto{{ _nc }} → depends on syft-core"
    @echo "{{ _green }}syft-rpc{{ _nc }} → depends on syft-core, syft-crypto"
    @echo "{{ _green }}syft-event{{ _nc }} → depends on syft-rpc"
    @echo "{{ _green }}syft-proxy{{ _nc }} → depends on syft-rpc"
    @echo "{{ _green }}syft-http-bridge{{ _nc }} → depends on syft-core"

# Universal bump command - handles all packages and their dependents
bump package increment="patch":
    #!/bin/bash
    if [ -z "{{ package }}" ]; then \
        echo -e "{{ _red }}Error: Package name required{{ _nc }}"; \
        echo "Usage: just bump <package> [increment]"; \
        echo "Packages: syft-core, syft-crypto, syft-rpc, syft-event"; \
        echo "Increments: patch, minor, major"; \
        echo "Example: just bump syft-core minor"; \
        exit 1; \
    fi
    
    # Check if package exists
    case "{{ package }}" in \
        "syft-core"|"syft-crypto"|"syft-rpc"|"syft-event") \
            ;; \
        *) \
            echo -e "{{ _red }}Error: Unknown package '{{ package }}'{{ _nc }}"; \
            echo "Available packages: syft-core, syft-crypto, syft-rpc, syft-event"; \
            exit 1; \
            ;; \
    esac
    
    echo -e "{{ _cyan }}Bumping {{ package }} {{ increment }} version...{{ _nc }}"
    
    # Bump the main package
    cd "packages/{{ package }}" && uv run cz bump --increment "{{ increment }}" --yes
    echo -e "{{ _green }}✅ {{ package }} bumped{{ _nc }}"
    
    # Update dependency constraints for dependent packages
    cd /home/shubham/repos/OpenMined/syft-extras
    case "{{ package }}" in \
        "syft-core") \
            echo -e "{{ _yellow }}Updating dependency constraints...{{ _nc }}"; \
            # Get the new version of syft-core \
            NEW_VERSION=$(grep '^version = ' packages/syft-core/pyproject.toml | sed 's/version = "\(.*\)"/\1/'); \
            echo -e "{{ _cyan }}Updating syft-crypto to depend on syft-core>=$NEW_VERSION{{ _nc }}"; \
            sed -i "s/syft-core>=[0-9]\+\.[0-9]\+\.[0-9]\+/syft-core>=$NEW_VERSION/" packages/syft-crypto/pyproject.toml; \
            echo -e "{{ _cyan }}Updating syft-rpc to depend on syft-core>=$NEW_VERSION{{ _nc }}"; \
            sed -i "s/syft-core>=[0-9]\+\.[0-9]\+\.[0-9]\+/syft-core>=$NEW_VERSION/" packages/syft-rpc/pyproject.toml; \
            echo -e "{{ _cyan }}Updating syft-http-bridge to depend on syft-core>=$NEW_VERSION{{ _nc }}"; \
            sed -i "s/syft-core>=[0-9]\+\.[0-9]\+\.[0-9]\+/syft-core>=$NEW_VERSION/" packages/syft-http-bridge/pyproject.toml; \
            echo ""; \
            echo -e "{{ _yellow }}⚠️  Note: Dependent packages may need version bumps:{{ _nc }}"; \
            echo -e "{{ _yellow }}   - syft-crypto (depends on syft-core){{ _nc }}"; \
            echo -e "{{ _yellow }}   - syft-rpc (depends on syft-core){{ _nc }}"; \
            echo -e "{{ _yellow }}   - syft-http-bridge (depends on syft-core){{ _nc }}"; \
            echo -e "{{ _yellow }}   Run 'just bump <package> <increment>' for each if needed{{ _nc }}"; \
            ;; \
        "syft-crypto") \
            echo -e "{{ _yellow }}Updating dependency constraints...{{ _nc }}"; \
            # Get the new version of syft-crypto \
            NEW_VERSION=$(grep '^version = ' packages/syft-crypto/pyproject.toml | sed 's/version = "\(.*\)"/\1/'); \
            echo -e "{{ _cyan }}Updating syft-rpc to depend on syft-crypto>=$NEW_VERSION{{ _nc }}"; \
            sed -i "s/syft-crypto>=[0-9]\+\.[0-9]\+\.[0-9]\+/syft-crypto>=$NEW_VERSION/" packages/syft-rpc/pyproject.toml; \
            echo ""; \
            echo -e "{{ _yellow }}⚠️  Note: Dependent packages may need version bumps:{{ _nc }}"; \
            echo -e "{{ _yellow }}   - syft-rpc (depends on syft-crypto){{ _nc }}"; \
            echo -e "{{ _yellow }}   Run 'just bump <package> <increment>' for each if needed{{ _nc }}"; \
            ;; \
        "syft-rpc") \
            echo -e "{{ _yellow }}Updating dependency constraints...{{ _nc }}"; \
            # Get the new version of syft-rpc \
            NEW_VERSION=$(grep '^version = ' packages/syft-rpc/pyproject.toml | sed 's/version = "\(.*\)"/\1/'); \
            echo -e "{{ _cyan }}Updating syft-event to depend on syft-rpc>=$NEW_VERSION{{ _nc }}"; \
            sed -i "s/syft-rpc>=[0-9]\+\.[0-9]\+\.[0-9]\+/syft-rpc>=$NEW_VERSION/" packages/syft-event/pyproject.toml; \
            echo -e "{{ _cyan }}Updating syft-proxy to depend on syft-rpc>=$NEW_VERSION{{ _nc }}"; \
            sed -i "s/syft-rpc>=[0-9]\+\.[0-9]\+\.[0-9]\+/syft-rpc>=$NEW_VERSION/" packages/syft-proxy/pyproject.toml; \
            echo ""; \
            echo -e "{{ _yellow }}⚠️  Note: Dependent packages may need version bumps:{{ _nc }}"; \
            echo -e "{{ _yellow }}   - syft-event (depends on syft-rpc){{ _nc }}"; \
            echo -e "{{ _yellow }}   - syft-proxy (depends on syft-rpc){{ _nc }}"; \
            echo -e "{{ _yellow }}   Run 'just bump <package> <increment>' for each if needed{{ _nc }}"; \
            ;; \
        "syft-event") \
            echo -e "{{ _yellow }}syft-event has no dependents{{ _nc }}"; \
            ;; \
    esac
    
    echo ""
    echo -e "{{ _green }}🎉 Package bumped and dependency constraints updated!{{ _nc }}"
    echo -e "{{ _cyan }}Run 'just package-versions' to see new versions{{ _nc }}"

# Dry run for any package bump
bump-dry package increment="patch":
    #!/bin/bash
    if [ -z "{{ package }}" ]; then \
        echo -e "{{ _red }}Error: Package name required{{ _nc }}"; \
        echo "Usage: just bump-dry <package> [increment]"; \
        echo "Packages: syft-core, syft-crypto, syft-rpc, syft-event"; \
        echo "Increments: patch, minor, major"; \
        echo "Example: just bump-dry syft-core minor"; \
        exit 1; \
    fi
    
    # Check if package exists
    case "{{ package }}" in \
        "syft-core"|"syft-crypto"|"syft-rpc"|"syft-event") \
            ;; \
        *) \
            echo -e "{{ _red }}Error: Unknown package '{{ package }}'{{ _nc }}"; \
            echo "Available packages: syft-core, syft-crypto, syft-rpc, syft-event"; \
            exit 1; \
            ;; \
    esac
    
    echo -e "{{ _cyan }}DRY RUN: Bumping {{ package }} {{ increment }} version...{{ _nc }}"
    echo ""
    
    # Show what packages will be affected
    case "{{ package }}" in \
        "syft-core") \
            echo -e "{{ _yellow }}This will bump: syft-core ({{ increment }}){{ _nc }}"; \
            echo -e "{{ _yellow }}And update their dependency requirements in: syft-crypto, syft-rpc, syft-http-bridge{{ _nc }}"; \
            ;; \
        "syft-crypto") \
            echo -e "{{ _yellow }}This will bump: syft-crypto ({{ increment }}){{ _nc }}"; \
            echo -e "{{ _yellow }}And update their dependency requirements in: syft-rpc{{ _nc }}"; \
            ;; \
        "syft-rpc") \
            echo -e "{{ _yellow }}This will bump: syft-rpc ({{ increment }}){{ _nc }}"; \
            echo -e "{{ _yellow }}And update their dependency requirements in: syft-event, syft-proxy{{ _nc }}"; \
            ;; \
        "syft-event") \
            echo -e "{{ _yellow }}This will bump: syft-event ({{ increment }}) only{{ _nc }}"; \
            ;; \
    esac
    echo ""
    
    # Show the main package bump
    echo -e "{{ _green }}Main package bump:{{ _nc }}"
    cd "packages/{{ package }}" && uv run cz bump --increment "{{ increment }}" --yes --dry-run
    echo ""
    
    echo ""
    echo -e "{{ _yellow }}⚠️  Note: Dependent packages will have their dependency requirements updated{{ _nc }}"
    echo -e "{{ _yellow }}   You may want to bump their versions separately if they have changes{{ _nc }}"

# Build all packages
package-build-all:
    @echo "{{ _cyan }}Building all packages...{{ _nc }}"
    uv build --all-packages
    @echo "{{ _green }}✅ All packages built successfully!{{ _nc }}"

# Build a specific package
package-build package:
    #!/bin/bash
    if [ -z "{{ package }}" ]; then \
        echo -e "{{ _red }}Error: Package name required{{ _nc }}"; \
        echo "Usage: just package-build-single <package>"; \
        echo "Available packages: syft-core, syft-crypto, syft-rpc, syft-event"; \
        exit 1; \
    fi
    
    # Check if package exists
    case "{{ package }}" in \
        "syft-core"|"syft-crypto"|"syft-rpc"|"syft-event") \
            ;; \
        *) \
            echo -e "{{ _red }}Error: Unknown package '{{ package }}'{{ _nc }}"; \
            echo "Available packages: syft-core, syft-crypto, syft-rpc, syft-event"; \
            exit 1; \
            ;; \
    esac
    
    echo -e "{{ _cyan }}Building {{ package }}...{{ _nc }}"
    cd "packages/{{ package }}" && uv build
    echo -e "{{ _green }}✅ {{ package }} built successfully!{{ _nc }}"

# TODO: Automate build/deploy step for package using uv in justfile
# This would include:
# - Building packages with uv build
# - Publishing to PyPI or private registry
# - Tagging and releasing
# - CI/CD integration

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
