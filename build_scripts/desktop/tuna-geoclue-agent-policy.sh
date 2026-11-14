#!/usr/bin/env bash
# GeoClue's [agent] whitelist replaces rather than appends, so the stock list
# refuses tuna-shell as the desktop's location agent. tuna-desktop (from
# v1.0.0-beta.3) ships /usr/libexec/tuna-geoclue-agent-policy, which writes an
# early vendor conf.d fragment from the packaged geoclue.conf plus tuna-shell
# and refuses administrator-modified inputs. Upstream's
# packaging/marlin/Containerfile runs it right after installing the package;
# this is the same image-construction step. It never grants an application
# location access.
#
# Sourced by install-desktop.sh through the tuna-arch profile's after_install.
set -euo pipefail

TUNA_IMAGE_BUILD=1 /usr/libexec/tuna-geoclue-agent-policy
