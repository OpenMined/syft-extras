## syft-event-0.4.3 (2025-11-05)

### Feat

- implement DID fetching from server
- update DID conflict handling to delete old DID instead of archiving
- implement auto-regeneration of DID from existing keys and enhance key verification logic
- private keys loss
- enhance decryption logging and error handling in SyftEvents

### Fix

- matches requests in sender subdirectories

### Refactor

- improve variable names and logging messages in ensure_bootstrap function
- remove debug logging from encrypt and decrypt message functions
- enhance error messages for key management

## syft-event-0.4.2 (2025-10-14)

### Feat

- update show-deps command to dynamically extract and display package versions
- SyftURL compatible with pydantic v2. Add tests for SyftURL

## syft-event-0.4.1 (2025-09-18)

## syft-event-0.4.0 (2025-09-16)

### Refactor

- rename api_request_name to app_request_name and update related methods in client_shim.py
- update request handling to use SyftRequest and improve body parsing methods
