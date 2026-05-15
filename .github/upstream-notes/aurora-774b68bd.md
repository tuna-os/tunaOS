# aurora@774b68bd — not ported

No TunaOS code changes were required for this commit.

## Reason
- Upstream change only modifies Aurora Renovate configuration (`.github/renovate.json5`) to enable updates on `beta`.
- TunaOS porting rules explicitly exclude CI/CD and Renovate config from Aurora ports.
- No corresponding KDE runtime/package/config change exists for `build_scripts/kde.sh` or `system_files_overrides/kde/`.
