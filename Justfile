# ── Config ─────────────────────────────────────────────────────────────────
# All environment variables and platform detection. Recipes live in just/*.just
# modules imported below.

export repo_organization := env("GITHUB_REPOSITORY_OWNER", "tuna-os")
export default_tag := env("DEFAULT_TAG", "latest")
export common_image := env("COMMON_IMAGE", "ghcr.io/projectbluefin/common")
export brew_image := env("BREW_IMAGE", "ghcr.io/ublue-os/brew")
export coreos_stable_version := env("COREOS_STABLE_VERSION", "43")
just := just_executable()
arch := arch()
yq := `which yq`
export platform := env("PLATFORM", if arch == "x86_64" { if `rpm -q kernel 2>/dev/null | grep -q "x86_64_v2$"; echo $?` == "0" { "linux/amd64/v2" } else { "linux/amd64" } } else if arch == "arm64" { "linux/arm64" } else if arch == "aarch64" { "linux/arm64" } else { error("Unsupported ARCH '" + arch + "'. Supported values are 'x86_64', 'aarch64', and 'arm64'.") })

# --- Default Base Image (for 'base' flavor builds) ---
export base_image := env("BASE_IMAGE", "quay.io/almalinuxorg/almalinux-bootc")
export base_image_tag := env("BASE_IMAGE_TAG", "10")

# ── Module imports ─────────────────────────────────────────────────────────
import 'just/ci.just'
import 'just/deps.just'
import 'just/build.just'
import 'just/iso.just'
import 'just/vm.just'
import 'just/pipeline.just'

# ── Default ────────────────────────────────────────────────────────────────
[private]
default:
    @{{ just }} --list
