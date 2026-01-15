# Agent Guidelines for TunaOS

This document contains guidelines for AI agents (like GitHub Copilot) working on the TunaOS repository.

## Pre-Commit Requirements

### Always Run `just fix` Before Committing

Before making any commit, **always** run `just fix` to ensure code is properly formatted:

```bash
just fix
```

This command will:
- Format shell scripts using `shfmt` (if available)
- Format Just files using `just --unstable --fmt`
- Ensure consistent formatting across the codebase

### Validation Workflow

Follow this workflow for all changes:

1. Make your code changes
2. Run `just fix` to format the code
3. Run `just check` to validate syntax
4. Review changes with `git status` and `git diff`
5. Commit changes only after formatting and validation pass

## Example Workflow

```bash
# 1. Make changes to files
vim Justfile

# 2. Format the code
just fix

# 3. Validate syntax
just check

# 4. Review changes
git status
git diff

# 5. Commit (via report_progress or other approved methods)
```

## Why This Matters

- **Consistency**: Ensures all code follows the same formatting standards
- **CI/CD**: Prevents formatting-related CI failures
- **Collaboration**: Makes code reviews easier with consistent formatting
- **Best Practice**: Maintains high code quality across the project

## Additional Resources

- See `.github/copilot-instructions.md` for comprehensive coding guidelines
- See `Justfile` for all available commands
- Run `just --list` to see available commands
