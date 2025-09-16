# GitHub Release Workflow

This document explains how to use the automated GitHub Actions workflow for releasing packages to PyPI.

## Overview

The release workflow automates the process of:
1. Bumping package versions using `just bump`
2. Updating dependency constraints automatically
3. Building packages using `just build`
4. Testing built packages
5. Uploading to PyPI

### Why Use Just Commands?

The workflow leverages the existing `just` commands from your `justfile`:
- **Consistency**: Uses the same commands developers use locally
- **Reliability**: Well-tested commands with proper error handling
- **Maintainability**: Single source of truth for build logic
- **Documentation**: Commands are self-documenting and familiar to the team

## Prerequisites

### Required GitHub Secrets

Before using this workflow, ensure the following secrets are configured in your GitHub repository:

1. **OM_PYPI_TOKEN**: Your PyPI username for uploading packages
   - Add your PyPI username to repository secrets as `OM_PYPI_TOKEN`


3. **GITHUB_TOKEN**: Automatically provided by GitHub Actions (no setup required)

### Repository Setup

- Ensure your repository has the correct branch structure
- Make sure all package dependencies are properly configured in `pyproject.toml` files
- Verify that commitizen is configured for each package

## How to Use

### Manual Trigger

1. Go to your GitHub repository
2. Navigate to **Actions** tab
3. Select **Release Package** workflow
4. Click **Run workflow**
5. Fill in the required inputs:

#### Input Parameters

- **Package**: Choose from dropdown
  - `syft-core`
  - `syft-crypto` 
  - `syft-rpc`
  - `syft-event`

- **Bump Type**: Choose version increment
  - `patch`: Bug fixes (0.1.0 → 0.1.1)
  - `minor`: New features (0.1.0 → 0.2.0)
  - `major`: Breaking changes (0.1.0 → 1.0.0)

- **Branch**: Target branch name (default: `main`)

### Workflow Steps

The workflow will automatically:

1. **Checkout**: Checkout the specified branch
2. **Setup**: Install Python, uv, just, and configure Git
3. **Bump Version**: Use `just bump` to bump the package version and update dependencies
4. **Commit & Push**: Commit changes and push to the branch
5. **Build**: Build the package using `just build`
6. **Test**: Test the built package by importing it
7. **Upload**: Upload to PyPI using twine
8. **Release**: Create a GitHub release with the new version

## Troubleshooting

### Common Issues

1. **Authentication Failed**: Ensure `OM_PYPI_TOKEN`.
2. **Build Failed**: Check package dependencies and configuration
3. **Import Test Failed**: Verify package structure and `__init__.py` files
4. **Git Push Failed**: Ensure the workflow has write permissions to the repository

### Debugging

- Check the workflow logs in the Actions tab
- Verify all secrets are properly configured
- Ensure the target branch exists and is accessible
- Check that commitizen is properly configured for the package

## Security Notes

- The `OM_PYPI_TOKEN` and `OM_PYPI_PWD` should have minimal required permissions
- Never commit credentials to the repository
- Regularly rotate passwords for security
- Use repository secrets for all sensitive information
- Consider using PyPI API tokens instead of username/password for better security

## Example Usage

```bash
# Example: Release syft-core with a minor version bump
# 1. Go to GitHub Actions
# 2. Select "Release Package" workflow  
# 3. Click "Run workflow"
# 4. Set inputs:
#    - Package: syft-core
#    - Bump Type: minor
#    - Branch: main
# 5. Click "Run workflow"
```

This will bump syft-core from 0.2.8 to 0.3.0, update all dependent packages, build, test, upload to PyPI, and create a GitHub release.
