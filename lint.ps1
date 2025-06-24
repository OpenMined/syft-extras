# Lint script for syft-extras packages (Windows PowerShell)

param(
    [string]$mode = "lint",
    [string]$package = ""
)

Write-Host "Running linting for syft-extras packages..."

# Function to run linting for a package
function Run-PackageLint {
    param(
        [string]$packageDir,
        [string]$mode
    )
    
    $packageName = Split-Path $packageDir -Leaf
    
    Write-Host ""
    Write-Host "========================================="
    Write-Host "Linting $packageName (mode: $mode)"
    Write-Host "========================================="
    
    Push-Location $packageDir
    
    # Check if package has Python code
    $pythonFiles = Get-ChildItem -Path . -Filter "*.py" -Recurse -File | Where-Object { $_.FullName -notmatch "\.venv" }
    
    if ($pythonFiles.Count -eq 0) {
        Write-Host "No Python files found in $packageName, skipping..."
        Pop-Location
        return
    }
    
    # Create virtual environment if it doesn't exist
    if (-not (Test-Path ".venv")) {
        Write-Host "Creating virtual environment..."
        uv venv .venv
    }
    
    # Install the package and linting tools
    Write-Host "Installing $packageName and linting tools..."
    uv pip install -e . 2>$null
    uv pip install ruff mypy types-PyYAML types-requests 2>$null
    
    # Run ruff
    Write-Host "Running ruff..."
    if ($mode -eq "fix") {
        uv run ruff check . --fix
        uv run ruff format .
    } else {
        uv run ruff check .
        uv run ruff format . --check
    }
    
    # Run mypy
    Write-Host "Running mypy..."
    uv run mypy . --install-types --non-interactive
    
    Pop-Location
}

# Main script
$rootDir = $PSScriptRoot
Set-Location $rootDir

# Determine packages to lint
$packagesToLint = @()

if ($package) {
    $packagePath = Join-Path "packages" $package
    if (Test-Path $packagePath) {
        $packagesToLint += $packagePath
    } else {
        Write-Host "Package '$package' not found in packages directory"
        exit 1
    }
} else {
    # Lint all packages
    $packagesToLint = Get-ChildItem -Path "packages" -Directory | Select-Object -ExpandProperty FullName
}

# Run linting for selected packages
foreach ($pkg in $packagesToLint) {
    Run-PackageLint $pkg $mode
}

Write-Host ""
Write-Host "Linting completed!"