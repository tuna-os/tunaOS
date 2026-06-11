# Rename GDX flavor to NVIDIA

The `-gdx` flavor suffix will be renamed to `-nvidia`. "GDX" is an opaque internal name — it doesn't tell users that this flavor adds NVIDIA drivers and CUDA. "NVIDIA" is universally understood, matches what users search for, and eliminates the need to explain what "GDX" means in documentation.

**Considered Options:**

1. **Keep GDX** — zero migration cost, but permanently confusing name. Every new user asks "what's GDX?"
2. **Ship both** — publish `-gdx` and `-nvidia` tags in parallel. Doubles the tag surface, CI matrix, and storage. Confusion about which to use.
3. **Rename to -nvidia** — clear, discoverable, one-time migration cost for existing users.

**Status:** accepted
