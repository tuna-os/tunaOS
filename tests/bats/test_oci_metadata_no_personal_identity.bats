#!/usr/bin/env bats
# tunaOS#1649: the io.artifacthub.package.maintainers OCI label baked into
# every published image hardcoded a maintainer's personal email
# (jreilly1821@gmail.com). Unlike a build-time convenience, this is a shipped
# artifact -- it leaks personal data into every published container's
# metadata in perpetuity, and cannot be fixed after the fact for images
# already published. Replaced with vars.MAINTAINER_NAME/vars.MAINTAINER_EMAIL
# (empty by default) so it can be set centrally without touching the
# workflow, same pattern this file already uses for vars.IMAGE_REGISTRY.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

@test "reusable-build-image.yml does not hardcode a personal email in OCI metadata" {
  workflow="${REPO_ROOT}/.github/workflows/reusable-build-image.yml"
  ! grep -q '@gmail\.com\|@[a-zA-Z0-9.-]\+\.[a-zA-Z]\{2,\}"' "$workflow"
}

@test "reusable-build-image.yml sources the ArtifactHub maintainer identity from repo/org vars" {
  workflow="${REPO_ROOT}/.github/workflows/reusable-build-image.yml"
  grep -q 'io.artifacthub.package.maintainers=.*vars.MAINTAINER_NAME' "$workflow"
  grep -q 'io.artifacthub.package.maintainers=.*vars.MAINTAINER_EMAIL' "$workflow"
}
