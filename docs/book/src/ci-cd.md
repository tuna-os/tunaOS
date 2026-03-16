# CI/CD Pipelines

TunaOS uses GitHub Actions for automated building, testing, and distribution of container images and ISO artifacts.

## Main Workflows

- **Build Images**: Automated builds for all variants and flavors triggered on changes and schedules.
- **Build Live ISOs**: Generates bootable Live ISOs from `bootc` container images and uploads to Cloudflare R2.
- **Verification**: Automatic boot testing using Lima VMs.
