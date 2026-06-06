# just/pipeline.just — Top-level build pipeline orchestration

# [pipeline]
# Run the full staged build pipeline
pipeline variant='all' flavor='all' tag='latest' dry_run='0':
    #!/usr/bin/env bash
    export JUST="{{ just }}"
    ./scripts/pipeline.sh "{{ variant }}" "{{ flavor }}" "{{ tag }}" "{{ dry_run }}"

# [pipeline]
# Attach to the currently running Zellij pipeline session
attach:
    #!/usr/bin/env bash
    SESSION=$(zellij list-sessions 2>/dev/null | grep "pipeline-" | head -1 | awk '{print $1}')
    [[ -z "$SESSION" ]] && SESSION=$(zellij list-sessions 2>/dev/null | grep -v "gemini-" | head -1 | awk '{print $1}')
    if [ -n "$SESSION" ]; then echo "Attaching to Zellij session: $SESSION"; zellij attach "$SESSION"
    else echo "No active zellij session found."; exit 1; fi
