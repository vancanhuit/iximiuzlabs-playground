# Custom Debian Trixie Rootfs for iximiuz Labs Playgrounds

Custom Debian **Trixie** (current stable) root filesystem images for
[iximiuz Labs](https://labs.iximiuz.com) playgrounds. This repo builds two images,
both published as tags of `ghcr.io/vancanhuit/debian-rootfs`:

| Tag           | Built from   | Purpose                                                            |
| ------------- | ------------ | ----------------------------------------------------------------- |
| `trixie-base` | `base/Dockerfile` | Minimal sysadmin server (bash). Follows the upstream pattern.     |
| `trixie-dev`  | `dev/Dockerfile` | Development environment (zsh, mise, Neovim/LazyVim) on top of `trixie-base`. |

The base image follows the
[official `100.rootfs-debian-stable`](https://github.com/iximiuz/labs/tree/main/playgrounds/100.rootfs-debian-stable)
pattern, stripped down to the essentials needed to boot as a real microVM.

## Contents

| File                   | Purpose                                                         |
| ---------------------- | -------------------------------------------------------------- |
| `base/Dockerfile`           | Builds the minimal `trixie-base` rootfs image.                 |
| `base/.vimrc`               | Vim config copied into the lab user's home (base image).       |
| `base/.tmux.conf`           | tmux config copied into the lab user's home (base image).      |
| `dev/Dockerfile`       | Builds the `trixie-dev` development image (`FROM` base).        |
| `dev/.zshrc`           | zsh config (mise, starship, atuin, fzf, completion, aliases).  |
| `dev/starship.toml`    | Starship prompt config.                                        |
| `base.manifest.yaml`        | Playground manifest for the base image.                        |
| `dev.manifest.yaml`  | Playground manifest for the dev image.                         |

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- A container registry account — **`ghcr.io` is required; Docker Hub is not supported**
  by iximiuz Labs due to its rate limiting
- [`mise`](https://mise.jdx.dev) — manage tools, environment variables and tasks in one place
- [`labctl`](https://github.com/iximiuz/labctl) — the iximiuz Labs CLI

```sh
git clone https://github.com/vancanhuit/iximiuzlabs-playground.git
cd iximiuzlabs-playground
# Install mise
curl https://mise.run | sh
# Since `labctl` is not available via `mise`, install it separately:
curl -sf https://labs.iximiuz.com/cli/install.sh | sh

# Install the tools defined in `mise.toml`
mise install
```

## The base image (`trixie-base`)

### 1. Build the image

```bash
mise run docker:build:trixie-base
```

To target a different Debian release, edit the `FROM` line in the `Dockerfile`
(e.g. `debian:bookworm` or the floating `debian:stable`).

### 2. Push to ghcr.io

```bash
gh auth login --scopes write:packages
gh auth status
echo $(gh auth token) | docker login ghcr.io -u vancanhuit --password-stdin

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

### 3. Create the playground

```bash
labctl playground create debian-trixie-base --base debian-stable -f base.manifest.yaml
```

This prints the playground name (e.g. `debian-trixie-base-<suffix>`) and its URL.

### 4. Start, inspect, and tear down

```bash
# Start a session (waits until all machines reach RUNNING)
labctl playground start debian-trixie-base-<suffix>

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

### 5. Update the playground

Edit `base.manifest.yaml` (new image tag, resources, tabs, etc.) and apply:

```bash
labctl playground update debian-trixie-base-<suffix> -f base.manifest.yaml
```

### Manifest reference

There is no formally published schema. The most reliable reference is the live output
of `labctl playground manifest <name>` for any existing playground, e.g.:

```bash
labctl playground manifest flexbox        # base for custom-rootfs playgrounds
labctl playground manifest debian-stable  # official Debian analog
```

#### To list your own custom playgrounds:

```bash
labctl playground catalog --filter my-custom
```

## The dev image (`trixie-dev`)

### Build, push, and create/update the dev playground

```bash
mise run docker:build:trixie-dev

# Push (also requires the package to be public; see above)
docker push ghcr.io/vancanhuit/debian-rootfs:trixie-dev

# Create / update the dev playground
labctl playground create debian-trixie-dev --base debian-stable -f dev.manifest.yaml
labctl playground update debian-trixie-dev-<suffix> -f dev.manifest.yaml
```

## References

- [Custom Playgrounds docs](https://labs.iximiuz.com/docs/custom-playgrounds)
- [Upstream playground rootfs images](https://github.com/iximiuz/labs/tree/main/playgrounds)
- [labctl CLI](https://github.com/iximiuz/labctl)
