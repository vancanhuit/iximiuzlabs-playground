# Runbook: Deploy the Incus cluster playground

**Owner:** Lab operator | **Frequency:** As needed
**Last updated:** 2026-09-05 | **Last run:** 2026-09-05

## Purpose

Use this runbook to deploy and verify the repository's three-node Incus cluster on iximiuz Labs. The tested configuration provides:

- Incus 7.0 LTS packages from [Zabbly](https://github.com/zabbly/incus)
- containers only through the `incus-base` package
- three Incus database members and three OVN database members
- `eth0` for Incus clustering and OVN Geneve traffic
- unnumbered `eth1` interfaces on a shared layer 2 network for the OVN uplink
- one member-local Btrfs pool backed by `/dev/vdb` on each host
- Tailscale SSH for Ansible and private Incus API access

The Btrfs pool is local storage. Incus can move instances between members, but their data is not synchronously replicated as it would be with shared storage such as Ceph.

## Files

| Path | Purpose |
| --- | --- |
| [`incus-cluster.manifest.yaml`](../../incus-cluster.manifest.yaml) | Three machines, two networks, dedicated data disks, and package installation |
| [`ansible/inventory.ini`](../../ansible/inventory.ini) | Logical hostnames and Tailscale SSH transport |
| [`ansible/tailscale.yml`](../../ansible/tailscale.yml) | Bootstrap enrollment through `labctl ssh` |
| [`ansible/incus_cluster.yml`](../../ansible/incus_cluster.yml) | Incus, Btrfs, OVN, uplink, and API configuration |
| [`secrets/lab.sops.yaml`](../../secrets/lab.sops.yaml) | Encrypted Tailscale API token |

## Prerequisites

- [ ] Install the pinned tools with `mise install`.
- [ ] Authenticate `labctl` to the intended iximiuz Labs account.
- [ ] Connect the control host to the intended Tailscale tailnet.
- [ ] Configure `SOPS_AGE_KEY_FILE` if the age identity is not in its default location.
- [ ] Confirm `sops decrypt secrets/lab.sops.yaml >/dev/null` succeeds.
- [ ] Ensure the tailnet policy permits the operator to assign `tag:lab` and reach tagged nodes.
- [ ] Ensure the Tailscale SSH policy permits the operator to connect to `tag:lab` as `root`.
- [ ] Confirm `/dev/vdb` may be erased on all three new machines.

The repository's example policy is [`docs/k0s/tailnet-policy.hujson`](../k0s/tailnet-policy.hujson). Replace its `tailscale_login` placeholder before applying it. Tailscale SSH `check` mode is supported, but an operator must complete its browser reauthentication before running the cluster playbook.

## Network And Storage Invariants

The playbook discovers addresses at runtime rather than storing them in inventory:

| Resource | Use |
| --- | --- |
| `eth0` | Incus cluster endpoint, OVN northbound/southbound databases, and Geneve encapsulation |
| `eth1` | OVN physical uplink; Ansible removes its host addresses before creating `ovn0` |
| `tailscale0` | Tailscale SSH and client access to the Incus API |
| `/dev/vdb` | Dedicated Btrfs storage for the local Incus pool |

The playbook persists the discovered `eth1` subnet metadata in `/etc/incus/uplink.json` before removing the interface address. This makes later runs idempotent. Do not delete that file unless `eth1` has its original playground address again.

Incus cluster traffic uses `cluster.https_address` on `eth0`. Incus has one HTTPS listener for both cluster and client traffic, so `core.https_address` listens on `0.0.0.0:8443`; management clients must use a Tailscale address or MagicDNS name, and tailnet policy remains the management access boundary.

## Procedure

### Step 1: Validate Local Configuration

```bash
mise install
mise exec -- ansible-lint \
  ansible/tailscale.yml \
  ansible/incus_cluster.yml
mise exec -- ansible-playbook \
  -i ansible/inventory.ini \
  ansible/tailscale.yml --syntax-check
mise exec -- ansible-playbook \
  -i ansible/inventory.ini \
  ansible/incus_cluster.yml --syntax-check
git diff --check
```

**Expected result:** Both playbooks pass the production lint profile and both syntax checks succeed.

**If it fails:** Run `mise install` again, then fix the reported file before changing the live playground.

### Step 2: Update The Custom Playground

The update changes future runs; it does not mutate an existing run.

```bash
labctl playground update incus-cluster-e6fb1c6c \
  --file incus-cluster.manifest.yaml \
  --force
```

**Expected result:** `labctl` returns `incus-cluster-e6fb1c6c` and its playground URL.

**If it fails:** Inspect `labctl playground manifest flexbox` and compare unsupported fields with the base manifest. Task keys and task names must contain only alphanumeric characters or underscores.

### Step 3: Remove Stale Tailscale Devices

Before recreating a run, inspect the Tailscale admin console for offline devices named `incus-01`, `incus-02`, and `incus-03`. Remove only devices confirmed to belong to a destroyed run. Duplicate records cause suffixed MagicDNS names such as `incus-01-1` and make the static Ansible inventory ambiguous.

Do not remove a live or unrelated node merely to reclaim a hostname.

**Expected result:** No existing Tailscale device owns any of the three names.

**If it fails:** Stop and identify the old run before deleting records. If it is still needed, use different machine names consistently in the manifest and inventory instead.

### Step 4: Start A Fresh Run

```bash
labctl playground start incus-cluster-e6fb1c6c
```

Record the returned run ID and wait for `install_incus_01`, `install_incus_02`, and `install_incus_03` to complete. The init tasks install Zabbly Incus, Btrfs tools, OVN, Open vSwitch, and Tailscale, but do not enroll Tailscale or initialize Incus.

**Expected result:** The run has three machines and all installation tasks complete successfully.

**If it fails:** Inspect the run in the browser or use `labctl playground status run_id`. Do not run either playbook until all init tasks complete.

### Step 5: Enroll Tailscale Through Labctl

```bash
mise exec -- ansible-playbook \
  -i ansible/inventory.ini \
  ansible/tailscale.yml \
  -e incus_play_id=playground_run_id
```

The playbook:

1. reaches each new machine through `labctl ssh`
2. decrypts only `tailscale.access_token` from the SOPS file
3. creates a reusable, preauthorized one-hour key for `tag:lab`
4. copies it through protected temporary files
5. enrolls all three machines and enables Tailscale SSH
6. removes every temporary key file and revokes the API-created key
7. verifies SSH through `tailscale nc`

**Expected result:** The play recap has no failures and `tailscale status` lists exactly one online device for each Incus hostname.

**If it fails:** The `always` block still attempts to delete local and remote key files and revoke the key. Check the Tailscale key list and revoke any remaining key manually before retrying. Remove partial offline device records before starting a replacement run.

### Step 6: Authorize Tailscale SSH Check Mode

If the policy uses `action: "check"`, the final task might print an authentication URL. Open it and complete authentication once, then confirm access:

```bash
ssh -o 'ProxyCommand=tailscale nc %h %p' root@incus-01 true
ssh -o 'ProxyCommand=tailscale nc %h %p' root@incus-02 true
ssh -o 'ProxyCommand=tailscale nc %h %p' root@incus-03 true
```

Do not set `checkPeriod` to `always` for these hosts because Ansible opens multiple SSH connections. A finite check period preserves reauthentication without blocking the run.

**Expected result:** All three commands exit without prompting after authorization.

**If it fails:** Confirm both a network grant and an SSH rule permit the operator to reach `tag:lab`, and confirm each host was enrolled with `tailscale up --ssh`.

### Step 7: Build The Incus Cluster

Warning: on a fresh run, this command permanently formats `/dev/vdb` on every member.

```bash
mise exec -- ansible-playbook \
  -i ansible/inventory.ini \
  ansible/incus_cluster.yml
```

The playbook validates the disks and interfaces, builds the three-member OVN database, forms the Incus cluster, initializes the local Btrfs pools, detaches host addresses from `eth1`, creates `UPLINK` and `ovn0`, updates the default profile, and verifies cluster and network state.

**Expected result:** All plays complete without failures. The first run reports changes; later runs should be mostly `ok` or `skipped`.

**If it fails:** Fix the reported stage and rerun the same playbook. It is designed to resume after successful cluster joins, Btrfs initialization, or network creation. Never manually format `/dev/vdb` to bypass the safety assertion.

## Verification

Run control-plane checks through Tailscale SSH:

```bash
ssh -o 'ProxyCommand=tailscale nc %h %p' root@incus-01 \
  'incus cluster list; incus storage list; incus network list'
```

Confirm:

- [ ] `incus-01`, `incus-02`, and `incus-03` are `ONLINE`.
- [ ] `local` uses the `btrfs` driver and is `CREATED`.
- [ ] `UPLINK` is a `physical` network in `CREATED` state.
- [ ] `ovn0` is an `ovn` network in `CREATED` state.
- [ ] `eth1` is up but has no host IPv4 or IPv6 address on every member.
- [ ] `incus config get core.https_address` returns `0.0.0.0:8443`.

Run a disposable workload test:

```bash
ssh -o 'ProxyCommand=tailscale nc %h %p' root@incus-01 \
  'incus launch images:debian/13 test-ovn --network ovn0'
ssh -o 'ProxyCommand=tailscale nc %h %p' root@incus-01 \
  'incus exec test-ovn -- ping -c 3 1.1.1.1'
ssh -o 'ProxyCommand=tailscale nc %h %p' root@incus-01 \
  'incus delete --force test-ovn'
```

**Expected result:** The container receives an address on `ovn0`, reaches the internet, and is removed afterward.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `Module zfs not found` | The default Firecracker kernel does not provide ZFS | Use the supported Btrfs configuration; do not add DKMS or a custom kernel unless ZFS is explicitly required |
| `database connection failed` from `ovs-vsctl` | `openvswitch-switch` is not running | Start and enable `openvswitch-switch`, then rerun `ansible/incus_cluster.yml` |
| Join preseed reports a YAML scanner error | Human-readable text was included with the token | Keep `incus cluster add --quiet` in the playbook and create a fresh token |
| `Network is not in pending state` | A prior run already finalized `UPLINK` | Inspect `incus network show UPLINK`; rerun the current idempotent playbook instead of recreating targets |
| `ipv6.gateway` rejects `none` | Physical uplinks do not accept that value | Omit `ipv6.gateway`; this runbook configures only the IPv4 uplink |
| OVN says `eth1` has addresses | systemd-networkd still owns the uplink address | Confirm `/etc/systemd/network/20-eth1.network` is unmanaged, flush `eth1`, and rerun the playbook |
| Members become `OFFLINE` after API configuration | `core.https_address` was bound only to Tailscale | Restore `incus config set core.https_address=0.0.0.0:8443` locally on every member |
| MagicDNS resolves to a suffixed name | A stale Tailscale device owns the canonical hostname | Remove only the confirmed stale record, then reenroll the replacement node |
| Ansible waits at SSH authentication | Tailscale SSH check mode requires reauthentication | Open the printed URL once; do not use `checkPeriod: always` with Ansible |

## Rollback And Teardown

Stop a run when its state might still be needed:

```bash
labctl playground stop playground_run_id
```

Permanently destroy a disposable run only after confirming no Incus instance or volume data is required. Then remove its three stale Tailscale device records before starting another run:

```bash
labctl playground destroy --force playground_run_id
```

The custom playground definition is separate from a run. To roll back its configuration, restore the prior tracked manifest and update `incus-cluster-e6fb1c6c`; do not remove the custom playground unless it is no longer needed.

## Escalation

| Situation | Contact | Method |
| --- | --- | --- |
| Playground provisioning, disk, or layer 2 network failure | iximiuz Labs support | [iximiuz Labs documentation](https://labs.iximiuz.com/docs) |
| Tailscale enrollment, policy, or SSH check failure | Tailnet administrator | Organization-approved operations channel |
| Incus, Btrfs, or OVN failure after a clean playbook run | Lab operator | Repository issue tracker with secret-free diagnostics |

## History

| Date | Run by | Notes |
| --- | --- | --- |
| 2026-09-05 | Repository owner and OpenCode | Deployed run `6a9bdbead17d324d6a33ce01`; verified three online Incus members, local Btrfs pools, OVN networking, Tailscale management, and container egress |

## References

- [Zabbly Incus packages](https://github.com/zabbly/incus)
- [Incus OVN cluster setup](https://linuxcontainers.org/incus/docs/main/howto/network_ovn_setup/#set-up-an-incus-cluster-on-ovn)
- [Incus clustered storage](https://linuxcontainers.org/incus/docs/main/howto/cluster_config_storage/)
- [Incus clustered networking](https://linuxcontainers.org/incus/docs/main/howto/cluster_config_networks/)
- [Tailscale SSH](https://tailscale.com/docs/features/tailscale-ssh)
