# Runbook: Deploy Debian and Kubernetes playgrounds

**Owner:** Lab operator | **Frequency:** As needed
**Last updated:** 2026-08-30 | **Last run:** 2026-08-30

## Purpose

Use this runbook to publish the Debian Trixie images and deploy their custom [iximiuz Labs playgrounds](https://labs.iximiuz.com). It also prepares the eight Kubernetes hosts for the separate k0s cluster runbook.

Use [`docs/k0s/README.md`](docs/k0s/README.md) after both Kubernetes playgrounds are running and every host is connected to Tailscale. That runbook owns k0s, Cilium, conformance testing, and private Kubernetes API access.

> **Reference environment**: This repository records one tested lab. It is not a drop-in configuration for another account or network. Before running commands, review these values:
>
> - The GitHub account, package URLs, and `ghcr.io/vancanhuit/debian-rootfs` image path in [`mise.toml`](mise.toml) and the four playground manifests
> - Playground and machine names, topology, resources, storage, and local subnets in the manifests
> - Tailscale enrollment and access control lists (ACLs), hostnames, Secure Shell (SSH) settings, interfaces, and node addresses
> - Kubernetes and Cilium versions, Pod and Service Classless Inter-Domain Routing (CIDR) ranges, and settings in [`docs/k0s/k0s.yaml`](docs/k0s/k0s.yaml) and [`docs/k0s/cilium-values.yaml`](docs/k0s/cilium-values.yaml)
>
> The examples retain the repository owner’s values to reproduce the tested setup. Keep replacements consistent across tasks, manifests, and cluster configuration. Publish images under an accessible registry path.

Use these repository components to build the environment:

- custom `trixie-base` and `trixie-dev` root filesystem images
- single-machine Debian playgrounds for testing those images
- two multi-machine playgrounds that form an eight-node Kubernetes lab over Tailscale
- a `k0s` cluster definition with Cilium, Hubble, and private Tailscale application programming interface (API) access

## Repository map

Use this map to locate each image, manifest, and cluster configuration:

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
| [`.sops.yaml`](.sops.yaml) | SOPS rule that selects the age recipient for encrypted secret files |
| [`secrets/lab.sops.yaml`](secrets/lab.sops.yaml) | Versioned ciphertext for credentials used by the lab runbooks |

## Prerequisites

Complete these checks before changing images or playgrounds:

- [ ] Install Docker, `mise`, `labctl`, and the Tailscale client on the control host
- [ ] Join the control host to the Kubernetes machines’ tailnet
- [ ] Authenticate `gh` with permission to publish packages to `ghcr.io/vancanhuit`
- [ ] Authenticate `labctl` to the target iximiuz Labs account
- [ ] Confirm the repository-specific registry paths, machine names, resources, subnets, and cluster ranges
- [ ] Obtain a Tailscale authentication key that can assign `tag:lab` when deploying Kubernetes playgrounds

## Secret management with SOPS and age

This repository uses [SOPS](https://getsops.io/) with [age](https://age-encryption.org/) so encrypted credentials can be versioned beside the configuration that consumes them. SOPS understands the YAML structure and encrypts its values; age controls who can unlock the file. This preserves useful keys and diffs such as `tailscale.oauth.client_id` without committing their plaintext values.

The two tools have separate responsibilities:

| Component | Responsibility |
| --- | --- |
| SOPS | Generates a random data key, encrypts each YAML value with AES-256-GCM, and authenticates the encrypted document with a message authentication code (MAC) |
| age | Encrypts, or wraps, the SOPS data key to the public recipient in [`.sops.yaml`](.sops.yaml) |
| age private identity | Stays outside Git and unwraps the data key when an authorized operator edits or decrypts the file |

This is envelope encryption. The public recipient beginning with `age1` is safe to commit and lets anyone encrypt a new data key for that recipient. It cannot decrypt the existing file. The corresponding private identity beginning with `AGE-SECRET-KEY-` grants decryption access and must be distributed through an approved secret-sharing channel, stored outside the repository, and protected like the credentials it unlocks.

[![SOPS and age envelope-encryption workflow](docs/k0s/architecture/sops-age.svg)](docs/k0s/architecture/sops-age.svg)

Open the [interactive SOPS and age workflow](docs/k0s/architecture/sops-age.html) to inspect the encryption, storage, and point-of-use boundaries.

### Configure access

Install the pinned versions with `mise install`. Obtain the existing repository age private identity from the repository owner; generating a new identity does not grant access to ciphertext encrypted for the current recipient.

SOPS checks its standard age identity locations and `SOPS_AGE_KEY_FILE`. If the identity is stored at a non-default path, point SOPS to it without putting the key itself in the shell command:

```bash
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"
chmod 600 "$SOPS_AGE_KEY_FILE"

age-keygen -y "$SOPS_AGE_KEY_FILE"
sops decrypt secrets/lab.sops.yaml >/dev/null
```

The first command prints the public recipient derived from the private identity. It must match the recipient in [`.sops.yaml`](.sops.yaml). The decrypt check should exit successfully without printing plaintext to the terminal.

### Edit and consume secrets

Edit the encrypted file through SOPS so plaintext is held in the editor buffer and the saved file remains encrypted:

```bash
sops secrets/lab.sops.yaml
```

Decrypt only the field needed by the next process and prefer a pipe:

```bash
sops decrypt --extract '["tailscale"]["auth_key"]' \
  secrets/lab.sops.yaml | consuming_command
```

When a consumer requires a file, create a private temporary directory, set `umask 077`, and remove it with a shell trap. The k0s runbook demonstrates this pattern for the Tailscale operator OAuth credentials. Do not place plaintext secrets in command arguments, shell history, traced shell output, logs, manifests, Git files, or documentation.

Before committing, inspect the diff and confirm every secret value still begins with `ENC[` and the document retains its `sops` metadata. Commit only `secrets/lab.sops.yaml`, never a decrypted copy.

### Rotate repository access

Changing a credential value and changing who can decrypt the file are different operations. Edit the encrypted YAML to rotate a service credential. To rotate repository decryption access, securely create or obtain the replacement age identity, change the recipient in `.sops.yaml`, and rewrap the existing data key:

```bash
sops updatekeys secrets/lab.sops.yaml
```

Review the encrypted diff before committing, verify that an intended replacement identity can decrypt it, and verify that a removed identity no longer can. Do not remove the old identity until the updated ciphertext is committed and recovery access is confirmed.

## Procedure

Follow the steps in order for a new deployment. For an image or manifest update, start at the relevant build or update step.

### Step 1: Prepare the control host

Install the local tools and verify access before changing infrastructure.

Required software:

- [Docker](https://docs.docker.com/get-docker/)
- [`mise`](https://mise.jdx.dev/)
- [`labctl`](https://github.com/iximiuz/labctl)
- A GitHub account with permission to publish packages to `ghcr.io/vancanhuit`
- The [Tailscale client](https://tailscale.com/download) on the control host and connected to the Kubernetes machines’ tailnet

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

`mise.toml` pins Python, `uv`, `kubectl`, the Cilium command-line interface (CLI), the GitHub CLI, `k0sctl`, Helm, SOPS, and age. Install Docker, Tailscale, and `labctl` separately.

Verify access before changing infrastructure:

```bash
docker version
gh auth status
labctl version
tailscale status
```

**Expected result:** Every version and authentication command exits successfully. `tailscale status` shows the control host in the target tailnet.

**If it fails:** Resolve the missing tool, expired login, or tailnet connection before publishing an image or creating a playground.

### Step 2: Authenticate to the container registry

Authenticate Docker with a GitHub token that can publish packages.

```bash
gh auth login --scopes write:packages
gh auth status

gh auth token | docker login ghcr.io \
  --username vancanhuit \
  --password-stdin
```

iximiuz Labs pulls root filesystem images anonymously. After the first push, make the `debian-rootfs` package public:

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

**Expected result:** Docker authenticates to `ghcr.io`, and anonymous manifest inspection succeeds after the package becomes public.

**If it fails:** Confirm the GitHub account has `write:packages`, repeat `gh auth login`, and verify package visibility before continuing.

### Step 3: Build and publish root filesystem images

Build and publish the base image before the development image.

### Base image

Build and push:

```bash
mise run docker:build:trixie-base
docker push ghcr.io/vancanhuit/debian-rootfs:trixie-base
```

The base image extends the upstream [`100.rootfs-debian-stable`](https://github.com/iximiuz/labs/tree/main/playgrounds/100.rootfs-debian-stable) pattern with a minimal system administration environment.

### Development image

The development image builds on `trixie-base`. The `mise` task exposes the authenticated GitHub token to BuildKit:

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

**Expected result:** Both builds and pushes succeed. `docker manifest inspect` resolves both published tags without registry credentials.

**If it fails:** Build `trixie-base` first. Confirm Docker BuildKit can read the GitHub token secret, then inspect the failing build stage or registry response.

### Step 4: Create or update the Debian playgrounds

Create one single-machine playground for each published image.

Create each custom playground once:

```bash
labctl playground create debian-trixie-base \
  --base debian-stable \
  --file base.manifest.yaml

labctl playground create debian-trixie-dev \
  --base debian-stable \
  --file dev.manifest.yaml
```

`labctl` returns the generated playground name. Keep it for update and remove commands. A started session has a separate run identifier (ID) for status, SSH, and stop commands.

Update an existing playground after changing its manifest or image tag:

```bash
labctl playground update playground_name \
  --file base.manifest.yaml
```

Replace the manifest path with `dev.manifest.yaml` for the development playground.

**Expected result:** `labctl` returns a generated playground name for each manifest. An updated playground retains that generated name.

**If it fails:** Inspect the current base manifest with `labctl playground manifest debian-stable`. Confirm the published image is public and the manifest references the intended tag.

### Step 5: Create the Kubernetes playgrounds

Create both multi-machine playgrounds before enrolling their eight hosts in Tailscale.

Tailscale connects the hosts in two iximiuz Labs playgrounds:

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

For repeatable lab provisioning, create a reusable Tailscale authentication key that assigns `tag:lab`:

1. Define `tag:lab` and its owners in the tailnet policy.
2. Add network and Tailscale SSH policy rules that let the control host reach `tag:lab` machines as `root`.
3. Generate a reusable authentication key in the Tailscale admin console. Assign `tag:lab`. Preapprove the key if your tailnet requires device approval.

Store the key in `/run/secrets/tailscale-auth-key` with mode `600`. Then run this command on each machine:

```bash
sudo tailscale up \
  --auth-key=file:/run/secrets/tailscale-auth-key \
  --ssh \
  --accept-routes \
  --advertise-tags=tag:lab
```

Reusable authentication keys can enroll multiple machines, so handle them as secrets. Never commit the key or add it to a manifest. Remove the temporary key file after enrollment.

`--accept-routes` accepts subnet routes that other tailnet nodes advertise. Omit it when this lab shouldn’t consume those routes. Revoke the key after provisioning the final machine. Revocation doesn’t deauthorize enrolled machines.

Verify that every host responds through its Tailscale name and Internet Protocol (IP) address:

```bash
tailscale status
ssh root@control-plane-01 hostname
ssh root@control-plane-02 hostname
ssh root@control-plane-03 hostname
ssh root@node-01 hostname
```

The manifests install and start `tailscaled`. The enrollment command connects each machine to the tailnet and enables Tailscale SSH.

**Expected result:** Both playground sessions run, and all eight unique hostnames respond through Tailscale and SSH.

**If it fails:** Stop before running k0s. Check the authentication key, tag ownership, device approval, duplicate hostnames, and tailnet ACLs.

### Step 6: Hand off to the k0s runbook

Follow the dedicated runbook to bootstrap and verify the supported Kubernetes configuration.

The k0s workflow is the repository’s supported Kubernetes path. The tested workflow uses `k0sctl` across both playgrounds to reproduce the multi-controller cluster.

Use the dedicated [`k0s` runbook](docs/k0s/README.md) for:

1. `k0sctl` dry-run and bootstrap
2. multihomed controller API binding through `tailscale0`
3. local kubeconfig installation
4. Cilium kube-proxy replacement and Hubble
5. cluster and connectivity verification
6. private Kubernetes API access through the Tailscale operator

Preview the k0s changes, then apply them:

```bash
k0sctl apply --config docs/k0s/k0s.yaml --dry-run
k0sctl apply --config docs/k0s/k0s.yaml
```

Workers remain `NotReady` until you install Cilium. Complete the runbook before evaluating cluster health.

**Expected result:** The k0s dry run shows only the intended cluster changes. The complete k0s runbook ends with healthy cluster and API checks.

**If it fails:** Follow the failure action in the corresponding k0s runbook step. Preserve the direct `tailscale-k0s` recovery context.

### Step 7: Operate playground sessions

Use the generated playground name to start a session, then use its run ID for session operations.

Start a playground session:

```bash
labctl playground start playground_name
```

The command prints a run ID. Use that ID, not the playground name, for session operations:

```bash
labctl playground status run_id
labctl ssh run_id
labctl ssh run_id -- uname -a
labctl playground stop run_id
```

Stopping preserves the session. The following command permanently removes a custom playground:

```bash
labctl playground remove --force playground_name
```

**Expected result:** Status and SSH commands address a run ID. Stop preserves session state; remove deletes the generated custom playground.

**If it fails:** List custom playgrounds to distinguish their generated names from session run IDs. Retry with the identifier required by the command.

### Step 8: Inspect and update manifests

Inspect a live base manifest before using an undocumented custom playground field.

iximiuz Labs doesn’t publish a schema for every custom playground field. Use a known playground’s live manifest as the reference:

```bash
labctl playground manifest flexbox
labctl playground manifest debian-stable
labctl playground catalog --filter my-custom
```

After editing a manifest, update its generated playground:

```bash
labctl playground update playground_name \
  --file manifest_path
```

**Expected result:** `labctl` accepts the manifest and updates the intended generated playground.

**If it fails:** Compare the edited field with the live base manifest. Confirm the command targets the generated playground name, not a run ID.

## Verification

Complete the checks that match the deployed playgrounds:

- [ ] `docker manifest inspect` resolves every published image tag without registry credentials
- [ ] `labctl playground catalog --filter my-custom` lists each generated custom playground
- [ ] Every started session reports a healthy status when addressed by its run ID
- [ ] SSH commands reach the expected machine and report its configured hostname
- [ ] Every Kubernetes host appears online in `tailscale status` with a unique hostname and IP address
- [ ] The k0s runbook verification passes when this deployment includes the Kubernetes cluster

## Troubleshoot playground operations

Use the observed failure to select the narrowest diagnostic command.

### Image pull fails

Confirm the package is public and anonymously accessible:

```bash
docker logout ghcr.io
docker manifest inspect \
  ghcr.io/vancanhuit/debian-rootfs:trixie-base
```

### Playground update uses the wrong target

List custom playgrounds and use the generated name from `labctl playground create`:

```bash
labctl playground catalog --filter my-custom
```

### Kubernetes nodes cannot communicate

Confirm that every machine is online in the same tailnet. Check that ACLs allow the required control-plane and Cilium traffic:

```bash
tailscale status
ssh root@control-plane-01 tailscale status
ssh root@node-01 tailscale status
```

See the [`k0s` runbook](docs/k0s/README.md) for tailnet policy, required ports, maximum transmission unit (MTU), address stability, API availability, diagnostics, and recovery procedures.

## Rollback

Stop a faulty session by its run ID to preserve its disks for diagnosis:

```bash
labctl playground stop run_id
```

For a faulty manifest update, correct the tracked manifest and apply it to the same generated playground name. An image tag in a running playground doesn’t change until you update the playground and start a new session.

To restore a previous image, publish the known-good content under a new immutable tag. Update the manifest and start a new session. Don’t overwrite a tag while another session may depend on it.

Remove a custom playground only after preserving required session data and recording its generated name:

```bash
labctl playground remove --force playground_name
```

For Kubernetes rollback and teardown, follow [`docs/k0s/README.md`](docs/k0s/README.md). Don’t destroy cluster playgrounds before exporting workload data and backing up etcd.

## Escalation

Use the failing system to choose the escalation path:

| Situation | Contact | Method |
| --- | --- | --- |
| Registry authentication, package publication, or image access failure | Repository owner | Repository issue tracker |
| Playground provisioning, manifest acceptance, or platform network failure | iximiuz Labs support | [iximiuz Labs documentation](https://labs.iximiuz.com/docs) |
| Tailnet enrollment, ACL, or device approval failure | Tailnet owner | Organization-approved operations channel |
| k0s, Cilium, or etcd failure after playground deployment | Kubernetes platform owner | Organization-approved incident channel |

## History

Record each image publication, playground deployment, update, or removal:

| Date | Run by | Notes |
| --- | --- | --- |
| 2026-08-30 | Not recorded | Converted the deployment guide into an operational runbook |
| 2026-08-30 | Repository owner and OpenCode | Recreated Kubernetes runs `6a93971d8bf0b87423a618b4` and `6a93971c156818a291cad1ef` from the updated playground definitions |
| 2026-08-30 | Repository owner and OpenCode | Rebuilt and published both root filesystem images, updated all four playground definitions, verified Debian runs `6a93a6e48bf0b87423a9f221` and `6a93a6e48bf0b87423a9f22f`, and revalidated the persistent Kubernetes cluster |

## Playground and cluster references

Use these sources to verify the external tools and procedures in this guide:

- [iximiuz Labs custom playgrounds](https://labs.iximiuz.com/docs/custom-playgrounds)
- [iximiuz Labs CLI](https://github.com/iximiuz/labctl)
- [Upstream root filesystem images](https://github.com/iximiuz/labs/tree/main/playgrounds)
- [Tailscale auth keys](https://tailscale.com/docs/features/access-control/auth-keys)
- [Tailscale device tags](https://tailscale.com/docs/features/tags)
- [`tailscale up`](https://tailscale.com/docs/reference/tailscale-cli/up)
- [Tailscale SSH](https://tailscale.com/docs/features/tailscale-ssh)
- [`k0s` cluster runbook](docs/k0s/README.md)
