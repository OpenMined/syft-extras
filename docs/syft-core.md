# Syft-Core Package Documentation

## Overview

The `syft-core` package provides the fundamental building blocks for the SyftBox ecosystem, including client configuration, workspace management, and a sophisticated permissions system that controls file access across distributed datasites.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         syft-core                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐ │
│  │   Client     │    │  Workspace   │    │   Permissions    │ │
│  │              │    │              │    │                  │ │
│  │ - Config     │    │ - Datasites  │    │ - syft.pub.yaml  │ │
│  │ - Email      │    │ - App Data   │    │ - Terminal flag  │ │
│  │ - URLs       │    │ - SyftBox    │    │ - Access control │ │
│  └──────────────┘    └──────────────┘    └──────────────────┘ │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐ │
│  │   Types      │    │     URL      │    │   Constants      │ │
│  │              │    │              │    │                  │ │
│  │ - PathLike   │    │ - SyftBoxURL │    │ - IGNORE_FOLDERS │ │
│  │ - Absolute   │    │ - Parsing    │    │ - Version info   │ │
│  │ - Relative   │    │ - Validation │    │ - Defaults       │ │
│  └──────────────┘    └──────────────┘    └──────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Client and Configuration

The `Client` class represents a SyftBox user with their configuration:

```python
from syft_core import Client

# Load client from default location
client = Client.load()

# Access client properties
print(client.email)           # User's email
print(client.workspace)       # Workspace object
print(client.server_url)      # Server URL
```

**Configuration File Structure** (`config.yaml`):
```yaml
email: alice@example.com
server_url: https://syftbox.example.com
client_url: http://127.0.0.1:8080
data_dir: /path/to/syftbox
```

### 2. Workspace Management

The workspace organizes the SyftBox file structure:

```
syftbox/
├── datasites/           # Contains all datasites
│   ├── alice@example.com/   # User's own datasite
│   └── bob@example.com/     # Other users' datasites
├── apps/                # Installed applications
└── logs/                # System logs
```

**Key Methods**:
- `client.workspace.datasites` - Path to datasites directory
- `client.workspace.syftbox_dir` - Root SyftBox directory
- `client.app_data(app_name, datasite)` - Get app data directory

### 3. Permissions System

The new permissions system uses `syft.pub.yaml` files with enhanced features:

#### File Format

```yaml
# Terminal flag - stops permission inheritance from parent directories
terminal: true

# Rules defining access control
rules:
  - pattern: "**/*.csv"        # Glob pattern for files
    access:
      read: ["*"]              # Everyone can read CSV files
      write: ["alice@example.com"]  # Only Alice can write
      admin: []                # No admin access

  - pattern: "private/**"      # All files in private directory
    access:
      read: ["alice@example.com", "bob@example.com"]
      write: ["alice@example.com"]
      admin: ["alice@example.com"]

  - pattern: "**"              # Default rule for all files
    access:
      read: []                 # No read access by default
      write: []
      admin: ["alice@example.com"]  # Owner has admin rights
```

#### Permission Hierarchy

```
┌─────────────────────────────────────────┐
│              Permission Hierarchy        │
├─────────────────────────────────────────┤
│                                         │
│   ADMIN ──────► includes all below      │
│     │                                   │
│     ▼                                   │
│   WRITE ──────► includes CREATE & READ  │
│     │                                   │
│     ▼                                   │
│   CREATE ─────► can create new files    │
│     │                                   │
│     ▼                                   │
│   READ ───────► can only read files     │
│                                         │
└─────────────────────────────────────────┘
```

#### Terminal Flag Behavior

The terminal flag controls permission inheritance:

```
datasites/
├── alice@example.com/
│   ├── syft.pub.yaml (terminal: false)
│   │   # Rules: everyone can read
│   ├── public/
│   │   └── data.csv  # ✓ Inherits parent permissions
│   └── private/
│       ├── syft.pub.yaml (terminal: true)
│       │   # Rules: only alice can access
│       └── secrets.txt  # ✗ Does NOT inherit parent permissions
```

#### Permission Computation Flow

```
┌─────────────────────────────────────────────────────┐
│           get_computed_permission()                  │
├─────────────────────────────────────────────────────┤
│                                                     │
│  1. Find all syft.pub.yaml files in path hierarchy │
│     └─► /datasites/alice/syft.pub.yaml             │
│     └─► /datasites/alice/app/syft.pub.yaml         │
│     └─► /datasites/alice/app/data/syft.pub.yaml    │
│                                                     │
│  2. Check for terminal flags                        │
│     └─► If terminal=true found, stop at that level │
│                                                     │
│  3. Collect applicable rules                        │
│     └─► Match file path against rule patterns      │
│     └─► Check user matches rule user               │
│                                                     │
│  4. Apply rules in order                            │
│     └─► Later rules override earlier ones           │
│     └─► Owner always has full access               │
│                                                     │
│  5. Return ComputedPermission object                │
│     └─► has_permission(PermissionType) → bool      │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 4. Auto-conversion from Old Format

The system automatically converts old `syftperm.yaml` files to the new format:

**Old Format**:
```yaml
- path: "**"
  user: "*"
  permissions: ["read"]
