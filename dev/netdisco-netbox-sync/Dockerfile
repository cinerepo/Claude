# tools/netdisco-netbox-sync/Dockerfile
#
# Containerizes netdisco-netbox-sync for in-cluster deployment - see README.md for why this
# moved off the bare host (Diode's OAuth2 auth path only works cleanly through the same
# internal, ClusterIP-only ingress NetBox's own Diode plugin uses - see the main repo's
# Battle Log for the full story - so running this tool inside the cluster avoids needing to
# expose that ingress externally at all).
#
# Built and published automatically by
# .github/workflows/build-netdisco-netbox-sync-image.yml on any push to this directory.
# Publishes to ghcr.io/cinerepo/netdisco-netbox-sync:latest - no version pin, unlike
# charts/netbox's image: this is actively-developed first-party code, not a third-party
# dependency with a compatibility window to protect.
#
# sqlite3 CLI included deliberately - this tool's whole point right now is being poked at
# directly (kubectl exec into the standing debug pod, `sqlite3 data/observed_assets.db`)
# while rules.yaml is still being tuned, not run-and-forget.
#
# Networking/diagnostic CLI tools included for the same reason - this debug pod is meant to
# be exec'd into and used directly to troubleshoot connectivity to netdisco/diode/netbox
# (same kind of thing net-debug has been used for elsewhere in this project), not just to
# run the two pipelines. nano included so rules.yaml can be edited in place on the mounted
# PVC without needing kubectl cp for every change.
#
# Debian packages the "bat" binary as batcat (name collision with an unrelated package) -
# symlinked to bat below so it works as expected.

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        sqlite3 \
        curl \
        net-tools \
        iproute2 \
        iputils-ping \
        traceroute \
        mtr-tiny \
        dnsutils \
        netcat-openbsd \
        bat \
        nano \
    && ln -s /usr/bin/batcat /usr/local/bin/bat \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copying everything before installing (rather than pyproject.toml first for layer-caching)
# because pip install . needs the actual module files present - pyproject.toml's
# [tool.setuptools] py-modules list references sync.py/config.py/etc. directly. This
# project is small enough that the caching tradeoff doesn't matter.
COPY . .

RUN pip install --no-cache-dir . \
    && chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]

# Keeps the standing debug pod alive indefinitely by default (kubectl exec in to run
# sync.py/discover.py manually, or poke at the sqlite DB with the sqlite3 CLI above). The
# two CronJobs override this with their own real commands - see playbooks/sync-tool.yml.
CMD ["sleep", "infinity"]
