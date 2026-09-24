---
tags: [gates, workflows, ci]
---

# Update `green-criteria.yml` gates when you move or rename a gate job

If you add, move or rename a job that asserts a green criterion, update its `gates` block in `.github/green-criteria.yml` in the same PR. `tests/test_ci_contract.py` (`just test-contract`) fails when the contract and the workflows disagree.

Source: `AGENTS.md` "A gate that is declared is a gate that runs".
