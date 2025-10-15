# TunaOS Bootc Container Images

TunaOS is a collection of bootc-based desktop operating systems built on AlmaLinux, CentOS, and Fedora. This is a **container-based OS image builder**, not traditional software - images are built as containers and can be used as bootable operating systems.

## Key Concepts
- **Bootc Technology**: These are bootable container images, not traditional applications
- **Container-First**: All OS images are built as OCI containers using Podman/Docker
- **Immutable OS**: Users receive atomic updates via container pulls
- **Multiple Variants**: Same codebase produces different OS variants based on different upstream bases
- **Flavor System**: Base → DX → GDX is a chain where each builds on the previous

Always reference these instructions first and fallback to search or bash commands only when you encounter unexpected information that does not match the info here.

## Quick Reference

### Most Common Tasks
```bash
# Validate your changes
just check

# Build a single variant (fastest test)
just yellowfin base

# Build the full chain for a variant
just yellowfin base && just yellowfin dx && just yellowfin gdx

# Clean everything and start fresh
just clean

# Create an ISO for testing
sudo just iso yellowfin base local
```

### When to Build Images
- **Always**: If you change `Containerfile*`, `build_scripts/*`, or `system_files*`
- **Sometimes**: If you change `scripts/*` and want to test ISO/VM generation
- **Never**: For documentation changes, workflow changes, or README updates

## Working Effectively

### Dependencies and Setup
- Install Just command runner to a temp dir not the root of the repo: `mkdir -p /tmp/just && cd /tmp/just && wget https://github.com/casey/just/releases/download/1.32.0/just-1.32.0-x86_64-unknown-linux-musl.tar.gz -O just.tar.gz && tar xzf just.tar.gz && sudo mv just /usr/local/bin/ && cd - && rm -rf /tmp/just`
- **CRITICAL**: NEVER extract just or any other tools directly into the repository root as this will overwrite project files like LICENSE and README.md
- Podman is required for container builds (usually pre-installed in CI environments)
- Shellcheck is required for linting: `sudo apt-get update && sudo apt-get install -y shellcheck`
- Root privileges are required for ISO/VM image generation

### Core Build Commands
- `just --list` - Show all available commands
- `just check` - Comprehensive syntax check for shell scripts, YAML, JSON, and Just files (takes ~1-2 seconds)
  - Runs shellcheck on all `.sh` files
  - Runs yamllint on all `.yaml` and `.yml` files
  - Validates JSON files with jq
  - Checks Just file syntax
- `just fix` - Format shell scripts and Just files (requires shfmt, currently formats shell scripts and Just files)

### Image Building
- `just build <variant> <flavor>` - Build container images
- Shortcut commands:
  - `just yellowfin [flavor]` - Build yellowfin variant (defaults to base)
  - `just albacore [flavor]` - Build albacore variant (defaults to base)
  - `just skipjack [flavor]` - Build skipjack variant (defaults to base)
  - `just bonito [flavor]` - Build bonito variant (defaults to base)
- Batch building:
  - `just build-all` - Build all stable variants (yellowfin, albacore, skipjack) with all flavors
  - `just build-all-base` - Build only base images for all variants including experimental
  - `just build-all-experimental` - Build all variants including experimental (bonito)
- Examples:
  - `just build yellowfin base` - Build basic yellowfin image
  - `just build albacore dx` - Build AlmaLinux developer image  
  - `just yellowfin gdx` - Build AlmaLinux Kitten with NVIDIA support (shortcut)
  - `just albacore` - Build AlmaLinux base image (shortcut)

### **CRITICAL BUILD TIMING**: 
- **NEVER CANCEL BUILDS**: Container builds take 45-60 minutes. Set timeout to 90+ minutes minimum.
- **CI TIMEOUT**: GitHub Actions uses 60-minute timeout - respect this as the maximum expected build time.
- Use `timeout=5400` (90 minutes) for build commands to ensure completion.

### ISO and VM Generation
- `sudo just iso <variant> <flavor> <repo>` - Generate bootable ISO using Titanoboa
- `sudo just qcow2 <variant> <flavor> <repo>` - Generate QCOW2 VM image
- Parameters:
  - `variant` - yellowfin, albacore, skipjack, or bonito
  - `flavor` - base, dx, or gdx (defaults to base)
  - `repo` - local (use locally built image) or ghcr (use published image from ghcr.io)
- Examples:
  - `sudo just iso yellowfin base local` - Create ISO from local build
  - `sudo just iso albacore dx ghcr` - Create ISO from published image
  - `sudo just qcow2 yellowfin gdx local` - Create VM disk image from local build
