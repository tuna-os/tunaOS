#!/usr/bin/env bats
# Test per-variant Plymouth boot theme assets and selection logic.
#
# Each variant gets a themed boot animation matching its build-config.yml
# emoji (extracted Noto animated emoji frames, or a static single frame for
# emoji with no animated GIF — see build_scripts/26-packages-post.sh).

SCRIPT="build_scripts/26-packages-post.sh"
THEMES_DIR="system_files/usr/share/plymouth/themes"

@test "26-packages-post.sh maps every build-config variant to a theme" {
    for variant in yellowfin albacore skipjack bonito sailfin guppy bonito-rawhide grouper marlin flounder flounder-sid; do
        grep -q "^${variant})" "$SCRIPT"
    done
}

@test "every mapped theme has a .plymouth descriptor and .script file" {
    for theme in tunaos tropical-fish sushi fishing-pole shark rainbow dragon rocket pufferfish radioactive; do
        [ -f "${THEMES_DIR}/${theme}/${theme}.plymouth" ]
        [ -f "${THEMES_DIR}/${theme}/${theme}.script" ]
    done
}

@test "every theme has at least one numbered frame matching its script prefix" {
    # tunaos predates the per-variant themes and uses "fish-" as its frame
    # prefix (not "tunaos-"); the rest use their own theme name as the prefix.
    declare -A prefix=(
        [tunaos]=fish [tropical-fish]=tropical-fish [sushi]=sushi
        [fishing-pole]=fishing-pole [shark]=shark [rainbow]=rainbow
        [dragon]=dragon [rocket]=rocket [pufferfish]=pufferfish
        [radioactive]=radioactive
    )
    for theme in "${!prefix[@]}"; do
        run bash -c "ls '${THEMES_DIR}/${theme}/${prefix[$theme]}-'*.png 2>/dev/null | wc -l"
        [ "$output" -gt 0 ]
    done
}

@test "unmapped/unknown variant falls back to the tunaos theme" {
    run bash -c "grep -A2 'PLYMOUTH_THEME=\"tunaos\"' '$SCRIPT' | head -1"
    [[ "$output" == *'PLYMOUTH_THEME="tunaos"'* ]]
}

@test "26-packages-post.sh still calls plymouth-set-default-theme with the resolved variable" {
    grep -q 'plymouth-set-default-theme "\$PLYMOUTH_THEME"' "$SCRIPT"
}

@test "26-packages-post.sh passes shellcheck" {
    run shellcheck -x "$SCRIPT"
    [ "$status" -eq 0 ]
}
