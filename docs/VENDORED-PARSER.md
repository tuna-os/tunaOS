# Reviewed TOML parser

All supported hosts use pure-Python Tomli 2.3.2 from `scripts/lib/_vendor/tomli`.
The import uses a repository-relative path. It does not select an installed
parser or download code. The grammar remains TOML 1.0 on Python 3.10 and 3.15.

The source is from [upstream revision d326dd59](https://github.com/hukkin/tomli/tree/d326dd59d8e10d621cba4de3ee110a7db6324ddd).
It includes the key-depth and nested-value limits in that release.
The source includes the unchanged MIT license and copyright notice.
`tomli-provenance.json` records the version, revision, and each file's SHA-256.

## Check the source

Run `python3 scripts/check-vendored-parser.py` to check the recorded bytes.
This command works offline. To compare an independently obtained checkout
of the recorded upstream revision, add `--upstream /path/to/tomli`.
The command checks bytes; the reviewer must verify that checkout's Git revision.

## Update the source

1. Review the upstream release, license, grammar, and resource-limit changes.
2. Check out its immutable revision in a separate directory.
3. Copy the four Python files, `py.typed`, and `LICENSE` without local edits.
4. Update the provenance revision and hashes. Update the version policy only
   when the grammar review allows it. Do not hide a TOML language change.
5. Run the offline check against that upstream checkout.
6. Run grammar, malformed-input, source-copy, and generated-byte tests on
   Python 3.10 and 3.15. Compare all generated adapters before publication.

The primary-config tests run the offline drift check. The parser belongs to
the host source tools; generated image adapters do not need Python.
The fork context includes these tracked files with the other tools.
