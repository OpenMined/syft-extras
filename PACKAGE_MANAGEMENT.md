# Package Management Guide

This guide explains how to manage package versions and dependencies in the syft-extras monorepo using the automated justfile commands.

## Overview

The monorepo uses **loose coupling** with automatic dependency requirement updates. When you bump a package version, dependent packages have their dependency requirements updated, but their versions are not automatically bumped.

## Package Dependency Chain

```
syft-core (base package)
├── syft-crypto → depends on syft-core
├── syft-rpc → depends on syft-core, syft-crypto
├── syft-event → depends on syft-rpc
├── syft-proxy → depends on syft-rpc
└── syft-http-bridge → depends on syft-core
```

## Available Commands

### Information Commands

```bash
# Show current versions of all packages
just package-versions

# Show dependency relationships
just package-deps
```

### Package Bumping Commands

#### Universal Bump Command (Recommended)

One command handles package bumping and updates dependency requirements in dependents:

```bash
# Bump any package and update dependency requirements in dependents
just bump <package> [increment=patch]
# Examples:
just bump syft-core minor
just bump syft-rpc patch
just bump syft-crypto major
just bump syft-event patch
```

#### Dry Run Command

```bash
# Test what would happen without making changes
just bump-dry <package> [increment=patch]
# Examples:
just bump-dry syft-core minor
just bump-dry syft-rpc patch
```

### Build Commands

```bash
# Build all packages
just package-build
```

## Version Increment Types

- **patch**: Bug fixes, small improvements (0.2.8 → 0.2.9)
- **minor**: New features, backward compatible (0.2.8 → 0.3.0)
- **major**: Breaking changes (0.2.8 → 1.0.0)

## Common Workflows

### 1. Adding a New Feature to syft-core

```bash
# 1. Make your changes and commit
git add .
git commit -m "feat: add new API to syft-core"

# 2. Bump syft-core (minor version) and update dependency requirements
just bump syft-core minor

# 3. Check the results
just package-versions
```

### 2. Fixing a Bug in syft-rpc

```bash
# 1. Make your changes and commit
git add .
git commit -m "fix: resolve RPC connection issue"

# 2. Bump syft-rpc (patch version) and update dependency requirements
just bump syft-rpc patch

# 3. Check the results
just package-versions
```

### 3. Making Breaking Changes to syft-crypto

```bash
# 1. Make your changes and commit
git add .
git commit -m "feat!: change encryption API"

# 2. Bump syft-crypto (major version) and update dependency requirements
just bump syft-crypto major

# 3. Check the results
just package-versions
```

### 4. Testing Before Release

```bash
# Test what would happen
just bump-dry syft-core minor

# If satisfied, run the actual bump
just bump syft-core minor
```

## What Happens During a Bump

When you run a bump command, the following happens:

1. **Version Update**: The package version is incremented in `pyproject.toml` and `__init__.py`
2. **Dependency Requirement Updates**: All dependent packages' dependency requirements are updated to use the new version
3. **Git Tag Creation**: A new tag is created (e.g., `syft-core-0.3.0`)
4. **Changelog Update**: The CHANGELOG.md is updated with recent commits
5. **User Notification**: You're informed that dependent packages may need version bumps if they have changes

## Important: Dependency Management Strategy

The system uses **loose coupling** which means:

- ✅ **What happens automatically**: Dependency requirements are updated (e.g., `syft-crypto` will require `syft-core>=0.4.0`)
- ❌ **What doesn't happen automatically**: Dependent package versions are NOT bumped
- ⚠️ **What you may need to do**: Manually bump dependent packages if they have changes

### Example:
```bash
# Bump syft-core from 0.3.0 to 0.4.0
just bump syft-core minor

# This updates dependency requirements in:
# - syft-crypto: syft-core>=0.4.0 (was syft-core>=0.3.0)
# - syft-rpc: syft-core>=0.4.0 (was syft-core>=0.3.0)  
# - syft-http-bridge: syft-core>=0.4.0 (was syft-core>=0.3.0)

# But syft-crypto, syft-rpc, syft-http-bridge versions remain unchanged
# You may want to bump them separately if they have changes:
just bump syft-crypto patch  # if syft-crypto has changes
just bump syft-rpc patch     # if syft-rpc has changes
```

## Example: Complete Release Flow

```bash
# 1. Check current state
just package-versions
just package-deps

# 2. Make changes and commit
git add .
git commit -m "feat: add new distributed computing features"

# 3. Test the bump (dry run)
just bump-dry syft-core minor

# 4. Execute the bump
just bump syft-core minor

# 5. Verify results
just package-versions

# 6. Build packages
just package-build

# 7. Push tags
git push --tags
```

## Tag Format

All tags follow the pattern: `<package-name>-<version>`

Examples:
- `syft-core-0.3.0`
- `syft-crypto-0.1.2`
- `syft-rpc-0.4.1`
- `syft-event-0.3.1`

## Best Practices

1. **Always test with dry-run first**: Use `just bump-dry` before actual bumps
2. **Use appropriate increment types**: 
   - `patch` for bug fixes
   - `minor` for new features
   - `major` for breaking changes
3. **Check dependencies**: Use `just package-deps` to understand impact
4. **Verify after bumping**: Use `just package-versions` to confirm changes
5. **Build after bumping**: Use `just package-build` to ensure everything works

## Troubleshooting

### If a bump fails:
1. Check that all files are committed
2. Ensure you're in the correct directory
3. Verify the package name is correct
4. Check for any syntax errors in pyproject.toml files

### If dependencies are out of sync:
1. Use `just package-versions` to check current state
2. Use `just package-deps` to understand relationships
3. Consider running a full dependency chain bump

## Integration with CI/CD

The git tags created by these commands can be used in CI/CD pipelines to:
- Trigger builds for specific packages
- Deploy only changed packages
- Generate release notes
- Update package registries

Example CI/CD usage:
```bash
# Get the latest tag for a package
git describe --tags --match "syft-core-*" --abbrev=0

# Get all tags for a specific commit
git tag --points-at HEAD
```
