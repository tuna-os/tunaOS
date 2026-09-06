# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: pass Markdown on stdin with a quoted heredoc delimiter:

  ```bash
  gh issue create --title 'Short title' --body-file - <<'EOF'
  ## What happened

  Markdown such as `env`, $GH_TOKEN, and $(command) stays literal.
  EOF
  ```

- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: use the same stdin pattern:

  ```bash
  gh issue comment <number> --body-file - <<'EOF'
  Markdown comment, including `code` and $VARIABLE references.
  EOF
  ```

- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: add a closing explanation with the safe comment form above, then run `gh issue close <number>`.

### Markdown is never a shell argument

Never put generated or authored Markdown directly in `--body`, `--comment`, or
a double-quoted shell variable assignment. Backticks, `$(...)`, and `$VARIABLE`
are shell syntax: the shell evaluates them before `gh` sees the text and can
splice credentials or command output into a public issue. Escaping backticks
alone is not sufficient.

Use `--body-file -` and a **single-quoted heredoc delimiter** (`<<'EOF'`) so the
shell performs no command, parameter, or backslash expansion. A temporary file
created with a quoted heredoc and passed through `--body-file "$file"` is also
safe when the body must be reused.

Infer the repo from `git remote -v` — `gh` does this automatically when run inside a clone.

## When a skill says "publish to the issue tracker"

Create a GitHub issue using the quoted-heredoc `--body-file -` form above.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.
