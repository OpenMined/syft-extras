# Test script for syft-extras packages (Windows PowerShell)

Write-Host "Running tests for syft-extras packages..."

# Track overall test status
$script:allTestsPassed = $true

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
    
    try {
        # Remove existing virtual environment if it exists
        if (Test-Path ".venv") {
            Write-Host "Removing existing virtual environment..."
            Remove-Item -Recurse -Force .venv
        }
        
        # Create virtual environment with uv
        Write-Host "Creating virtual environment..."
        uv venv .venv
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create virtual environment"
        }
        
        # Activate virtual environment
        Write-Host "Activating virtual environment..."
        & .venv\Scripts\Activate.ps1
        
        # Install the package in editable mode with test dependencies
        Write-Host "Installing $packageName and test dependencies..."
        uv pip install -e .
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install package"
        }
        
        uv pip install pytest pytest-cov pytest-xdist
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install test dependencies"
        }
        
        # Run tests if they exist
        if (Test-Path "tests") {
            Write-Host "Running tests..."
            $packageNameUnderscored = $packageName -replace '-', '_'
            python -m pytest tests/ -v --cov="$packageNameUnderscored" --cov-report=term-missing
            
            if ($LASTEXITCODE -ne 0) {
                Write-Host "Tests FAILED for $packageName" -ForegroundColor Red
                $script:allTestsPassed = $false
            } else {
                Write-Host "Tests PASSED for $packageName" -ForegroundColor Green
            }
        } else {
            Write-Host "No tests directory found, skipping tests for $packageName"
        }
        
        # Deactivate virtual environment
        deactivate
    }
    catch {
        Write-Host "ERROR in $packageName : $_" -ForegroundColor Red
        $script:allTestsPassed = $false
    }
    finally {
        Pop-Location
    }
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
        Write-Host "Package '$packageName' not found in packages directory" -ForegroundColor Red
        exit 1
    }
} else {
    # Run tests for all packages
    Get-ChildItem -Path "packages" -Directory | ForEach-Object {
        Run-PackageTests $_.FullName
    }
}

Write-Host ""
if ($script:allTestsPassed) {
    Write-Host "All tests completed successfully!" -ForegroundColor Green
    exit 0
} else {
    Write-Host "Some tests FAILED!" -ForegroundColor Red
    exit 1
}