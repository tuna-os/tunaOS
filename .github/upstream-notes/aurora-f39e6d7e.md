# aurora@f39e6d7e — not ported

No TunaOS code changes were required for this commit.

## Reason
- Upstream change only adjusts GitHub Actions trigger branches in `.github/workflows/build-image-latest-main.yml`.
- TunaOS porting rules explicitly exclude CI/CD workflow changes from Aurora ports.
- No corresponding KDE runtime/package/config change exists for `build_scripts/kde.sh` or `system_files_overrides/kde/`.
