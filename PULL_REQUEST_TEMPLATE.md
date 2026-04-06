## Summary

This PR addresses critical issues identified in a code quality review and implements important improvements to enhance reliability and robustness.

## Changes Made

### 🔴 Critical Fixes

1. **Source Service Verification** (NEW)
   - Added `_verify_source_service_exists()` that checks if the source DBus service is available at startup
   - Fails early with clear error message if service is unavailable
   - Prevents silent failures and cryptic errors later

2. **Power Inversion Consistency** (FIXED)
   - Now correctly inverts `/Dc/0/Power` from source if provided (previously only calculated)
   - Ensures power values stay in sync with source instead of diverging
   - Falls back to voltage × current calculation only when source doesn't provide power

3. **Exception Handling in Main** (IMPROVED)
   - Added robust error handling with fallback to stderr
   - Ensures logger availability before use
   - Prevents crashes if logging setup fails

4. **Signal Handler Robustness** (IMPROVED)
   - Added try-except in `_handle_exit()` to safely catch errors during shutdown
   - Prevents exceptions from interrupting graceful shutdown

### 🟡 Improvements

5. **Retry Logic with Backoff** (NEW)
   - Implements exponential backoff for failed polls instead of immediate cache removal
   - Configurable max attempts via `POLL_RETRY_MAX_ATTEMPTS` env var (default: 3)
   - Tracks retry count per path independently
   - Resets on successful signal reception
   - Better logging distinguishes between transient and persistent failures

6. **Value Validation** (IMPROVED)
   - Added None checks before float conversion in `_update_power()`
   - Prevents TypeErrors from invalid conversions

7. **Version Bump**
   - Updated process version from 1.1 → 1.2

## Environment Variables

New configurable option:
- `POLL_RETRY_MAX_ATTEMPTS` - Maximum retry attempts before removing from cache (default: 3)

## Testing Recommendations

1. Test with source service unavailable at startup (should fail fast)
2. Test with source service becoming temporarily unavailable (retry logic)
3. Verify power values match source when both voltage and current are available
4. Verify graceful shutdown with Ctrl+C

## Backwards Compatibility

✅ Fully backwards compatible
- All new environment variables have sensible defaults
- Existing installations will work without changes
- More robust error handling only improves stability