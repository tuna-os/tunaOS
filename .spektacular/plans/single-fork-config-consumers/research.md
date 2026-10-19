---
created_date: "2026-10-18"
document_status: final
closed_date: "2026-10-18"
---

# Findings

- Both install-desktop.sh and configure-desktop-runtime.sh must be adapted;
  Ubuntu niri/xfce bypass the first path (RFC013 and docs/BRANDING.md).
- pkg_remove masks pacman errors and emerge only deselects; denylist-only
  protection cannot prevent transitive base/session removal (build_scripts/lib.sh).
- Desktop active wallpaper is tunaos-default.jpg; inputs are decoded as JPEG
  before build and hashed, never relabeled PNG bytes.
- Generic repository v1 fields omit apt suites/components and Portage identity;
  only signed dnf/zypper .repo sources can be represented without guessing.
- Existing bind mount cache key hashes shell scripts only; fork manifests/assets
  must augment it or different customization reuses the same cached layers.
- Spektacular 0.20.0 version check passed. Discovery's repo list/always-applied
  lookup reports missing sibling docs/.spektacular; source-local guides read
  directly. External docs repo work is outside this slice.
