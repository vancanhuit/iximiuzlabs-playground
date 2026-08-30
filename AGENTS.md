# Repository Instructions

## Scope

- This repository owns Debian rootfs images, iximiuz Labs playground manifests, and the `docs/k0s/` runbook/configuration for one tested eight-node cluster. Values are deliberately environment-specific; do not generalize or replace owner values unless requested.
- Treat `README.md` as the playground/image workflow and `docs/k0s/README.md` as the ordered cluster operations runbook.
- There is no CI pipeline or repository-wide lint/format command. Use the smallest verification below that covers the changed files.

## Local Workflow

- Install the pinned toolchain and Python dependency with `mise install` then `uv sync --locked`.
- Run all updater tests with `uv run --locked python -m unittest scripts/test_update_k0s_tailscale_ips.py -v`.
- Run one test with `uv run --locked python -m unittest scripts.test_update_k0s_tailscale_ips.UpdateFileTests.test_dry_run_does_not_write -v`.
- Build `trixie-base` before `trixie-dev`; the dev Dockerfile inherits the published base image. Use `mise run docker:build:trixie-base` and `mise run docker:build:trixie-dev`. The dev task obtains a GitHub token through `gh auth token` and passes it as a BuildKit secret.
- Finish text/config edits with `git diff --check`. YAML and TOML use two-space indentation; other files default to four spaces per `.editorconfig`.

## Safety Boundaries

- `labctl playground create/update/remove/start/stop`, image pushes, `k0sctl apply`, Helm changes, `kubectl apply/delete`, and tailnet policy or device changes affect real external infrastructure. Do not run them merely to validate a file; confirm the intended target/context first.
- Playground names and session run IDs are different. `labctl playground update/remove` takes the generated playground name; status, SSH, and stop operations take a run ID.
- Only commit encrypted `secrets/lab.sops.yaml`. Edit it with `sops secrets/lab.sops.yaml`; never decrypt credentials into tracked files, command arguments, logs, or responses.
- The direct `tailscale-k0s` kubeconfig context is the recovery path. Preserve it when configuring or testing the Tailscale API proxy context.

## Cluster Invariants

- The Kubernetes lab spans both `kubernetes-01.manifest.yaml` and `kubernetes-02.manifest.yaml`; hostnames must remain aligned with `docs/k0s/k0s.yaml`.
- k0s node traffic uses `tailscale0`; preserve each host's matching `ssh.address` and `privateAddress`, controller addresses in API SANs, and `api.onlyBindToAddress: true`.
- Update live Tailscale addresses with `uv run scripts/update_k0s_tailscale_ips.py --dry-run` before the write command. The updater intentionally requires all configured hosts online and changes only host SSH/private addresses and controller SAN IPs; inspect `git diff -- docs/k0s/k0s.yaml` afterward.
- Keep Pod CIDR `10.244.0.0/16`, Service CIDR `10.96.0.0/12`, Cilium VXLAN over Tailscale, `tailscale0` MTU `1280`, and Cilium MTU `1230` consistent across `docs/k0s/k0s.yaml`, `docs/k0s/cilium-values.yaml`, the runbook, and diagrams. Do not advertise Pod or Service CIDRs through Tailscale.
- Workers are expected to remain `NotReady` between `k0sctl apply` and Cilium installation because k0s uses custom CNI and kube-proxy is disabled.
- Preserve `apiServerProxyConfig.allowImpersonation=true` when installing or upgrading the Tailscale operator; shared API access depends on Tailscale identity plus Kubernetes RBAC.

## Generated And Published Artifacts

- `docs/k0s/architecture/*.architecture.json` are the authoritative diagram sources. Their `.html`, `.svg`, `*.visual-check.json`, and visual-check images are generated/exported companions; update and validate the set together rather than hand-editing only an export.
- Playground manifests reference published `ghcr.io/vancanhuit/debian-rootfs` tags. A local image build does not update a running playground; publishing and `labctl playground update` are separate explicit operations.
