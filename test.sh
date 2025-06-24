#!/bin/bash
set -e

# Test script for syft-extras packages

echo "Running tests for syft-extras packages..."

# Function to run tests for a package
run_package_tests() {
    local package_dir=$1
    local package_name=$(basename "$package_dir")
    
    echo ""
    echo "========================================="
    echo "Testing $package_name"
    echo "========================================="
    
    cd "$package_dir"
    
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
    
    # Install the package in editable mode with test dependencies
    echo "Installing $package_name and test dependencies..."
    uv pip install -e .
    uv pip install pytest pytest-cov pytest-xdist
    
    # Run tests if they exist
    if [ -d "tests" ]; then
        echo "Running tests..."
        python -m pytest tests/ -v --cov="${package_name//-/_}" --cov-report=term-missing
    else
        echo "No tests directory found, skipping tests for $package_name"
    fi
    
    # Deactivate virtual environment
    deactivate
    
    # Return to root directory
    cd - > /dev/null
}

# Main script
ROOT_DIR=$(dirname "$0")
cd "$ROOT_DIR"

# Check if specific package is requested
if [ "$1" ]; then
    if [ -d "packages/$1" ]; then
        run_package_tests "packages/$1"
    else
        echo "Package '$1' not found in packages directory"
        exit 1
    fi
else
    # Run tests for all packages
    for package_dir in packages/*; do
        if [ -d "$package_dir" ]; then
            run_package_tests "$package_dir"
        fi
    done
fi

echo ""
echo "All tests completed!"