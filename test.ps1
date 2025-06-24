# Test script for syft-extras packages (Windows PowerShell)

Write-Host "Running tests for syft-extras packages..."

# Function to run tests for a package
function Run-PackageTests {
    param(
        [string]$packageDir
    )
    
    $packageName = Split-Path $packageDir -Leaf
    
    Write-Host ""
    Write-Host "========================================="
    Write-Host "Testing $packageName"
    Write-Host "========================================="
    
    Push-Location $packageDir
    
    # Remove existing virtual environment if it exists
    if (Test-Path ".venv") {
        Write-Host "Removing existing virtual environment..."
        Remove-Item -Recurse -Force .venv
    }
    
    # Create virtual environment with uv
    Write-Host "Creating virtual environment..."
    uv venv .venv
    
    # Install the package in editable mode with test dependencies
    Write-Host "Installing $packageName and test dependencies..."
    uv pip install -e .
    uv pip install pytest pytest-cov pytest-xdist
    
    # Run tests if they exist
    if (Test-Path "tests") {
        Write-Host "Running tests..."
        $packageNameUnderscored = $packageName -replace '-', '_'
        uv run python -m pytest tests/ -v --cov="$packageNameUnderscored" --cov-report=term-missing
    } else {
        Write-Host "No tests directory found, skipping tests for $packageName"
    }
    
    Pop-Location
}

# Main script
$rootDir = $PSScriptRoot
Set-Location $rootDir

# Check if specific package is requested
if ($args.Count -gt 0) {
    $packageName = $args[0]
    $packagePath = Join-Path "packages" $packageName
    
    if (Test-Path $packagePath) {
        Run-PackageTests $packagePath
    } else {
        Write-Host "Package '$packageName' not found in packages directory"
        exit 1
    }
} else {
    # Run tests for all packages
    Get-ChildItem -Path "packages" -Directory | ForEach-Object {
        Run-PackageTests $_.FullName
    }
}

Write-Host ""
Write-Host "All tests completed!"