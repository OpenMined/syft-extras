#!/bin/bash
set -e

# Lint script for syft-extras packages

echo "Running linting for syft-extras packages..."

# Function to run linting for a package
run_package_lint() {
    local package_dir=$1
    local package_name=$(basename "$package_dir")
    
    echo ""
    echo "========================================="
    echo "Linting $package_name"
    echo "========================================="
    
    cd "$package_dir"
    
    # Check if package has Python files to lint
    if [ ! -d "$(echo ${package_name} | tr '-' '_')" ] && [ ! -d "tests" ]; then
        echo "No Python files found, skipping lint for $package_name"
        cd - > /dev/null
        return
    fi
    
    # Remove existing virtual environment if it exists
    if [ -d ".venv" ]; then
        echo "Removing existing virtual environment..."
        rm -rf .venv
    fi
    
    # Create virtual environment with uv
    echo "Creating virtual environment..."
    uv venv .venv
    
    # Activate virtual environment based on OS
    echo "Activating virtual environment..."
    if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
        # Windows
        source .venv/Scripts/activate
    else
        # Unix-like (Linux, macOS)
        source .venv/bin/activate
    fi
    
    # Install the package and linting tools
    echo "Installing $package_name and linting tools..."
    uv pip install -e .
    uv pip install ruff mypy
    
    # Install type stubs if needed
    if grep -q "yaml" pyproject.toml 2>/dev/null || grep -q "PyYAML" pyproject.toml 2>/dev/null; then
        uv pip install types-PyYAML
    fi
    
    # Get the package module name (replace - with _)
    local module_name=$(echo "$package_name" | tr '-' '_')
    
    # Run ruff checks
    echo ""
    echo "Running ruff checks..."
    echo "---------------------"
    
    # Check if module directory exists
    if [ -d "$module_name" ]; then
        echo "Checking $module_name..."
        uv run ruff check "$module_name" || true
        uv run ruff format --check "$module_name" || true
    fi
    
    # Check if tests directory exists
    if [ -d "tests" ]; then
        echo "Checking tests..."
        uv run ruff check tests || true
        uv run ruff format --check tests || true
    fi
    
    # Run mypy
    echo ""
    echo "Running mypy..."
    echo "---------------"
    if [ -d "$module_name" ]; then
        uv run mypy "$module_name" --ignore-missing-imports || true
    fi
    
    # Deactivate virtual environment
    deactivate
    
    # Return to root directory
    cd - > /dev/null
}

# Function to run autofix with ruff
run_package_autofix() {
    local package_dir=$1
    local package_name=$(basename "$package_dir")
    
    echo ""
    echo "========================================="
    echo "Auto-fixing $package_name"
    echo "========================================="
    
    cd "$package_dir"
    
    # Get the package module name (replace - with _)
    local module_name=$(echo "$package_name" | tr '-' '_')
    
    # Check if package has Python files to fix
    if [ ! -d "$module_name" ] && [ ! -d "tests" ]; then
        echo "No Python files found, skipping autofix for $package_name"
        cd - > /dev/null
        return
    fi
    
    # Reuse existing virtual environment or create new one
    if [ ! -d ".venv" ]; then
        echo "Creating virtual environment..."
        uv venv .venv
    fi
    
    # Activate virtual environment
    if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
        source .venv/Scripts/activate
    else
        source .venv/bin/activate
    fi
    
    # Install ruff if not already installed
    if ! command -v ruff &> /dev/null; then
        echo "Installing ruff..."
        uv pip install ruff
    fi
    
    # Run ruff fixes
    echo "Running ruff fixes..."
    if [ -d "$module_name" ]; then
        echo "Fixing $module_name..."
        uv run ruff check "$module_name" --fix || true
        uv run ruff format "$module_name" || true
    fi
    
    if [ -d "tests" ]; then
        echo "Fixing tests..."
        uv run ruff check tests --fix || true
        uv run ruff format tests || true
    fi
    
    # Deactivate virtual environment
    deactivate
    
    # Return to root directory
    cd - > /dev/null
}

# Main script
ROOT_DIR=$(dirname "$0")
cd "$ROOT_DIR"

# Check for command line arguments
COMMAND=${1:-lint}
PACKAGE=${2:-}

case "$COMMAND" in
    lint)
        if [ "$PACKAGE" ]; then
            if [ -d "packages/$PACKAGE" ]; then
                run_package_lint "packages/$PACKAGE"
            else
                echo "Package '$PACKAGE' not found in packages directory"
                exit 1
            fi
        else
            # Run linting for all packages
            for package_dir in packages/*; do
                if [ -d "$package_dir" ]; then
                    run_package_lint "$package_dir"
                fi
            done
        fi
        ;;
    
    fix)
        if [ "$PACKAGE" ]; then
            if [ -d "packages/$PACKAGE" ]; then
                run_package_autofix "packages/$PACKAGE"
            else
                echo "Package '$PACKAGE' not found in packages directory"
                exit 1
            fi
        else
            # Run autofix for all packages
            for package_dir in packages/*; do
                if [ -d "$package_dir" ]; then
                    run_package_autofix "$package_dir"
                fi
            done
        fi
        ;;
    
    *)
        echo "Usage: $0 [lint|fix] [package-name]"
        echo ""
        echo "Commands:"
        echo "  lint [package]  - Run linting checks (default)"
        echo "  fix [package]   - Auto-fix linting issues"
        echo ""
        echo "Examples:"
        echo "  $0              - Lint all packages"
        echo "  $0 lint         - Lint all packages"
        echo "  $0 lint syft-core  - Lint only syft-core"
        echo "  $0 fix          - Auto-fix all packages"
        echo "  $0 fix syft-core   - Auto-fix only syft-core"
        exit 1
        ;;
esac

echo ""
echo "Linting completed!"