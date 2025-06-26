## Installation

To install the `syft-high-low` package, you can use the following command:

```bash
pip install syft-high-low
```

## Usage

### Initializing a high datasite sync configuration

```
syft-high-low init-high-datasite --email high@datasite.com
syft-high-low init-sync-config \
    --remote-datasite-path ~/.syftbox/low@user.com/SyftBox \
    --ssh-host low.datasite.com \
    --ssh-port 22 \
    --ssh-key-path ~/.ssh/id_rsa \
    --force-overwrite \
```

## Adding directories to sync
```
# Adding a pull sync entry (e.g., pull pending Jobs to execute on the high side)
syftbox add-sync-entry \
    --local-dir /path/to/local/dir \
    --remote-dir /path/to/remote/dir \
    --direction pull

# Adding a push sync entry (e.g., push results back to the low side)
syftbox add-sync-entry \
    --local-dir /path/to/local/dir \
    --remote-dir /path/to/remote/dir \
    --direction push
```