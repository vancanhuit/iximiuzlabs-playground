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
- a `k0s` cluster definition with Cilium, Hubble, and private Tailscale API access

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

`mise.toml` pins Python, `uv`, `kubectl`, Cilium CLI, GitHub CLI, `k0sctl`,
Helm, SOPS, and age. Docker, Tailscale, and `labctl` are installed separately.

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

Start one session for each generated playground.

### Enroll machines in Tailscale

For repeatable lab provisioning, create a reusable Tailscale auth key that
assigns `tag:lab`:

1. Define `tag:lab` and its owners in the tailnet policy.
2. Add network and Tailscale SSH policy rules that allow the control host to
   reach `tag:lab` machines and connect as `root`.
3. Generate a reusable auth key in the Tailscale admin console, assign it
   `tag:lab`, and make it pre-approved when device approval is enabled.

Run this command on each of the eight machines, replacing the quoted placeholder
at execution time:

```bash
sudo tailscale up \
  --auth-key='tskey-auth-REPLACE_ME' \
  --ssh \
  --accept-routes \
  --advertise-tags=tag:lab
```

Reusable auth keys can enroll multiple machines and must be handled as secrets.
Never commit the key or place it in a manifest. The inline form above can expose
the key through shell history or process inspection; prefer a secret manager and
Tailscale's `file:` form when available:

```bash
sudo tailscale up \
  --auth-key=file:/run/secrets/tailscale-auth-key \
  --ssh \
  --accept-routes \
  --advertise-tags=tag:lab
```

`--accept-routes` accepts subnet routes advertised by other tailnet nodes. Omit
it when this lab should not consume those routes. Revoke the reusable auth key
after provisioning if no more lab machines need to join; revocation does not
deauthorize machines already enrolled with it.

Every host must now be reachable by its Tailscale name and IP from the control
host:

```bash
tailscale status
ssh root@control-plane-01 hostname
ssh root@control-plane-02 hostname
ssh root@control-plane-03 hostname
ssh root@node-01 hostname
```

The manifests install and start `tailscaled`; the enrollment command joins each
machine to the tailnet and enables Tailscale SSH.

## 6. Bootstrap Kubernetes with k0s

The k0s workflow is the repository's single supported Kubernetes path. It is
tested end to end across both playgrounds and uses `k0sctl` to reproduce the
multi-controller cluster.

Use the dedicated [`k0s` runbook](docs/k0s/README.md) for:

1. `k0sctl` dry-run and bootstrap
2. multihomed controller API binding through `tailscale0`
3. local kubeconfig installation
4. Cilium kube-proxy replacement and Hubble
5. cluster and connectivity verification
6. private Kubernetes API access through the Tailscale operator

Quick entry point:

```bash
k0sctl apply --config docs/k0s/k0s.yaml --dry-run
k0sctl apply --config docs/k0s/k0s.yaml
```

Workers remain `NotReady` until Cilium is installed. Continue through the full
runbook before evaluating cluster health.

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

See the [`k0s` runbook](docs/k0s/README.md) for tailnet policy, required ports,
MTU, address stability, API availability, connectivity diagnostics, and
recovery procedures.

## References

- [iximiuz Labs custom playgrounds](https://labs.iximiuz.com/docs/custom-playgrounds)
- [iximiuz Labs CLI](https://github.com/iximiuz/labctl)
- [Upstream root filesystem images](https://github.com/iximiuz/labs/tree/main/playgrounds)
- [Tailscale auth keys](https://tailscale.com/docs/features/access-control/auth-keys)
- [Tailscale device tags](https://tailscale.com/docs/features/tags)
- [`tailscale up`](https://tailscale.com/docs/reference/tailscale-cli/up)
- [Tailscale SSH](https://tailscale.com/docs/features/tailscale-ssh)
- [`k0s` cluster runbook](docs/k0s/README.md)
