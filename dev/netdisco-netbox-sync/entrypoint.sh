#!/bin/sh
set -eu

# rules.yaml lives on the mounted PVC (RULES_FILE env - this platform's Deployment/CronJob
# manifests set it to data/rules.yaml, inside the same mount as the sqlite staging DB) so
# edits survive pod restarts and CronJob runs. Bootstrapped once from the shipped example -
# never overwritten after that, same "force: false, never clobber an existing file" behavior
# playbooks/sync-tool.yml used to provide when this ran directly on the host.
RULES_FILE="${RULES_FILE:-rules.yaml}"
if [ ! -f "$RULES_FILE" ]; then
    mkdir -p "$(dirname "$RULES_FILE")"
    cp rules.yaml.example "$RULES_FILE"
    echo "[entrypoint] Bootstrapped $RULES_FILE from rules.yaml.example"
fi

exec "$@"
