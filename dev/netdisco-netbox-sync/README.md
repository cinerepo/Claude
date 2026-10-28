# netdisco-netbox-sync

The discovery-to-IPAM glue between `netdisco` and `netbox`/`diode` in this
platform's `build_order`. Three pipelines, plus a web UI over all of them:

- **`sync.py`** - infrastructure sync. Pulls SNMP-managed devices (switches,
  firewalls) that Netdisco has already discovered and pushes them into
  NetBox via Diode. Meant to run on a schedule (hourly by default).
- **`discover.py`** - host discovery. Pulls end hosts from Netdisco's
  MAC/ARP table data, stages them in a local SQLite database, classifies
  them by VLAN intent (see `rules.yaml.example`) and stability over time,
  and lets you selectively promote candidates into NetBox. Also meant to
  run on a schedule (every 6 hours by default), with manual review of
  what it finds via its own CLI (`list-candidates`, `promote`, `ignore`,
  etc. - see `INSTALLATION_GUIDE.txt`).
- **`lifecycle.py`** - staleness reconciler. Talks to NetBox's own REST API
  directly (not through Diode - Diode has no delete/lifecycle concept),
  computing a `discovery_state` (active/stale/review/decommission_candidate/
  mia) for every device from how long it's been since `last_discovered`,
  purely from age - no memory of past runs needed, so a device that gets
  rediscovered heals itself back to `active` automatically. Never deletes
  anything; decommissioning stays a human decision. Runs once daily by
  default (`lifecycle_schedule`).
- **`webapp.py`** - a small FastAPI web UI over all three: filter/promote/
  ignore discovered hosts, edit `rules.yaml` (VLAN policy + per-device
  site/tenant/location overrides) with live validation against the real
  parser, view Lifecycle staleness, and trigger any of the three pipelines
  on demand ("Run Now" buttons), all from a browser instead of
  `kubectl exec`.
  HTTP Basic Auth - see the main repo's README "Logging in" section for
  how to get the password.

**Runs in-cluster now** - a container image (`Dockerfile`), not a plain
venv+cron process on the bare host like earlier in this project. That
changed for a real reason, not just tidiness: Diode's OAuth2 auth path
(both pipelines authenticate to Diode via the official
`netboxlabs-diode-sdk`) only resolves correctly through the same internal,
ClusterIP-only ingress NetBox's own Diode plugin uses - see the main
repo's Battle Log for the full three-plus-one-bug saga behind that.
Exposing that ingress externally just for this one host-based tool would
have meant a new LoadBalancer IP and an untested gRPC-over-external-ingress
path; running this tool inside the cluster instead means it just reuses
the exact address already verified working for NetBox.

## How this gets deployed

`playbooks/sync-tool.yml` creates, in its own namespace
(`config.yaml`'s `netdisco_netbox_sync.namespace`):

- A **standing debug Deployment** (`netdisco-netbox-sync-debug`, 1
  replica, always running) - `kubectl exec -it
  deploy/netdisco-netbox-sync-debug -n <namespace> -- bash` gets you a
  shell with all three pipelines and a real `sqlite3` CLI available
  (`sqlite3 data/observed_assets.db`). The web UI (below) covers most of
  what you'd use this for day to day now; this is still there for anything
  that needs a real shell.
- A **web UI Deployment + LoadBalancer Service**
  (`netdisco-netbox-sync-webui`, 1 replica - required, not just
  convention, since the shared sqlite staging DB is single-writer). Its
  "Run Now" buttons shell out to the same three pipelines as subprocesses
  inside this same pod, using the same PVC and credentials the CronJobs
  get. Static IP via `config.yaml`'s
  `networking.cluster_lan.static_service_ips.netdisco_netbox_sync_ui`,
  same convention as every other pinned service in this platform.
- Three **CronJobs** (`netdisco-netbox-sync-sync` /
  `netdisco-netbox-sync-discover` / `netdisco-netbox-sync-lifecycle`)
  running the same image on the same schedules as before (hourly / every
  6 hours / once daily by default, `config.yaml`'s
  `sync_schedule`/`discover_schedule`/`lifecycle_schedule`).
- A **PVC** mounted at `/app/data` in all of the above, holding both the
  sqlite staging DB and the real `rules.yaml` - edits made from the debug
  pod or the web UI's Config page persist across CronJob runs and pod
  restarts.
- A **ConfigMap + three Secrets** for configuration instead of a
  generated `.env` file - same values, native Kubernetes objects instead.
  The diode-ingest client secret is mirrored from Diode's own generated
  credential; the web UI login (`WEBUI_USER`/`WEBUI_PASSWORD`) and the
  NetBox API token (`NETBOX_TOKEN`, for `lifecycle.py`) each get their own
  Secret - see the main repo's README "Before you run this" for the one
  manual step the NetBox token needs.

The image itself is built and published automatically by
`.github/workflows/build-netdisco-netbox-sync-image.yml` on any push to
this directory - no local Docker install needed, same pattern as
`charts/netbox`'s image. `entrypoint.sh` bootstraps `data/rules.yaml`
from `rules.yaml.example` on first run only (never overwrites an
existing one), replacing the Ansible copy task the host-based install
used to do.

You shouldn't need to hand-edit anything in this directory for a normal
install - `config.yaml`'s `netdisco_netbox_sync` block is the one file
worth reading before you run it. Edit the real `rules.yaml` in place
from inside the debug pod, not `rules.yaml.example` (that's only ever
read once, as the bootstrap source).

## Before running this for real

1. **Your own VLAN policy** - once the debug pod is up, `kubectl exec`
   in and edit `data/rules.yaml` (bootstrapped from `rules.yaml.example`
   on first run): which VLANs are `infrastructure` (auto-promoted),
   `lab`/`corporate` (held for manual review), or `ignore`. The shipped
   example's VLANs (1/10/20) and subnets are illustrative placeholders,
   not real values.
2. **`config.yaml`'s `netdisco_netbox_sync` block** (in the repo root) -
   `default_site` needs a real value for your deployment.
   `netdisco_url`/`diode_target`/`diode_client_secret` are all resolved
   or generated automatically now, nothing to fill in for those.
   `oob_subnet` is optional - set it to this deployment's mgmt/OOB range
   (e.g. `"10.60.80.0/24"`) so `sync.py` can confidently attach each
   infrastructure device's own polling IP to its real named mgmt
   interface instead of a less reliable per-port lookup. Safe to leave
   as `"TBD"`; everything else about the sync still works without it.
3. **A NetBox API token for `lifecycle.py`**, if you want the Lifecycle
   page/CronJob working - the one credential here that can't be
   auto-generated. See the main repo's README "Before you run this" item
   7 for the exact steps. Safe to skip and add later; everything else
   works without it.

## Version pin note

`config.yaml`'s `version_pins` block pins `netdisco`/`netbox`/`diode` to
exact versions specifically because this tool's field mappings
(`transformer.py`, `netdisco_client.py`) were built and verified against
those exact API shapes. Bumping any of those three services without
re-verifying this tool against the new version can silently break the
sync - see each service's own `charts/*/README.md` for the version
constraint itself.
