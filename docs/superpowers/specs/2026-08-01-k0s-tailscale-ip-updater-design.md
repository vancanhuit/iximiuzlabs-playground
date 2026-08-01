# k0s Tailscale IP Updater Design

## Goal

Provide a small Python utility that discovers the current Tailscale IPv4
address of every host in the k0s cluster definition and updates the operational
YAML before bootstrap. Project-level `uv` metadata and a lockfile provide the
Python environment and YAML dependency.

## Scope

Keep `scripts/update_k0s_tailscale_ips.py` and its focused test together under
`scripts/`. The script updates only `docs/k0s/k0s.yaml`; IP addresses shown in
`docs/k0s/README.md` remain deployment examples. The runbook documents
environment setup, discovery, dry-run, update, and subsequent k0sctl validation
commands.

## Python Environment

Declare Python and `ruamel.yaml` in a non-package `pyproject.toml` and commit the
generated `uv.lock`. Running `uv sync` creates or updates the repository-local
`.venv`; `.gitignore` excludes that environment and Python bytecode caches.

The updater has no PEP 723 inline dependency block. `uv run` resolves the
locked project environment when running the updater or its tests.

## Discovery and Validation

The script runs `tailscale status --json` once on the control host. It combines
the local node and peers, then matches each configured k0s hostname to an online
Tailscale node. Each configured host must resolve to exactly one unique IPv4
address in Tailscale's `100.64.0.0/10` range.

Discovery is all-or-nothing. A missing, offline, duplicated, malformed, or
reused node address causes a clear error before the configuration is modified.
The subprocess uses an argument list rather than a shell and has a finite
timeout.

## YAML Update

Use `ruamel.yaml` in round-trip mode so key ordering, indentation, and quoting
remain stable. For every configured host, update:

- `privateAddress`
- `ssh.address`

For controllers, replace each existing private IP entry in
`spec.k0s.config.spec.api.sans` with the newly discovered address. Preserve
hostname SANs and unrelated SAN entries. Refuse to write if the expected old
controller SAN entries are absent or ambiguous.

After all validation and in-memory updates succeed, write through a temporary
file and atomically replace the target. Preserve the target file mode. A
`--dry-run` option prints the planned hostname and address changes without
writing. `--config` accepts an alternate k0sctl configuration path for testing
or non-default layouts.

## Testing

The focused test at `scripts/test_update_k0s_tailscale_ips.py` uses temporary
YAML files and fixture Tailscale status data, so it does not require a live
tailnet. It covers:

- updating all host address fields and controller SANs
- preserving non-address SANs and YAML structure
- dry-run leaving the file unchanged
- rejecting missing, offline, duplicate, invalid, and reused node addresses
- leaving the file unchanged after any validation failure

## Runbook

The k0s runbook instructs users to run:

```bash
uv sync --locked
uv run --locked python -m unittest scripts/test_update_k0s_tailscale_ips.py -v
uv run --locked scripts/update_k0s_tailscale_ips.py --dry-run
uv run --locked scripts/update_k0s_tailscale_ips.py
k0sctl apply --config docs/k0s/k0s.yaml --dry-run
```

It states that the control host must be connected to the target tailnet and
that all configured node hostnames must appear online in `tailscale status`.

## Sources

- https://docs.astral.sh/uv/concepts/projects/layout/
- https://docs.astral.sh/uv/concepts/projects/sync/
- https://tailscale.com/kb/1080/cli#status
- https://yaml.dev/doc/ruamel.yaml/
