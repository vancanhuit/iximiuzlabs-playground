# Custom Debian Trixie Rootfs for iximiuz Labs Playgrounds

Custom Debian **Trixie** (current stable) root filesystem images for
[iximiuz Labs](https://labs.iximiuz.com) playgrounds. This repo builds two images,
both published as tags of `ghcr.io/vancanhuit/debian-rootfs`:

| Tag           | Built from   | Purpose                                                            |
| ------------- | ------------ | ----------------------------------------------------------------- |
| `trixie-base` | `Dockerfile` | Minimal sysadmin server (bash). Follows the upstream pattern.     |
| `trixie-dev`  | `dev/Dockerfile` | Development environment (zsh, mise, Neovim/LazyVim) on top of `trixie-base`. |

The base image follows the
[official `100.rootfs-debian-stable`](https://github.com/iximiuz/labs/tree/main/playgrounds/100.rootfs-debian-stable)
pattern, stripped down to the essentials needed to boot as a real microVM.

## Contents

| File                   | Purpose                                                         |
| ---------------------- | -------------------------------------------------------------- |
| `Dockerfile`           | Builds the minimal `trixie-base` rootfs image.                 |
| `manifest.yaml`        | Playground manifest for the base image.                        |
| `.vimrc`               | Vim config copied into the lab user's home (base image).       |
| `.tmux.conf`           | tmux config copied into the lab user's home (base image).      |
| `dev/Dockerfile`       | Builds the `trixie-dev` development image (`FROM` base).        |
| `dev/.zshrc`           | zsh config (mise, starship, atuin, fzf, completion, aliases).  |
| `dev/starship.toml`    | Starship prompt config.                                        |
| `dev.playground.yaml`  | Playground manifest for the dev image.                         |

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

## The base image (`trixie-base`)

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
- a 30 GiB disk, 2 vCPUs, 4 GiB RAM
- one terminal tab
- public access control

To list your own custom playgrounds:

```bash
labctl playground catalog --filter my-custom
```

> **SSH note:** `labctl ssh <run-id>` works from an interactive terminal. The
> non-interactive form `labctl ssh <run-id> -- <cmd>` needs a TTY and will appear
> to hang when run without one (e.g. in scripts/CI); use the browser terminal or an
> interactive shell instead.

## The dev image (`trixie-dev`)

Built from `dev/Dockerfile` (`FROM ghcr.io/vancanhuit/debian-rootfs:trixie-base`). On
top of the base it adds:

- **Shell:** `zsh` as the lab user's default shell, plus `build-essential`
- **Tool manager:** [`mise`](https://mise.jdx.dev) installed for the lab user, used to
  install: starship, ripgrep, fd, lazygit, neovim, ast-grep, tree-sitter, fzf, bat,
  shellcheck, shfmt, python (3.14.6), uv, ruff, delta, node (lts), atuin, eza
- **Neovim providers:** `pynvim` via `uv tool install` (Neovim auto-detects the
  `pynvim-python` shim on `PATH`) and the `neovim` npm package
- **Editor config:** [LazyVim starter](https://github.com/LazyVim/starter) at `~/.config/nvim`
- **Dotfiles:** `dev/.zshrc` and `dev/starship.toml`
- **Git config:** sensible global defaults via `git config --global` (delta pager,
  `init.defaultBranch=main`, rebase-on-pull, etc.); user name/email are intentionally
  left unset

### Build, push, and run the dev image

```bash
# Build (from the dev/ directory)
docker build --build-arg LAB_USER=laborant \
  -t ghcr.io/vancanhuit/debian-rootfs:trixie-dev dev/

# Optional: pass a GitHub token to avoid API rate limits while mise downloads tools.
# The secret mount is optional — a plain build works without it.
# Read the token straight from the gh CLI:
GITHUB_TOKEN="$(gh auth token)" docker build --build-arg LAB_USER=laborant \
  --secret id=github_token,env=GITHUB_TOKEN \
  -t ghcr.io/vancanhuit/debian-rootfs:trixie-dev dev/

# Push (also requires the package to be public; see above)
docker push ghcr.io/vancanhuit/debian-rootfs:trixie-dev

# Create / update the dev playground
labctl playground create --base flexbox -f dev.playground.yaml debian-trixie-dev
labctl playground update debian-trixie-dev-<suffix> -f dev.playground.yaml
```

`dev.playground.yaml` uses the `trixie-dev` drive with a 50 GiB disk, 4 vCPUs, and
10 GiB RAM.

## References

- [Custom Playgrounds docs](https://labs.iximiuz.com/docs/playgrounds/custom-playgrounds)
- [Upstream playground rootfs images](https://github.com/iximiuz/labs/tree/main/playgrounds)
- [labctl CLI](https://github.com/iximiuz/labctl)
