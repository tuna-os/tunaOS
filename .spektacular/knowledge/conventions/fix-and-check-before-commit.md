---
tags: [ci, formatting, testing]
---

# Run `just fix && just check` before every commit

Run `just fix && just check` before every commit; it is mandatory, not advisory. Run `just test` (bats + pytest, same as CI) for code changes and `just ci` for the whole PR gate locally (check + CI contract + test).

Source: `AGENTS.md` Quick Reference; `docs/AGENT_GUIDE.md` "Pre-Commit (mandatory)".
