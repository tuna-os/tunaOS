# TunaOS Bootc Container Images
TunaOS is a collection of bootc-based desktop operating systems built on AlmaLinux, CentOS, and Fedora. This is a **container-based OS image builder**, not traditional software - images are built as containers and can be used as bootable operating systems.

Always reference these instructions first and fallback to search or bash commands only when you encounter unexpected information that does not match the info here.

## Working Effectively

### Dependencies and Setup
- Install Just command runner to a temp dir not the root of the repo: `mkdir .just && wget https://github.com/casey/just/releases/download/1.32.0/just-1.32.0-x86_64-unknown-linux-musl.tar.gz -O just.tar.gz && tar xzf .just/just.tar.gz && sudo mv .just/just /usr/local/bin/ && rm -rf .just`
- Podman is required for container builds (usually pre-installed in CI environments)
- Shellcheck is required for linting: `sudo apt-get update && sudo apt-get install -y shellcheck`
- Root privileges are required for ISO/VM image generation

### Core Build Commands
- `just --list` - Show all available commands
- `just check` - Syntax check for shell scripts and Just files (takes ~1-2 seconds)
- `just lint` - Run shellcheck on all shell scripts (takes ~0.5 seconds)
- `just fix` - Format shell scripts and Just files (requires shfmt)

### Image Building
- `just build <variant> <flavor>` - Build container images
- Examples:
  - `just build yellowfin base` - Build basic yellowfin image
  - `just build albacore dx` - Build AlmaLinux developer image  
  - `just build yellowfin gdx` - Build AlmaLinux Kitten with NVIDIA support

### **CRITICAL BUILD TIMING**: 
- **NEVER CANCEL BUILDS**: Container builds take 45-60 minutes. Set timeout to 90+ minutes minimum.
- **CI TIMEOUT**: GitHub Actions uses 60-minute timeout - respect this as the maximum expected build time.
- Use `timeout=5400` (90 minutes) for build commands to ensure completion.

### ISO and VM Generation
- `sudo just iso <variant> <flavor> <repo>` - Generate bootable ISO
- `sudo just qcow2 <variant> <flavor> <repo>` - Generate QCOW2 VM image
- Examples:
  - `sudo just iso yellowfin base local` - Create ISO from local build
  - `sudo just iso albacore dx ghcr` - Create ISO from published image
- **NOTE**: Requires root privileges and takes additional 20-30 minutes

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
1. `just check` - Verify syntax
2. `just lint` - Check shell script quality  
3. Build and test at least one complete image: `just build yellowfin base`
4. **MANUAL FUNCTIONAL TESTING**: If building ISOs, test boot and basic desktop functionality

### **END-TO-END TESTING SCENARIOS**:
- Build base yellowfin image and verify it completes without errors
- Test ISO generation: `sudo just iso yellowfin base local`
- Verify build scripts complete all phases (00-workarounds through cleanup)
- Check that built images include expected software (GNOME, Flathub, etc.)

### Common Build Failure Points:
- Network connectivity issues during base image pull
- Insufficient disk space (builds require ~20GB free space)
- Missing root privileges for ISO generation
- Build timeout in CI (must complete within 60 minutes)

## Development Workflow

### Making Changes:
1. **Always run syntax checks first**: `just check && just lint`
2. **Test locally before pushing**: Build at least one variant to verify changes work
3. **Respect build timing**: Allow 45-60 minutes for full builds, never cancel early
4. **CI Integration**: All changes must pass GitHub Actions workflow within 60-minute timeout

### File Structure:
- `Justfile` - Main build system configuration  
- `build_scripts/` - Container build scripts (run during image build)
- `system_files/` - Files copied into all image variants
- `system_files_overrides/` - Variant-specific file overrides
- `Containerfile*` - Docker/Podman build definitions
- `.github/workflows/` - CI/CD pipeline definitions

### Configuration Files:
- `scripts/get-base-image.sh` - Maps variants to base container images
- `image-versions.yaml` - Version pinning for base images
- Build arguments passed via environment variables

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
- Multi-platform builds (AMD64, ARM64, AMD64v2)
- Matrix-based building for all variant/flavor combinations  
- Automatic publishing to ghcr.io/tuna-os/
- Image signing with cosign
- SBOM generation for security compliance

## Troubleshooting

### Build Failures:
- Check network connectivity if base image pull fails
- Verify sufficient disk space (20GB+ required)
- Review build logs for specific script failures
- Most failures occur in package installation steps

### Syntax Errors:
- Run `just check` to verify Just syntax
- Run `just lint` for shell script issues
- Common issue: shell variables must be quoted properly

### Performance Issues:
- Builds are CPU and I/O intensive
- Use build caching when available (`just build` enables RPM cache for local builds)
- Consider building one variant at a time instead of `build-all`

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