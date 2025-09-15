#!/bin/bash
# Test script for syft-extras packages

echo "Running tests for syft-extras packages..."

# Track overall test status
ALL_TESTS_PASSED=true

# Function to run tests for a package
run_package_tests() {
    local package_dir=$1
    local package_name=$(basename "$package_dir")
    
    echo ""
    echo "========================================="
    echo "Testing $package_name"
    echo "========================================="
    
    cd "$package_dir" || { echo "Failed to enter $package_dir"; ALL_TESTS_PASSED=false; return 1; }
    
    # Remove existing virtual environment if it exists
    if [ -d ".venv" ]; then
        echo "Removing existing virtual environment..."
        rm -rf .venv
    fi
    
    # Create virtual environment with uv
    echo "Creating virtual environment..."
    if ! uv venv .venv; then
        echo -e "\033[0;31mFailed to create virtual environment for $package_name\033[0m"
        ALL_TESTS_PASSED=false
        cd - > /dev/null
        return 1
    fi
    
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
    if ! uv pip install -e .; then
        echo -e "\033[0;31mFailed to install $package_name\033[0m"
        ALL_TESTS_PASSED=false
        deactivate
        cd - > /dev/null
        return 1
    fi
    
    if ! uv pip install pytest pytest-cov pytest-xdist; then
        echo -e "\033[0;31mFailed to install test dependencies for $package_name\033[0m"
        ALL_TESTS_PASSED=false
        deactivate
        cd - > /dev/null
        return 1
    fi
    
    # Run tests if they exist
    if [ -d "tests" ]; then
        echo "Running tests..."
        if python -m pytest -s tests/ -v --cov="${package_name//-/_}" --cov-report=term-missing; then
            echo -e "\033[0;32mTests PASSED for $package_name\033[0m"
        else
            echo -e "\033[0;31mTests FAILED for $package_name\033[0m"
            ALL_TESTS_PASSED=false
        fi
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
        echo -e "\033[0;31mPackage '$1' not found in packages directory\033[0m"
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
if [ "$ALL_TESTS_PASSED" = true ]; then
    echo -e "\033[0;32mAll tests completed successfully!\033[0m"
    exit 0
else
    echo -e "\033[0;31mSome tests FAILED!\033[0m"
    exit 1
fi