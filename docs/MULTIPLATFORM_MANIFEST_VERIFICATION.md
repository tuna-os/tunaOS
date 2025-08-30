# Multiplatform Manifest Verification

This document describes the enhanced CI/CD workflow that ensures multiplatform container manifests contain all intended platforms before proceeding to the next build stage.

## Overview

The build workflow now includes verification steps that:
1. **Verify manifest completeness**: Check that all expected platforms are present in the multiplatform manifest
2. **Block progression on failure**: Prevent the next build variant from starting if manifest verification fails
3. **Provide clear status reporting**: Show exactly which platforms are expected vs. actual in the manifest

## Workflow Structure

```
generate_matrix
    ↓
build-base → verify-base-manifests
    ↓
build-dx → verify-dx-manifests  
    ↓
build-gdx → verify-gdx-manifests
    ↓
verify-build-completion
```

## Verification Jobs

### Individual Variant Verification
Each build variant (`base`, `dx`, `gdx`) now has a corresponding verification job:
- `verify-base-manifests`
- `verify-dx-manifests` 
- `verify-gdx-manifests`

These jobs:
- Run after the corresponding build job completes successfully
- Login to the container registry and inspect the pushed manifest
- Compare expected platforms vs. actual platforms in the manifest
- Fail with detailed error reporting if platforms don't match

### Final Build Completion Verification
The `verify-build-completion` job:
- Runs after all build and verification jobs (using `always()` condition)
- Checks the results of all jobs based on the requested build variants
- Provides a summary of success/failure for each variant
- Fails the entire workflow if any required variant failed

## Platform Verification Logic

The verification uses this logic:
1. Extract expected platforms from the build matrix (e.g., `linux/amd64,linux/arm64,linux/amd64/v2`)
2. Inspect the pushed manifest using `podman manifest inspect`
3. Extract actual platforms from the manifest JSON
4. Sort both lists and compare for exact match
5. Report success ✅ or failure ❌ with detailed platform information

## Error Examples

### Missing Platform
```
❌ Manifest verification failed
Expected: linux/amd64,linux/amd64/v2,linux/arm64
Actual:   linux/amd64,linux/arm64
```

### Successful Verification
```
✅ Manifest verification successful - all expected platforms present
```

## Benefits

1. **Reliability**: Ensures multiplatform images are properly created before dependent builds start
2. **Early Detection**: Catches platform-specific build failures immediately
3. **Clear Reporting**: Easy to understand what went wrong and why
4. **Proper Sequencing**: Guarantees base → dx → gdx dependency chain works correctly
5. **Latest Tag Safety**: "latest" tags are only applied after successful manifest verification

## Integration with Existing Workflow

The verification is integrated seamlessly with the existing workflow:
- No changes needed to the reusable build workflow interface
- All existing functionality (rechunking, SBOM, signing) continues to work
- Added verification is a safety layer on top of existing manifest creation
- PR builds still work as before (verification is skipped for PRs in some cases)

## Troubleshooting

If a manifest verification fails:
1. Check the job logs for the specific platform mismatch
2. Verify that the build for the missing platform(s) completed successfully
3. Check for registry push issues for specific platforms
4. Ensure the platform list in the build matrix matches the intended platforms

## Configuration

The verification is controlled by:
- `inputs.platforms`: Defines expected platforms for each image variant
- Build variant selection (`inputs.build_variant`): Controls which verification jobs run
- The existing `if` conditions ensure verification only runs when appropriate