---
tags: [variants, hummingbird, packaging]
---

# hummingbird is not Fedora 43 and ships no desktop by design

Trap: its `.fc43` dist tags are Rawhide numbering; it is a hardened Rawhide fork on the ARK kernel. Diagnoses assuming a Fedora 43 package set have been wrong repeatedly.
Do instead: read `docs/HUMMINGBIRD.md`; measure the repo index (`repo.tunaos.org/hummingbird/.../repodata`) rather than infer. `hummingbird:gnome` takes GNOME from `projectbluefin/utah-packages`. Source: `AGENTS.md` "Know your base".
