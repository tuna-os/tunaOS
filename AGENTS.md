# Agent Guidelines for TunaOS

This document contains guidelines for AI agents (like GitHub Copilot) working on the TunaOS repository.

## Setup Requirements

### Install Just via Homebrew

Before working on this repository, ensure you have `just` installed via Homebrew for consistency with CI:

```bash
# Install Homebrew if not already installed (Linux/macOS)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install just
brew install just
```

**Why Homebrew?** The CI environment uses Homebrew to install just, ensuring version consistency between local development and CI builds. This prevents formatting mismatches that can cause CI failures.

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
