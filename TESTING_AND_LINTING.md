# Testing and Linting syft-extras

This repository contains multiple packages. Each package has its own test suite and follows consistent linting standards.

## Testing

### Quick Start - Test All Packages

**Unix/macOS:**
```bash
./test.sh
```

**Windows:**
```powershell
.\test.ps1
```

### Test Specific Package

**Unix/macOS:**
```bash
./test.sh syft-core
./test.sh syft-proxy
```

**Windows:**
```powershell
.\test.ps1 syft-core
.\test.ps1 syft-proxy
```

## Linting

### Lint All Packages

**Unix/macOS:**
```bash
./lint.sh
```

**Windows:**
```powershell
.\lint.ps1
```

### Lint Specific Package

**Unix/macOS:**
```bash
./lint.sh lint syft-core
```

**Windows:**
```powershell
.\lint.ps1 lint syft-core
```

### Auto-fix Linting Issues

**Unix/macOS:**
```bash
./lint.sh fix              # Fix all packages
./lint.sh fix syft-core    # Fix specific package
```

**Windows:**
```powershell
.\lint.ps1 fix             # Fix all packages
.\lint.ps1 fix syft-core   # Fix specific package
```

## Script Features

### Test Scripts (`test.sh` / `test.ps1`)
- Create isolated virtual environments for each package
- Install packages in editable mode
- Run pytest with coverage reporting
- Clean up virtual environments after testing
- Work across all major operating systems

### Lint Scripts (`lint.sh` / `lint.ps1`)
- Run `ruff` for code style checking and formatting
- Run `mypy` for type checking
- Support auto-fixing of common issues
- Install type stubs as needed (e.g., types-PyYAML)
- Skip packages without Python code

## Continuous Integration

GitHub Actions automatically runs tests and linting on:
- **Python versions**: 3.8, 3.9, 3.10, 3.11, 3.12, 3.13
- **Operating systems**: Ubuntu, Windows, macOS
- **Events**: Push to main/master, pull requests

## Package-Specific Documentation

For detailed information about tests in each package, see:
- [syft-core testing](packages/syft-core/TESTING.md)

## Adding New Packages

When adding a new package:
1. Create a `tests/` directory in your package
2. Add pytest as a test dependency in `pyproject.toml`
3. Update `.github/workflows/test.yml` to include your package
4. The main test and lint scripts will automatically detect and process it

## Requirements

- Python 3.8-3.13
- [uv](https://github.com/astral-sh/uv) package manager
- pytest (installed automatically by test script)
- ruff (installed automatically by lint script)
- mypy (installed automatically by lint script)

## Linting Standards

All packages use:
- **ruff** for code formatting and style checks
- **mypy** for static type checking
- **Black-compatible** formatting (via ruff)
- **isort-compatible** import sorting (via ruff)

To maintain consistency, always run the lint script before committing changes.