- **NOTE**: Requires root privileges and takes additional 20-30 minutes

### Utility Commands
- `just clean` - Clean up build artifacts, caches, and local images
  - Removes `.rpm-cache-*` directories
  - Removes `.build-logs` directory
  - Removes `.build/*` directory
  - Removes all local podman images for TunaOS variants

## Image Variants and Flavors

### Variants (Base OS):
1. **yellowfin** - AlmaLinux Kitten 10 (most compatible with upstream Bluefin LTS)
2. **albacore** - AlmaLinux 10 (stable enterprise)
3. **skipjack** - CentOS Stream 10 (experimental) 
4. **bonito** - Fedora 42 (cutting edge, incomplete)

### Flavors (Feature Sets):
1. **base** - Basic desktop OS with GNOME, Flathub, Homebrew
2. **dx** - Developer Experience: adds Docker, VSCode, development tools
3. **gdx** - Graphics Developer Experience: adds NVIDIA drivers, CUDA

### Build Dependencies:
- Base images are pulled from Quay.io registries
- Network connectivity required for initial base image pulls
- Builds chain: base → dx → gdx (dx builds from base, gdx builds from dx)

## Validation and Testing

### **MANDATORY VALIDATION STEPS**:
After making any changes, ALWAYS:
1. `just check` - Verify syntax (includes shellcheck, yamllint, JSON validation, and Just syntax)
2. Build and test at least one complete image: `just build yellowfin base` (if changes affect build scripts or Containerfiles)
3. **MANUAL FUNCTIONAL TESTING**: If building ISOs, test boot and basic desktop functionality

### **END-TO-END TESTING SCENARIOS**:
- Build base yellowfin image and verify it completes without errors
- Test ISO generation: `sudo just iso yellowfin base local`
- Verify build scripts complete all phases (00-workarounds through cleanup)
- Check that built images include expected software (GNOME, Flathub, etc.)
- Test the build chain: `just yellowfin base && just yellowfin dx && just yellowfin gdx`

### **QUICK VALIDATION** (for minor changes):
For changes that don't affect the build process (e.g., documentation, CI config):
1. `just check` - Verify syntax only
2. Review the specific files changed
3. No image building required unless changes affect Containerfiles or build scripts

### Common Build Failure Points:
- Network connectivity issues during base image pull
- Insufficient disk space (builds require ~20GB free space)
- Missing root privileges for ISO generation
- Build timeout in CI (must complete within 60 minutes)

## Development Workflow

### Making Changes:
1. **Always run syntax checks first**: `just check`
2. **Test locally before pushing**: Build at least one variant to verify changes work
3. **Respect build timing**: Allow 45-60 minutes for full builds, never cancel early
4. **CI Integration**: All changes must pass GitHub Actions workflow within 60-minute timeout

### File Structure:
- `Justfile` - Main build system configuration with all build commands
- `build_scripts/` - Container build scripts (run during image build)
  - `lib.sh` - Shared library functions for build scripts
  - `BASE.sh`, `DX.sh`, `GDX.sh` - Flavor-specific build scripts
  - `overrides/` - Variant-specific build script overrides
- `system_files/` - Files copied into all image variants
  - `etc/` - System configuration files
  - `usr/` - User-space files and scripts
- `system_files_overrides/` - Variant-specific file overrides
  - `dx/` - Developer Experience specific files
  - `gdx/` - Graphics Developer Experience specific files
- `Containerfile` - Base image build definition
- `Containerfile.dx` - DX flavor build definition
- `Containerfile.gdx` - GDX flavor build definition
- `.github/` - GitHub-specific files
  - `workflows/` - CI/CD pipeline definitions (reusable-build-image.yml is the main workflow)
  - `copilot-instructions.md` - This file
- `scripts/` - Helper scripts for building and testing
  - `get-base-image.sh` - Maps variants to base container images
  - `build-bootc-diskimage.sh` - Creates VM disk images
  - `build-titanoboa.sh` - Creates ISO images using Titanoboa
  - `build-all-images.sh` - Batch building script
- `iso_files/` - Files and scripts for ISO generation
- `docs/` - Documentation files

### Configuration Files:
- `scripts/get-base-image.sh` - Maps variants to base container images
- `image-versions.yaml` - Version pinning for base images
- `.yamllint.yml` - YAML linting configuration
- `renovate.json5` - Dependency update automation configuration

