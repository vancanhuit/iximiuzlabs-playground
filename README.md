# iximiuz Labs Playgrounds

Runbooks and manifests for custom Debian Trixie playgrounds and Kubernetes
clusters on [iximiuz Labs](https://labs.iximiuz.com).

> **Reference environment:** This repository records one tested lab; it is not
> a drop-in configuration for another account or network. Before running the
> commands, review and tailor:
>
> - the GitHub account, package URLs, and
>   `ghcr.io/vancanhuit/debian-rootfs` image path in [`mise.toml`](mise.toml)
>   and the four playground manifests
> - playground and machine names, topology, resources, storage, and the
>   `172.16.0.0/24` playground subnet in the manifests
> - Tailscale enrollment and ACLs, hostnames, SSH user and port, node interface,
>   and node addresses
> - Kubernetes and Cilium versions, Pod and Service CIDRs, and feature settings
>   in [`docs/k0s/k0s.yaml`](docs/k0s/k0s.yaml) and
>   [`docs/k0s/cilium-values.yaml`](docs/k0s/cilium-values.yaml)
>
> Examples below retain the repository owner's values so the tested setup remains
> reproducible. Keep replacements consistent across tasks, manifests, and cluster
> configuration, and publish images under a registry path your environment can
> access.

This repository provides:

- custom `trixie-base` and `trixie-dev` root filesystem images
- single-machine Debian playgrounds for testing those images
- two multi-machine playgrounds that form an eight-node Kubernetes lab over
  Tailscale
- a `k0s` cluster definition with Cilium, Gateway API, Envoy, and Hubble
- Ansible automation for an alternative kubeadm-based setup

## Repository map

| Path | Purpose |
| --- | --- |
| [`base/`](base/) | Minimal Debian Trixie root filesystem image |
| [`dev/`](dev/) | Development image with `zsh`, `mise`, and Neovim/LazyVim |
| [`base.manifest.yaml`](base.manifest.yaml) | Single-node `trixie-base` playground |
| [`dev.manifest.yaml`](dev.manifest.yaml) | Single-node `trixie-dev` playground |
| [`kubernetes-01.manifest.yaml`](kubernetes-01.manifest.yaml) | First Kubernetes playground: one controller and three workers |
| [`kubernetes-02.manifest.yaml`](kubernetes-02.manifest.yaml) | Second Kubernetes playground: two controllers and two workers |
| [`docs/k0s/k0s.yaml`](docs/k0s/k0s.yaml) | Eight-node `k0sctl` cluster definition |
| [`docs/k0s/cilium-values.yaml`](docs/k0s/cilium-values.yaml) | Cilium Helm values for the `k0s` cluster |
| [`docs/k0s/README.md`](docs/k0s/README.md) | Full `k0s` and Cilium runbook |
| [`ansible/README.md`](ansible/README.md) | Ansible and kubeadm runbook |

## 1. Prepare the control host

Required software:

- [Docker](https://docs.docker.com/get-docker/)
- [`mise`](https://mise.jdx.dev/)
- [`labctl`](https://github.com/iximiuz/labctl)
- a GitHub account with permission to publish packages to
  `ghcr.io/vancanhuit`
- the [Tailscale client](https://tailscale.com/download) installed on the control
  host and joined to the same tailnet as the Kubernetes machines

Clone the repository and install the pinned tools:

```bash
git clone https://github.com/vancanhuit/iximiuzlabs-playground.git
cd iximiuzlabs-playground

curl https://mise.run | sh
curl -sf https://labs.iximiuz.com/cli/install.sh | sh

mise install
mise ls --local

labctl auth login
labctl auth whoami
```

`mise.toml` pins Python, `uv`, Ansible, `kubectl`, Cilium CLI, GitHub CLI,
`k0sctl`, and Helm. Docker and `labctl` are installed separately.

Verify access before changing infrastructure:

```bash
docker version
gh auth status
labctl version
tailscale status
```

## 2. Authenticate to the container registry

```bash
gh auth login --scopes write:packages
gh auth status

gh auth token | docker login ghcr.io \
  --username vancanhuit \
  --password-stdin
```

iximiuz Labs pulls root filesystem images anonymously. After the first push,
make the `debian-rootfs` package public:

1. Open [Package settings](https://github.com/users/vancanhuit/packages/container/debian-rootfs/settings).
2. Select **Change visibility** in the Danger Zone.
3. Change visibility to **Public**.

Verify anonymous access:

```bash
docker logout ghcr.io
docker manifest inspect \
  ghcr.io/vancanhuit/debian-rootfs:trixie-base >/dev/null
```

Log in again before the next push.

## 3. Build and publish root filesystem images

### Base image

Build and push:

```bash
mise run docker:build:trixie-base
docker push ghcr.io/vancanhuit/debian-rootfs:trixie-base
```

The base image is a minimal sysadmin environment derived from the upstream
[`100.rootfs-debian-stable`](https://github.com/iximiuz/labs/tree/main/playgrounds/100.rootfs-debian-stable)
pattern.

### Development image

The development image builds on `trixie-base` and uses the authenticated GitHub
token exposed by the `mise` task:

```bash
mise run docker:build:trixie-dev
docker push ghcr.io/vancanhuit/debian-rootfs:trixie-dev
```

Verify both tags:

```bash
docker manifest inspect \
  ghcr.io/vancanhuit/debian-rootfs:trixie-base >/dev/null
docker manifest inspect \
  ghcr.io/vancanhuit/debian-rootfs:trixie-dev >/dev/null
```

## 4. Create the Debian playgrounds

Create each custom playground once:

```bash
labctl playground create debian-trixie-base \
  --base debian-stable \
  --file base.manifest.yaml

labctl playground create debian-trixie-dev \
  --base debian-stable \
  --file dev.manifest.yaml
```

`labctl` returns the generated playground name. Keep that value for update,
start, and remove commands. A started session has a separate run ID used by
status, SSH, and stop commands.

Update an existing playground after changing its manifest or image tag:

```bash
labctl playground update <playground-name> \
  --file base.manifest.yaml
```

Replace the manifest path with `dev.manifest.yaml` for the development
playground.

## 5. Create the Kubernetes playgrounds

The Kubernetes lab spans two iximiuz Labs playgrounds joined through Tailscale:

| Playground | Machines |
| --- | --- |
| `kubernetes-01` | `control-plane-01`, `node-01`, `node-02`, `node-03` |
| `kubernetes-02` | `control-plane-02`, `control-plane-03`, `node-04`, `node-05` |

Create both playgrounds:

```bash
labctl playground create kubernetes-01 \
  --base flexbox \
  --file kubernetes-01.manifest.yaml

labctl playground create kubernetes-02 \
  --base flexbox \
  --file kubernetes-02.manifest.yaml
```

Start one session for each generated playground and complete the Tailscale login
on all eight machines. Every host must be reachable by its Tailscale name and IP
from the control host:

```bash
tailscale status
ssh root@control-plane-01 hostname
ssh root@control-plane-02 hostname
ssh root@control-plane-03 hostname
ssh root@node-01 hostname
```

The manifests install and start `tailscaled`, but joining each machine to the
tailnet still requires the chosen Tailscale authentication workflow.

## 6. Bootstrap Kubernetes

Choose one cluster workflow. Do not run both against the same machines.

> **Recommendation:** Use the `k0s` workflow for this lab. It is the fully
> tested and reproducible path documented in this repository. `k0s` provides
> more deployment flexibility here than the integrated RKE2 stack, while
> `k0sctl` makes the multi-controller setup easier to reproduce than the manual
> kubeadm workflow.

### `k0s` with Cilium

Use the dedicated [`k0s` runbook](docs/k0s/README.md) for:

1. `k0sctl` dry-run and bootstrap
2. multihomed controller API binding through `tailscale0`
3. local kubeconfig installation
4. Gateway API CRD installation
5. Cilium kube-proxy replacement, Envoy, and Hubble
6. cluster and connectivity verification

Quick entry point:

```bash
k0sctl apply --config docs/k0s/k0s.yaml --dry-run
k0sctl apply --config docs/k0s/k0s.yaml
```

Workers remain `NotReady` until Cilium is installed. Continue through the full
runbook before evaluating cluster health.

### Ansible and kubeadm

> **Experimental:** The Ansible roles and kubeadm runbook are not fully tested.
> Treat them as development references, not the supported deployment path for
> this lab.

Use the [Ansible runbook](ansible/README.md) for host preparation and the
alternative kubeadm workflow:

```bash
cd ansible
ansible-playbook k8s.yaml
```

This path also disables kube-proxy and installs Cilium separately.

## 7. Operate playground sessions

Start a playground session:

```bash
labctl playground start <playground-name>
```

The command prints a run ID. Use the run ID, not the playground name, for
session operations:

```bash
labctl playground status <run-id>
labctl ssh <run-id>
labctl ssh <run-id> -- uname -a
labctl playground stop <run-id>
```

Stopping preserves the session. Removing a custom playground is permanent:

```bash
labctl playground remove --force <playground-name>
```

## 8. Inspect and update manifests

There is no formally published schema for every custom playground field. Use a
known playground's live manifest as the reference:

```bash
labctl playground manifest flexbox
labctl playground manifest debian-stable
labctl playground catalog --filter my-custom
```

After editing a manifest, update its generated playground:

```bash
labctl playground update <playground-name> \
  --file <manifest.yaml>
```

## Troubleshooting

### Image pull fails

Confirm the package is public and anonymously accessible:

```bash
docker logout ghcr.io
docker manifest inspect \
  ghcr.io/vancanhuit/debian-rootfs:trixie-base
```

### Playground update uses the wrong target

List custom playgrounds and use the generated playground name returned by
`labctl playground create`:

```bash
labctl playground catalog --filter my-custom
```

### Kubernetes nodes cannot communicate

Check that all machines are online in the same tailnet and that ACLs allow the
required control-plane and Cilium traffic:

```bash
tailscale status
ssh root@control-plane-01 tailscale status
ssh root@node-01 tailscale status
```

See the [`k0s` Tailscale notes](docs/k0s/README.md#tailscale-networking-notes)
for ports, MTU, address stability, API availability, and Gateway listener
caveats.

## References

- [iximiuz Labs custom playgrounds](https://labs.iximiuz.com/docs/custom-playgrounds)
- [iximiuz Labs CLI](https://github.com/iximiuz/labctl)
- [Upstream root filesystem images](https://github.com/iximiuz/labs/tree/main/playgrounds)
- [`k0s` cluster runbook](docs/k0s/README.md)
- [Ansible and kubeadm runbook](ansible/README.md)