- path: "**"
  user: "alice@example.com"
  permissions: ["admin", "write", "read"]
```

**Converted to New Format**:
```yaml
rules:
  - pattern: "**"
    access:
      read: ["*"]
      admin: ["alice@example.com"]
```

To disable auto-conversion:
```python
from syft_core.permissions import set_auto_convert_permissions
set_auto_convert_permissions(False)
```

## Usage Examples

### Creating Default Permissions

```python
from syft_core import Client
from syft_core.permissions import SyftPermission

client = Client.load()
app_dir = client.workspace.datasites / "alice@example.com" / "my_app"

# Create permissions with public read access
perm = SyftPermission.mine_with_public_read(client, app_dir)
perm.save(app_dir)

# Create private permissions (terminal)
private_perm = SyftPermission.datasite_default(client, app_dir / "private")
private_perm.terminal = True
private_perm.save(app_dir / "private")
```

### Checking Permissions

```python
from syft_core.permissions import get_computed_permission
from syft_core.types import RelativePath, PermissionType

# Check if user can read a file
perms = get_computed_permission(
    client=client,
    path=RelativePath("alice@example.com/data/file.csv")
)

if perms.has_permission(PermissionType.READ):
    print("User can read the file")

if perms.has_permission(PermissionType.WRITE):
    print("User can write to the file")
```

### Working with Paths

```python
from syft_core.types import AbsolutePath, RelativePath, issubpath

# Create path objects
abs_path = AbsolutePath("/home/user/syftbox/datasites")
rel_path = RelativePath("alice@example.com/data")

# Check if one path is inside another
if issubpath(abs_path, abs_path / rel_path):
    print("Path is inside datasites")

# Convert between path types
full_path = abs_path / rel_path
relative = full_path.relative_to(abs_path)
```

## Advanced Features

### Custom Permission Rules

```python
perm = SyftPermission.create(client, app_dir)

# Add custom rules
perm.add_rule(
    path="logs/*.log",
    user="*",
    permission=["read"],
    allow=True
)

perm.add_rule(
    path="config/*",
    user="admin@example.com",
    permission=["admin"],
    allow=True
)

# Save with terminal flag to prevent inheritance
perm.terminal = True
perm.save(app_dir)
```

### URL Handling

```python
from syft_core.url import SyftBoxURL

# Parse SyftBox URLs
url = SyftBoxURL("syft://alice@example.com/app_data/my_app/data.csv")
print(url.user_email)    # alice@example.com
print(url.app_name)      # my_app
print(url.path)          # data.csv

# Create URLs
new_url = client.to_syft_url(Path("/datasites/alice@example.com/app_data/my_app"))
```

## Best Practices

1. **Always use terminal flags for sensitive directories** - Prevents accidental permission inheritance
2. **Order rules from most specific to least specific** - More specific patterns should come first
3. **Use glob patterns effectively**:
   - `**` matches any number of directories
   - `*` matches any characters in a single segment
   - `*.csv` matches all CSV files
   - `data/**/*.json` matches all JSON files under data/

4. **Test permissions before deployment**:
   ```python
   # Verify permissions work as expected
   test_path = RelativePath("alice@example.com/sensitive/data.txt")
   perms = get_computed_permission(client=other_client, path=test_path)
   assert not perms.has_permission(PermissionType.READ)
   ```

## Migration Guide

For applications using the old permissions system:

1. **Automatic migration** - Files are converted on first access
2. **Manual migration** - Use the conversion utilities:
   ```python
   from syft_core.permissions import SyftPermission
   
   # Load and convert old format
   perm = SyftPermission.from_file(
       Path("syft.pub.yaml"),
       datasites_path
   )
   ```

3. **Update permission checks** - The API remains the same:
   ```python
   # Old and new both use:
   perms = get_computed_permission(client=client, path=path)
   if perms.has_permission(PermissionType.READ):
       # Process file
   ```

## Error Handling

Common exceptions:

- `PermissionParsingError` - Invalid permission file format
- `FileNotFoundError` - Permission file not found
- `ValueError` - Invalid paths or parameters

Example error handling:
```python
try:
    perm = SyftPermission.from_file(perm_file, datasites)
except PermissionParsingError as e:
    print(f"Invalid permission file: {e}")
except FileNotFoundError:
    # Create default permissions
    perm = SyftPermission.datasite_default(client, directory)
```