### Environment Variables and Build Arguments:
The Justfile uses several environment variables that can be overridden:
- `GITHUB_REPOSITORY_OWNER` - Repository owner (defaults to "tuna-os")
- `DEFAULT_TAG` - Default image tag (defaults to "latest")
- `BIB_IMAGE` - Bootc image builder image (defaults to quay.io/centos-bootc/bootc-image-builder:latest)
- `PLATFORM` - Build platform (auto-detected based on architecture)
- `BASE_IMAGE` - Base container image for builds (defaults to quay.io/almalinuxorg/almalinux-bootc)
- `BASE_IMAGE_TAG` - Tag for base image (defaults to "10")

Build arguments passed to Podman:
- `IMAGE_NAME` - Name of the image being built
- `IMAGE_VENDOR` - Repository organization
- `BASE_IMAGE` - Parent image for the build
- `SHA_HEAD_SHORT` - Short git commit SHA (if repo is clean)

## Architecture Understanding

### Container-Native OS:
- This is NOT traditional software - it builds bootable OS images as containers
- Images are based on bootc technology (like CoreOS but newer)
- Final output is container images that can be booted as operating systems
- Uses rpm-ostree technology under the hood for atomic updates

### Build Process Flow:
1. Pull base image (AlmaLinux/CentOS/Fedora bootc image)
2. Copy system files and build scripts
3. Run build scripts in sequence (numbered 00- through 90-)
4. Apply variant-specific overrides
5. Create final bootable container image

### CI/CD Pipeline:
- **Main workflow**: `.github/workflows/reusable-build-image.yml`
  - Multi-platform builds (AMD64, ARM64, AMD64v2)
  - Matrix-based building for all variant/flavor combinations
  - Automatic publishing to ghcr.io/tuna-os/
  - Image signing with cosign
  - SBOM generation for security compliance
  - Rechunking for optimized image layers
- **Other workflows**:
  - `generate-changelog-release.yml` - Automated changelog generation
  - `scorecard.yml` - Security scorecards
  - `content-filter.yaml` - Content filtering for PRs
  - `validate-renovate.yaml` - Validates Renovate configuration
- **Build process**:
  1. Builds base flavor first
  2. Builds dx flavor using base as parent
  3. Builds gdx flavor using dx as parent
  4. Each build is independent per platform and variant
  5. Final images are pushed to ghcr.io and signed

## Common Pitfalls and Best Practices

### Critical Don'ts:
- **NEVER cancel builds early**: Builds take 45-60 minutes, canceling early wastes resources
- **NEVER extract tools to repo root**: Always use /tmp or other temporary directories to avoid overwriting project files
- **NEVER skip validation**: Always run `just check` before committing changes
- **NEVER commit build artifacts**: Use `.gitignore` to exclude `.build/`, `.rpm-cache-*`, and similar directories

### Build Best Practices:
- Always build base flavor first before dx or gdx
- Use `just clean` between major changes to clear stale caches
- For local development, use `just build` with cache enabled (default for non-CI builds)
- Test with at least one variant before pushing to avoid CI failures

### Script Development:
- All shell scripts must pass shellcheck
- Use `set -euo pipefail` in bash scripts for proper error handling
- Quote all variables properly
- Follow the existing script structure in `build_scripts/lib.sh`

## Troubleshooting

### Build Failures:
- Check network connectivity if base image pull fails
- Verify sufficient disk space (20GB+ required)
- Review build logs for specific script failures
- Most failures occur in package installation steps
- Check that parent images exist (base for dx, dx for gdx)
- Verify podman is installed and running

### Syntax Errors:
- Run `just check` to verify all syntax (shell scripts, YAML, JSON, Just files)
- Common issues:
  - Shell variables must be quoted properly
  - YAML files may have trailing spaces or line length issues
  - JSON files must be valid (validated with jq)
  - Shellcheck errors (SC1091 is excluded for sourced files)

### Performance Issues:
- Builds are CPU and I/O intensive
- Use build caching when available (`just build` enables RPM cache for local builds)
- Consider building one variant at a time instead of `build-all`
- Clean up old images with `just clean` to free disk space

### ISO/VM Generation Issues:
- Requires root privileges (sudo)
- Requires bootc-image-builder to be available
- Takes 20-30 minutes additional time
- Check that source image exists (local or ghcr)

## Key Project Information

### Documentation:
- README.md - Project overview and installation instructions
- docs/BUILD_IMPROVEMENTS.md - Recent build system enhancements
- docs/CODE_REVIEW_SUMMARY.md - Development workflow improvements

### External Dependencies:
- Base images from quay.io (AlmaLinux, CentOS, Fedora)
- bootc-image-builder for ISO/VM generation
- Universal Blue ecosystem compatibility

### Release Information:
- Images published to ghcr.io/tuna-os/
- Multiple architecture support
- Regular automated builds via GitHub Actions
- Compatible with rpm-ostree and bootc tooling