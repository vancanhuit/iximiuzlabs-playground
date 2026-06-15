# Custom Debian Trixie Rootfs for iximiuz Labs Playgrounds

A minimal Debian **Trixie** (current stable) root filesystem image, built to be used as
a custom [iximiuz Labs](https://labs.iximiuz.com) playground rootfs. It follows the
[official `100.rootfs-debian-stable`](https://github.com/iximiuz/labs/tree/main/playgrounds/100.rootfs-debian-stable)
pattern, stripped down to the essentials needed to boot as a real microVM.

## Contents

| File            | Purpose                                                              |
| --------------- | ------------------------------------------------------------------- |
| `Dockerfile`    | Builds the minimal Debian Trixie rootfs image.                      |
| `manifest.yaml` | iximiuz Labs playground manifest referencing the published image.   |
| `.vimrc`        | Vim config copied into the lab user's home.                         |
| `.tmux.conf`    | tmux config copied into the lab user's home.                        |

## What's in the image

- **Base:** `debian:trixie` (Debian 13, current stable)
- **Boot-as-VM essentials:** `systemd`, `udev`, `kmod`, `dbus`
  (required so the rootfs boots as a real microVM, not just a container)
- **Lab user:** `laborant` (uid 1001), member of `sudo`, passwordless sudo, `bash` shell
- **SSH:** `openssh-server` configured for **publickey-only** auth with an ed25519 host key
- **Tooling:** vim, tmux, git, curl, wget, socat, netcat, htop, tree, ripgrep-free
  sysadmin basics (see `Dockerfile` for the full package list)

> The iximiuz-internal `examiner` service and the various `get-*.sh` tool installers
> from the upstream repo are **not** required for a custom playground and are omitted.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (with BuildKit; the Dockerfile uses
  `# syntax=docker/dockerfile:1` heredocs)
- A container registry account — **`ghcr.io` is required; Docker Hub is not supported**
  by iximiuz Labs due to its rate limiting
- [`labctl`](https://github.com/iximiuz/labctl) — the iximiuz Labs CLI

## 1. Build the image

`LAB_USER` has no default, so it must be supplied:

```bash
docker build \
  --build-arg LAB_USER=laborant \
  -t ghcr.io/vancanhuit/debian-rootfs:trixie-base \
  .
```

To target a different Debian release, edit the `FROM` line in the `Dockerfile`
(e.g. `debian:bookworm` or the floating `debian:stable`).

## 2. Push to ghcr.io

```bash
# Authenticate (needs a token with write:packages scope)
echo "$CR_PAT" | docker login ghcr.io -u vancanhuit --password-stdin

docker push ghcr.io/vancanhuit/debian-rootfs:trixie-base
```

### Make the package public

iximiuz Labs pulls the rootfs **anonymously**, so the package must be public.
GitHub's REST API has no endpoint to change package visibility, so do it in the UI:

> GitHub → your profile → **Packages** → `debian-rootfs` → **Package settings** →
> Danger Zone → **Change visibility** → **Public**

Direct link:
<https://github.com/users/vancanhuit/packages/container/debian-rootfs/settings>

Verify it is anonymously pullable:

```bash
docker logout ghcr.io
docker manifest inspect ghcr.io/vancanhuit/debian-rootfs:trixie-base >/dev/null \
  && echo "public: pullable"
```

## 3. Create the playground

The manifest references the published image via an `oci://` drive source. Custom-rootfs
playgrounds are created on top of the `flexbox` base:

```bash
labctl playground create --base flexbox -f manifest.yaml debian-trixie-base
```

This prints the playground name (e.g. `debian-trixie-base-<suffix>`) and its URL.

## 4. Start, inspect, and tear down

```bash
# Start a session (waits until all machines reach RUNNING)
labctl playground start debian-trixie-base-<suffix> --safety-disclaimer-consent

# Check status (use the run ID printed by start, NOT the playground name)
labctl playground status <run-id>

# SSH into the running VM
labctl ssh <run-id>
# ...or run a one-off command:
labctl ssh <run-id> -- uname -a

# Stop a session (preserves it for restart)
labctl playground stop <run-id>

# Permanently remove the custom playground
labctl playground remove -f debian-trixie-base-<suffix>
```

## 5. Update the playground

Edit `manifest.yaml` (new image tag, resources, tabs, etc.) and apply:

```bash
labctl playground update debian-trixie-base-<suffix> -f manifest.yaml
```

## Manifest reference

There is no formally published schema. The most reliable reference is the live output
of `labctl playground manifest <name>` for any existing playground, e.g.:

```bash
labctl playground manifest flexbox        # base for custom-rootfs playgrounds
labctl playground manifest debian-stable  # official Debian analog
```

`manifest.yaml` in this repo sets:

- a single VM (`debian-01`) with `root` and a default `laborant` user
- the custom rootfs as the `/` drive via `source: oci://ghcr.io/vancanhuit/debian-rootfs:trixie-base`
- a 30 GiB disk, 2 vCPUs, 2 GiB RAM
- one terminal tab
- public access control

## References

- [Custom Playgrounds docs](https://labs.iximiuz.com/docs/playgrounds/custom-playgrounds)
- [Upstream playground rootfs images](https://github.com/iximiuz/labs/tree/main/playgrounds)
- [labctl CLI](https://github.com/iximiuz/labctl)
