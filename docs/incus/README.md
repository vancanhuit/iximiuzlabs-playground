# Runbook: Deploy the Incus cluster playground

**Owner:** Lab operator | **Frequency:** As needed
**Last updated:** 2026-09-19 | **Last run:** 2026-09-19

## Purpose

Use this runbook to deploy and verify the repository's three-node Incus cluster on iximiuz Labs. The tested configuration provides:

- Incus 7.0 LTS packages from [Zabbly](https://github.com/zabbly/incus)
- containers only through the `incus-base` package
- three Incus database members and three OVN database members
- `eth0` for Incus clustering and OVN Geneve traffic
- unnumbered `eth1` interfaces on a shared layer 2 network for the OVN uplink
- one member-local Btrfs pool backed by `/dev/vdb` on each host
- Tailscale SSH for Ansible and private Incus API access
- OVN DHCP with `1.1.1.1` and `1.0.0.1` as the container DNS servers

The Btrfs pool is local storage. Incus can move instances between members, but their data is not synchronously replicated as it would be with shared storage such as Ceph.

## Architecture diagrams

- [Incus cluster architecture](architecture/incus-cluster.html): management access, cluster control, database quorums, and member-local storage
- [OVN network data paths](architecture/ovn-network.html): cross-member Geneve traffic, physical uplink egress, and boot recovery

[![Three-node Incus cluster architecture](architecture/incus-cluster.svg)](architecture/incus-cluster.html)

[![Incus OVN network data paths](architecture/ovn-network.svg)](architecture/ovn-network.html)

### OVN network data paths

Open the [interactive OVN network diagram](architecture/ovn-network.html) and select **Cross-member traffic**, **Internet egress**, or **Uplink boot recovery** to isolate a path.

OVN separates the logical container network from the networks that carry its traffic:

| Layer | Network or interface | Responsibility |
| --- | --- | --- |
| Logical overlay | `ovn0`, assigned by Incus | Assigns container addresses with DHCP and performs logical switching and routing |
| Tunnel underlay | `net-01` / member `eth0`, `172.16.0.0/24` | Carries Geneve packets between OVN chassis |
| Physical uplink | `UPLINK` / member `eth1` / `net-02`, `172.17.0.0/24` | Connects the OVN logical router to the playground network and gateway |
| Management | `tailscale0` | Carries Ansible, SSH, and Incus API traffic; it is not part of the container data path |

#### Same-member container traffic

1. The source container sends a frame through its virtual `eth0` interface.
2. The host-side Open vSwitch port receives the frame.
3. The local OVN controller applies the logical switch, router, and policy flows derived from the OVN southbound database.
4. Open vSwitch sends the frame to the destination container's local virtual port.

The packet remains on one Incus member. It does not enter a Geneve tunnel, physical `eth0`, `UPLINK`, or `eth1`.

#### Cross-member container traffic

1. The source container sends a frame through its virtual `eth0` interface to `ovn0`.
2. Open vSwitch applies OVN's logical forwarding rules and selects the remote chassis hosting the destination logical port.
3. OVN encapsulates the original frame in Geneve. The outer source and destination addresses are the Incus members' `eth0` addresses on `172.16.0.0/24`.
4. The Geneve packet crosses `net-01` to the destination member.
5. The destination chassis decapsulates the packet, applies its local OVN flows, and delivers the original frame to the destination container.

The inner container addresses remain on `ovn0`; only the outer Geneve packet uses the `172.16.0.0/24` underlay. Return traffic follows the same stages in the opposite direction and may use a different active chassis path selected by OVN.

#### Container Internet and DNS traffic

1. The container sends traffic for a non-local address to the `ovn0` logical router.
2. OVN selects the clustered physical network named `UPLINK` for north-south traffic.
3. `UPLINK` maps to unnumbered `eth1` on the active OVN chassis.
4. The Ethernet frame enters the shared `net-02` layer 2 network and resolves the configured gateway, currently `172.17.0.1`, with ARP.
5. The playground gateway must forward the packet and provide the external egress required to reach Internet services.
6. Reply traffic returns through the gateway, `net-02`, `UPLINK`, and the OVN logical router to the originating container.

DNS uses the same north-south path. OVN DHCP advertises `1.1.1.1` and `1.0.0.1`, but those addresses are usable only while the complete uplink and gateway path works. A successful DHCP lease or container-to-container ping does not prove Internet or DNS egress.

#### Uplink boot invariant

Every member's `eth1` must be up but have no host IPv4, IPv6, or link-local address. The `incus-ovn-uplink.service` unit runs after `systemd-networkd` and before Incus and `ovn-host`; it installs the unmanaged network definition, flushes addresses from `eth1`, and leaves the link active. This prevents host networking from competing with Open vSwitch for the OVN provider interface after a reboot.

The playground gateway can acquire a new MAC address when a persistent run resumes. OVN's southbound database retains learned MAC bindings across that stop/resume, and aging is disabled by default.

The playbook sets the `ovn0` logical router's `options:mac_binding_age_threshold` to `172.17.0.1/32:30`, derived from the discovered uplink gateway. OVN expires that gateway binding after 30 idle seconds and learns its current MAC through ARP. Other neighbors retain their default behavior. The setting persists in the replicated northbound database.

Use these boundaries when diagnosing a failure:

| Observation | Working portion | Inspect next |
| --- | --- | --- |
| Same-member ping works, cross-member ping fails | Container ports and local OVN switching | `ovn-controller`, Geneve chassis addresses, `eth0`, and `net-01` |
| Cross-member ping works, Internet IP fails | OVN overlay and Geneve underlay | `UPLINK`, unnumbered `eth1`, gateway ARP, and `172.17.0.1` forwarding |
| Internet IP works, DNS fails | OVN egress and gateway forwarding | DHCP-advertised resolvers and container resolver state |
| Networking fails only after reboot | Runtime OVN configuration may still be valid | `incus-ovn-uplink.service` ordering and addresses restored on `eth1` |

## Files

| Path | Purpose |
| --- | --- |
| [`incus-cluster.manifest.yaml`](../../incus-cluster.manifest.yaml) | Three machines, two networks, dedicated data disks, and package installation |
| [`ansible/inventories/incus.ini`](../../ansible/inventories/incus.ini) | Incus topology and playground run mapping |
| [`ansible/roles/tailscale_enrollment/`](../../ansible/roles/tailscale_enrollment/) | Reusable bootstrap enrollment through `labctl ssh` |
| [`ansible/tailscale.yml`](../../ansible/tailscale.yml) | Shared enrollment role entry point |
| [`ansible.cfg`](../../ansible.cfg) | Shared Python, user, and role-path settings |
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

## Network and storage invariants

The playbook discovers addresses at runtime rather than storing them in inventory:

| Resource | Use |
| --- | --- |
| `eth0` | Incus cluster endpoint, OVN northbound/southbound databases, and Geneve encapsulation |
| `eth1` | OVN physical uplink; Ansible removes its host addresses before creating `ovn0` |
| `tailscale0` | Tailscale SSH and client access to the Incus API |
| `/dev/vdb` | Dedicated Btrfs storage for the local Incus pool |

The playbook persists the discovered `eth1` subnet metadata in `/etc/incus/uplink.json`, then starts the manifest-installed `incus-ovn-uplink.service`. The service removes the interface address and stays active after preparing the link. Init tasks run only when a playground instance is created, not after an in-session machine reboot, so the enabled unit repeats this preparation before Incus and OVN start. Do not delete the metadata file unless `eth1` has its original playground address again.

Incus cluster traffic uses `cluster.https_address` on `eth0`. Incus has one HTTPS listener for both cluster and client traffic, so `core.https_address` listens on `0.0.0.0:8443`; management clients must use a Tailscale address or MagicDNS name, and tailnet policy remains the management access boundary.

## Procedure

### Step 1: Validate local configuration

Run these commands and all later Ansible commands from the repository root:

```bash
mise install
ansible-playbook --version
ansible-lint --version
ansible-lint \
  ansible/tailscale.yml \
  ansible/roles/tailscale_enrollment \
  ansible/incus_cluster.yml
ansible-playbook \
  -i ansible/inventories/incus.ini \
  ansible/tailscale.yml --syntax-check
ansible-playbook \
  -i ansible/inventories/incus.ini \
  ansible/incus_cluster.yml --syntax-check
git diff --check
```

**Expected result:** Both Ansible version commands succeed, both playbooks pass the production lint profile, and both syntax checks succeed.

**If it fails:** Run `mise install` again, then fix the reported file before changing the live playground.

### Step 2: Update the custom playground

The update changes future runs; it does not mutate an existing run.

```bash
labctl playground update incus-cluster-e6fb1c6c \
  --file incus-cluster.manifest.yaml \
  --force
```

**Expected result:** `labctl` returns `incus-cluster-e6fb1c6c` and its playground URL.

**If it fails:** Inspect `labctl playground manifest flexbox` and compare unsupported fields with the base manifest. Task keys and task names must contain only alphanumeric characters or underscores.

### Step 3: Remove stale Tailscale devices

Before recreating a run, inspect the Tailscale admin console for offline devices named `incus-01`, `incus-02`, and `incus-03`. Remove only devices confirmed to belong to a destroyed run. Duplicate records cause suffixed MagicDNS names such as `incus-01-1` and make the static Ansible inventory ambiguous.

Do not remove a live or unrelated node merely to reclaim a hostname.

**Expected result:** No existing Tailscale device owns any of the three names.

**If it fails:** Stop and identify the old run before deleting records. If it is still needed, use different machine names consistently in the manifest and inventory instead.

### Step 4: Start or resume a run

Start a fresh run when no cluster state must be preserved:

```bash
run_id=$(labctl playground start incus-cluster-e6fb1c6c --quiet)
labctl playground persist "${run_id}"
printf 'Run ID: %s\n' "${run_id}"
```

Resume a stopped persistent run instead:

```bash
labctl playground restart playground_run_id
```

For a fresh run, record the returned run ID and make the run persistent. Wait for `install_incus_01`, `install_incus_02`, and `install_incus_03` to complete. The init tasks install Zabbly Incus, Btrfs tools, OVN, Open vSwitch, and Tailscale, but do not enroll Tailscale or initialize Incus. A resumed run retains its disks and does not rerun init tasks.

**Expected result:** The persistent run has three machines and all installation tasks complete successfully.

**If it fails:** Inspect the run in the browser or use `labctl playground status run_id`. Do not run either playbook until all init tasks complete.

### Step 5: Enroll Tailscale through labctl

```bash
ansible-playbook \
  -i ansible/inventories/incus.ini \
  ansible/tailscale.yml \
  -e incus_play_id=playground_run_id
```

The playbook reaches each machine through `labctl ssh`, decrypts only `tailscale.access_token`, and creates a reusable, preauthorized one-hour key for `tag:lab`. It transfers the key through protected temporary files, enrolls all three machines with Tailscale SSH, removes the temporary files, revokes the key, and verifies each host's Tailscale backend through `labctl`.

**Expected result:** The play recap has no failures and `tailscale status` lists exactly one online device for each Incus hostname.

**If it fails:** The `always` block still attempts to delete local and remote key files and revoke the key. Check the Tailscale key list and revoke any remaining key manually before retrying. Remove partial offline device records before starting a replacement run.

### Step 6: Authorize Tailscale SSH check mode

If the policy uses `action: "check"`, the final task might print an authentication URL. Open it and complete authentication once, then confirm access:

```bash
ssh root@incus-01 true
ssh root@incus-02 true
ssh root@incus-03 true
```

Do not set `checkPeriod` to `always` for these hosts because Ansible opens multiple SSH connections. A finite check period preserves reauthentication without blocking the run.

**Expected result:** All three commands exit without prompting after authorization.

**If it fails:** Confirm both a network grant and an SSH rule permit the operator to reach `tag:lab`, and confirm each host was enrolled with `tailscale up --ssh`.

### Step 7: Build the Incus cluster

Warning: on a fresh run, this command permanently formats `/dev/vdb` on every member.

```bash
ansible-playbook \
  -i ansible/inventories/incus.ini \
  ansible/incus_cluster.yml
```

The playbook validates the disks and interfaces, builds the three-member OVN database, forms the Incus cluster, initializes the local Btrfs pools, detaches host addresses from `eth1`, creates `UPLINK` and `ovn0`, configures the OVN DNS servers and gateway MAC-binding expiry, updates the default profile, and verifies cluster and network state.

**Expected result:** All plays complete without failures. The first run reports changes; later runs should be mostly `ok` or `skipped`.

**If it fails:** Fix the reported stage and rerun the same playbook. It is designed to resume after successful cluster joins, Btrfs initialization, or network creation. Never manually format `/dev/vdb` to bypass the safety assertion.

### Step 8: Configure the control host client

The client certificate is public material, but use a private temporary file on the cluster member and remove it immediately after adding trust:

```bash
ssh root@incus-01 'umask 077; cat >/tmp/control-host-incus-client.crt' \
  < ~/.config/incus/client.crt
ssh root@incus-01 \
  "incus config trust add-certificate \
    /tmp/control-host-incus-client.crt \
    --name control-host-$(hostname) \
    --description 'Incus client via Tailscale'; \
   rm -f /tmp/control-host-incus-client.crt"
incus remote list --format csv --columns n | grep -qx incus-lab && \
  incus remote remove incus-lab
incus remote add incus-lab https://incus-01:8443 --accept-certificate
incus remote switch incus-lab
incus cluster list
```

If `control-host-$(hostname)` already exists on the new cluster, inspect it instead of adding a duplicate. Replacing `incus-lab` makes the control host accept the new cluster's server certificate.

**Expected result:** `incus cluster list` succeeds from the control host and reports all three members as `ONLINE`.

**If it fails:** Confirm `incus-01` resolves through MagicDNS, TCP port `8443` is allowed by the tailnet policy, and `core.https_address` is `0.0.0.0:8443`.

## Verification

Run control-plane checks through Tailscale SSH:

```bash
ssh root@incus-01 \
  'incus cluster list; incus storage list; incus network list'
```

Confirm:

- [ ] `incus-01`, `incus-02`, and `incus-03` are `ONLINE`.
- [ ] `local` uses the `btrfs` driver and is `CREATED`.
- [ ] `UPLINK` is a `physical` network in `CREATED` state.
- [ ] `ovn0` is an `ovn` network in `CREATED` state.
- [ ] `incus network get ovn0 dns.nameservers` returns `1.1.1.1,1.0.0.1`.
- [ ] `eth1` is up but has no host IPv4 or IPv6 address on every member.
- [ ] `incus-ovn-uplink.service` is enabled and active on every member.
- [ ] `incus config get core.https_address` returns `0.0.0.0:8443`.
- [ ] The `ovn0` logical router has `options:mac_binding_age_threshold="172.17.0.1/32:30"`.

Run one disposable workload on each member and wait for DHCP:

```bash
for member in incus-01 incus-02 incus-03; do
  incus launch images:debian/13/cloud "test-${member}" \
    --profile default \
    --target "${member}"
done

for instance in test-incus-01 test-incus-02 test-incus-03; do
  until incus exec "${instance}" -- ip -4 route show default | grep -q default; do
    sleep 1
  done
done
```

Verify full-mesh name resolution and connectivity, plus external DNS and package repositories:

```bash
for source in test-incus-01 test-incus-02 test-incus-03; do
  for destination in test-incus-01 test-incus-02 test-incus-03; do
    [ "${source}" = "${destination}" ] || \
      incus exec "${source}" -- ping -c 3 "${destination}"
  done
done

incus exec test-incus-01 -- getent hosts deb.debian.org
incus exec test-incus-01 -- apt-get update

for instance in test-incus-01 test-incus-02 test-incus-03; do
  incus delete --force "${instance}"
done
```

**Expected result:** Each container receives an address on `ovn0`, resolves and reaches both peers by name, resolves `deb.debian.org` through the configured DNS servers, completes `apt-get update`, and is removed afterward.

### Stop/resume regression check

For this check, defer the container deletion loop above until after resume verification. If you already removed the containers, repeat the launch and DHCP steps first. A rolling VM reboot alone does not exercise gateway replacement.

Stop the persistent playground and check its status:

```bash
labctl playground stop playground_run_id
labctl playground status playground_run_id
```

Repeat the status command until the run's `State` is `STOPPED`. Individual machines can report `STOPPED` while the run is still finalizing. Then resume it:

```bash
labctl playground restart playground_run_id
```

Wait for all three members to report `ONLINE`, then repeat the workload checks above on every member. Allow up to 60 seconds for gateway neighbor expiry and ARP recovery after the services are ready. Confirm the setting survived by querying the router name from Incus rather than assuming its internal ID:

```bash
ssh root@incus-01 'bash -s' <<'EOF'
set -euo pipefail
nb=$(incus config get network.ovn.northbound_connection)
router=$(incus query /1.0/networks/ovn0/state |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["ovn"]["logical_router"])')
ovn-nbctl --timeout=15 --db="$nb" get Logical_Router "$router" options
EOF
```

**Expected result:** Gateway aging remains configured; container DNS, Internet access, and cross-member connectivity recover without an Ansible rerun or manual ARP refresh. Remove the disposable containers afterward.

### Verified resume recovery on 2026-09-19

Resuming run `6aa69e8bb4bf6f74dea37640` restored all three Incus members and both OVN database quorums, but container egress failed. OVN retained the September 13 gateway MAC `46:f6:76:7a:3a:49`; the resumed gateway used `3e:8c:8b:75:db:be`. An ARP refresh restored egress, confirming the stale binding as the cause.

After enabling gateway-specific 30-second aging, reinserting the obsolete MAC reproduced the failure. OVN recovered automatically at about 30 seconds, even while outbound pings continued. A full playbook reconciliation completed with zero changes and no failures.

A subsequent playground stop/resume changed the gateway MAC again to `42:7c:18:b1:d6:d8`; OVN learned it without manual intervention. Before and after resume, three disposable containers passed all six directed peer paths over both IPv4 and IPv6. They also passed external DNS, Internet IP probes, and `apt-get update`. All test containers were removed afterward.

### Verified state on 2026-09-13

Fresh persistent run `6aa69e8bb4bf6f74dea37640` passed the complete procedure. All three replacement Tailscale devices were online. A second reconciliation after activating the persistent uplink service and a third reconciliation after rolling reboots completed without failures; the third run reported no changes.

The control host used `incus-lab` as its current remote:

```text
NAME                 URL                                   PROTOCOL       AUTH TYPE    PUBLIC  STATIC  GLOBAL
homelab-server       https://debian-incus:8443             incus          tls          NO      NO      NO
images               https://images.linuxcontainers.org    simplestreams  none         YES     NO      NO
incus-lab (current)  https://incus-01:8443                 incus          tls          NO      NO      NO
local                unix://                               incus          file access  NO      YES     NO
```

All three cluster members were fully operational:

```text
NAME      URL                        ROLES                     STATUS  MESSAGE
incus-01  https://172.16.0.2:8443    database-leader,database  ONLINE  Fully operational
incus-02  https://172.16.0.3:8443    database                  ONLINE  Fully operational
incus-03  https://172.16.0.4:8443    database                  ONLINE  Fully operational
```

The connectivity test created one Debian 13 cloud container on each member. They received `10.8.143.2` through `10.8.143.4`, passed full-mesh name resolution and connectivity, resolved `deb.debian.org`, completed `apt-get update`, survived rolling member reboots, and were removed afterward.

After each reboot, `incus-ovn-uplink.service` was active, `eth1` had no global address, all Incus members were `ONLINE`, and both three-member OVN databases retained quorum.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `Module zfs not found` | The default Firecracker kernel does not provide ZFS | Use the supported Btrfs configuration; do not add DKMS or a custom kernel unless ZFS is explicitly required |
| `database connection failed` from `ovs-vsctl` | `openvswitch-switch` is not running | Start and enable `openvswitch-switch`, then rerun `ansible/incus_cluster.yml` |
| Join preseed reports a YAML scanner error | Human-readable text was included with the token | Keep `incus cluster add --quiet` in the playbook and create a fresh token |
| `Network is not in pending state` | A prior run already finalized `UPLINK` | Inspect `incus network show UPLINK`; rerun the current idempotent playbook instead of recreating targets |
| `ipv6.gateway` rejects `none` | Physical uplinks do not accept that value | Omit `ipv6.gateway`; this runbook configures only the IPv4 uplink |
| OVN says `eth1` has addresses | systemd-networkd still owns the uplink address | Confirm `/etc/systemd/network/20-eth1.network` is unmanaged, flush `eth1`, and rerun the playbook |
| `ovn0` is unavailable after a reboot | `eth1` regained its playground address before Incus started | Confirm `incus-ovn-uplink.service` is enabled, rerun `ansible/incus_cluster.yml`, and restart `incus.service` after `eth1` is unnumbered |
| Containers reach `ovn0` but not `1.1.1.1` | The OVN uplink gateway is unreachable | From the active OVN chassis, verify that `172.17.0.1` answers ARP on `eth1`; restore playground network egress before changing container DNS |
| Container egress fails after playground resume, but hosts and cross-member traffic work | OVN retained the gateway's old MAC address | Verify `mac_binding_age_threshold` as above; rerun `ansible/incus_cluster.yml` if missing, then allow neighbor expiry and retry. Do not pin the gateway MAC or flush the entire southbound database |
| Containers reach `1.1.1.1` but names do not resolve | OVN DHCP advertised missing or incorrect resolvers | Run `incus network set ovn0 dns.nameservers=1.1.1.1,1.0.0.1`, restart the test container, and rerun the playbook to persist the setting |
| Members become `OFFLINE` after API configuration | `core.https_address` was bound only to Tailscale | Restore `incus config set core.https_address=0.0.0.0:8443` locally on every member |
| MagicDNS resolves to a suffixed name | A stale Tailscale device owns the canonical hostname | Remove only the confirmed stale record, then reenroll the replacement node |
| Ansible waits at SSH authentication | Tailscale SSH check mode requires reauthentication | Open the printed URL once; do not use `checkPeriod: always` with Ansible |

## Rollback and teardown

To roll back gateway neighbor aging, remove only `mac_binding_age_threshold` from the logical router's `options` map:

```bash
ssh root@incus-01 'bash -s' <<'EOF'
set -euo pipefail
nb=$(incus config get network.ovn.northbound_connection)
router=$(incus query /1.0/networks/ovn0/state |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["ovn"]["logical_router"])')
ovn-nbctl --timeout=15 --db="$nb" remove Logical_Router "$router" \
  options mac_binding_age_threshold
EOF
```

Remove the corresponding Ansible task too, or the next reconciliation will restore it. This rollback reintroduces the stale-gateway risk after stop/resume.

Stop a run when its state might still be needed:

```bash
labctl playground stop playground_run_id
```

Permanently destroy a disposable run only after confirming no Incus instance or volume data is required. Then remove its three stale Tailscale device records before starting another run:

```bash
labctl playground destroy playground_run_id
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
| 2026-09-19 | Repository owner and OpenCode | Fixed stale OVN uplink gateway MAC bindings after resume with gateway-specific neighbor aging; verified fault-injection recovery, idempotence, and complete workload connectivity across a full playground stop/resume |
| 2026-09-13 | Repository owner and OpenCode | Deleted the three stale Incus Tailscale devices; deployed persistent run `6aa69e8bb4bf6f74dea37640` from scratch; verified Incus, Btrfs, OVN quorum, full-mesh workloads, DNS, package egress, idempotence, and rolling reboot recovery |
| 2026-09-08 | Repository owner and OpenCode | Resumed run `6a9bdbead17d324d6a33ce01`; configured control-host access, persistent OVN uplink recovery, explicit container DNS, and verified `apt-get update` |
| 2026-09-05 | Repository owner and OpenCode | Deployed run `6a9bdbead17d324d6a33ce01`; verified three online Incus members, local Btrfs pools, OVN networking, Tailscale management, and container egress |

## References

- [Zabbly Incus packages](https://github.com/zabbly/incus)
- [Incus OVN cluster setup](https://linuxcontainers.org/incus/docs/main/howto/network_ovn_setup/#set-up-an-incus-cluster-on-ovn)
- [OVN northbound schema: MAC-binding aging](https://www.ovn.org/support/dist-docs/ovn-nb.5.html) (also available in the installed OVN 25.03 `ovn-nb(5)` manual)
- [Incus clustered storage](https://linuxcontainers.org/incus/docs/main/howto/cluster_config_storage/)
- [Incus clustered networking](https://linuxcontainers.org/incus/docs/main/howto/cluster_config_networks/)
- [Tailscale SSH](https://tailscale.com/docs/features/tailscale-ssh)
