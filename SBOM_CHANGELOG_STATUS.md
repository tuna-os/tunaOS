# SBOM Changelog Implementation Status

## Current State

### ✅ What's Implemented

1. **SBOM Generation** (in `reusable-build-image.yml`):
   - Syft generates SPDX JSON SBOMs
   - SBOMs attached to OCI images via ORAS
   - SBOMs signed with cosign
   - Configuration: `sbom: true` on line 217 of `build-variant.yml`

2. **Changelog Action** (in `generate-changelog-release.yml`):
   - Already using `hanthor/changelog-action@master`
   - Configured for TunaOS registry: `ghcr.io/tuna-os/`
   - Images: `yellowfin albacore skipjack`
   - Stream-based tag discovery with pattern `^\d{8}$`

3. **Tag Format**:
   - Format: `{flavor}-{YYYYMMDD}` (e.g., `gnome-20250323`)
   - Set by `default-tag: ${{ matrix.flavor }}` in `build-variant.yml:215`
   - Date tag added in `reusable-build-image.yml:718`

### ❌ Current Problem

**No SBOMs attached to any builds yet**

The workflow shows:
- `sbom: true` is enabled
- `continue-on-error: true` on SBOM generation (line 203)
- SBOM upload only happens if `steps.generate-sbom.outputs.SBOM != ''` (line 332)

**Result**: No SBOM referrers found for any images, meaning the changelog action cannot find 2 builds to compare.

### 📋 What's Needed to Make It Work

According to `changelog.py:409-423`:
```python
if len(sbom_tags) < 2:
    raise ValueError(
        f"Found fewer than 2 SBOM-bearing tags... "
        f"Builds may not yet have SBOM attachments — wait for at least two SBOM-enabled builds."
    )
```

You need **2 completed builds** with:
1. SBOM successfully generated
2. SBOM successfully attached via ORAS
3. ORAS-attached SBOM verified by the changelog action

## Testing the Setup

### Manual Test (to verify workflow works)

Once you have 2 SBOM-bearing builds:

```bash
# Test with workflow_dispatch
gh workflow run generate-changelog-release.yml \
  -f stream=gnome \
  -f handwritten="Test changelog generation" \
  -f dry_run=true
```

### Verify SBOMs are Attached

```bash
# Check if a specific tag has SBOM
oras discover \
  --artifact-type application/vnd.spdx+json \
  --format json \
  "ghcr.io/tuna-os/yellowfin:gnome-20250323"
```

Expected output should show referrers with SBOM content.

## Next Steps

1. **Wait for builds to complete** with SBOM generation
   - The SBOM generation step has `continue-on-error: true`
   - Check build logs for any SBOM generation failures
   - SBOMs should be attached automatically if generation succeeds

2. **Monitor for SBOM referrers**:
   ```bash
   # After a build completes, check for SBOM
   oras discover \
     --artifact-type application/vnd.spdx+json \
     --format json \
     "ghcr.io/tuna-os/yellowfin:gnome-20250323"
   ```

3. **Once 2 builds have SBOMs**, the changelog action will work automatically

## Potential Issues to Check

If builds complete but no SBOMs appear:

1. **Check build logs** for:
   - Syft installation failures
   - SBOM generation failures
   - ORAS attach failures
   - Permission issues

2. **Verify ORAS login** works (line 329):
   ```bash
   echo $GITHUB_TOKEN | oras login ghcr.io -u $GITHUB_ACTOR --password-stdin
   ```

3. **Check SBOM file exists** after generation (line 213):
   ```bash
   # Should output something like:
   # SBOM=/tmp/xyz/sbom.json
   ```

## Summary

**Status**: Setup is complete, waiting for SBOM-enabled builds to complete

**Action Required**: 
- Wait for at least 2 builds to complete with SBOMs attached
- The changelog action will auto-discover and compare them

**Files Involved**:
- Workflow: `.github/workflows/generate-changelog-release.yml`
- Changelog script: `scripts/` (in hanthor/changelog-action repo)
- SBOM generation: `.github/workflows/reusable-build-image.yml:197-374`
