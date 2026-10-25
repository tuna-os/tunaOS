# Fictional bug report example

This report is fictional. It uses an invented preview tool, version, commit,
and log. They do not describe a TunaOS defect or a shipped tool. Do not run the steps or file this example as an issue.

For a suspected vulnerability, follow [SECURITY.md](../SECURITY.md) to
report it privately. Do not put vulnerability details in a public issue.

## Prepare a report

For an ordinary bug, record the smallest set of steps that shows the problem.
Include the expected result, actual result, affected version or commit, and
only the log lines that help explain the failure. Say how often it occurs.
Record your OS and tool versions when they affect the result.

Review text and screenshots before you post them. Replace usernames,
hostnames, IP and email addresses, private paths, and tokens with placeholders
such as `<USER>`, `<HOST>`, `<IP_ADDRESS>`, `<EMAIL_ADDRESS>`, and
`<TOKEN_REDACTED>`. Use the same placeholder for each occurrence of a value.
Keep error codes and relevant file names so someone can follow the failure.
Do not copy credentials, unrelated logs, or dumps of the environment.

## Worked report (fictional)

### Title

Docs preview keeps the previous page title after navigation

### Environment and version

- Component: fictional tool for local documentation previews
- Version: `v0.0.0-fictional`
- Commit: `0000000000000000000000000000000000000000` (dummy value)
- OS: `<OS_NAME_AND_VERSION>`; browser: `<BROWSER_AND_VERSION>`
- Preview address: `https://<HOST>/preview`
- User: `<USER>`; contact: `<EMAIL_ADDRESS>` (omitted from a public report)

### Minimal reproduction

These steps describe the fictional tool only. You can read this example
without an installation or image build.

1. Open the local documentation preview at `https://<HOST>/preview`.
2. Select the **Overview** page. Check that its title is **Overview**.
3. Select the **Setup** page from the navigation list.

### Expected behavior

The page body and browser tab title both change to **Setup**.

### Actual behavior

The page body changes to **Setup**, but the tab title stays
**Overview**. This occurs in all three tries in a new browser session.
A page reload shows the correct title.

### Short redacted log

This example uses a made-up log with no private data.
The placeholders show how to replace private values before you post a report.

```text
12:00:00 INFO preview version=v0.0.0-fictional commit=0000000
12:00:01 INFO session user=<USER> host=<HOST> client=<IP_ADDRESS>
12:00:01 DEBUG request Authorization: Bearer <TOKEN_REDACTED>
12:00:02 INFO render source=/home/<USER>/<PRIVATE_PATH>/setup.md status=200
12:00:02 ERROR TITLE_NOT_UPDATED expected="Setup" actual="Overview"
```

The log preserves the event order, file name, and error. Placeholders replace
user, host, address, private directory, and token values. The title mismatch is an
observation; this report does not establish its cause.
