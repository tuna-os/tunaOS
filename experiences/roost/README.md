# Experimental Roost on Marlin

Admission is tracked in tunaOS#2990 and hanthor/roost-desktop#69. On 2026-10-04, @hanthor confirmed existing CI capacity for one additional amd64 Roost image and boot gate. The matrix entry remains disabled until the signed Tideforge Arch package is published. This adds no ISO or LUKS matrix cells.

The key is byte-identical to tuna-os/tunaos-packages `public.gpg` at commit `f560ade103d6369794c177e50cfd0e77863dc0c7`, SHA256 `4de5dfede473d4d56d79719a23e7b0925336719adfc142ea638735118039a82e`, primary fingerprint `4E5CC9F8B3B521793D95266E629BE6EA45188366`. Package signatures are required. Roost resolves explicitly from `tunaos/roost`; other packages retain Arch repository precedence.

The existing gtkgreet/cage launcher supplies a graphical greetd session picker and software rendering fallback. Roost's shipped session launches its supervisor, and its PAM lock service handles unlock. The desktop contract checks six executable versions, the session entry, PAM, calendar server, IBus, portal backends, keyring, WirePlumber and greeter. Image and runtime contract results are still required before publication; source checks do not establish boot readiness.
