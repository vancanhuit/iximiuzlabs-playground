# k0s over Tailscale on iximiuz Labs

This runbook builds an eight-node Kubernetes cluster across two iximiuz Labs
playgrounds. Tailscale is the private node network, `k0sctl` bootstraps k0s, and
Cilium provides a kube-proxy-free Pod network.

Presentation-ready, interactive diagrams are available under
[`architecture/`](architecture/):

- [lab system architecture](architecture/lab-architecture.html)
- [bootstrap journey](architecture/bootstrap-journey.html)

Both presentations include guided chapters, light and dark themes, searchable
components, relationship tracing, and export controls.

The result has three distinct network layers:

| Layer | CIDR or interface | Purpose |
| --- | --- | --- |
| Node underlay | `tailscale0`, `100.64.0.0/10` | SSH, etcd, Kubernetes API, kubelet, and Cilium VXLAN |
| Pod network | `10.244.0.0/16` | Cilium allocates one `/24` to each worker |
| Service network | `10.96.0.0/12` | Virtual Kubernetes Service addresses |

Do not advertise the Pod or Service CIDR as a Tailscale subnet route. These
networks are internal to Kubernetes. Tailnet clients should access the API and
applications through Tailscale identities, not by routing all cluster CIDRs.

## Architecture and invariants

[![Interactive k0s lab architecture](architecture/lab-architecture.svg)](architecture/lab-architecture.html)

Open the [interactive architecture](architecture/lab-architecture.html) to use
guided chapters, trace relationships, switch themes, present full-screen, or
export the diagram. The companion
[bootstrap journey](architecture/bootstrap-journey.html) tells the deployment
story from eight empty machines to identity-aware shared access.

[![Interactive k0s bootstrap journey](architecture/bootstrap-journey.svg)](architecture/bootstrap-journey.html)

The configuration depends on these invariants:

- every host has a unique, stable hostname and Tailscale IPv4 address
- all hosts remain in the same tailnet and can reach each other according to
  tailnet policy
- `privateAddress` and `privateInterface` select `tailscale0` for k0s traffic
- `api.onlyBindToAddress: true` prevents multihomed controllers from selecting
  an iximiuz Labs `172.16.0.x` address
- controller certificate SANs contain every controller name and Tailscale IP
- Pod, Service, playground LAN, and other routed CIDRs do not overlap
- Cilium uses VXLAN because the Pod CIDR is not routed through Tailscale
- workers keep ordinary Internet egress for image registries, Tailscale
  coordination, and DERP

Controllers are intentionally not workers. `kubectl get nodes` therefore lists
five workers, not eight hosts. Check controllers with `k0s status` and `k0s etcd
member-list`.

## Reference versions

The repository pins client tools in [`../../mise.toml`](../../mise.toml). The
cluster manifests currently use:

| Component | Version |
| --- | --- |
| k0sctl | `v0.32.2` |
| k0s / Kubernetes | `v1.36.3+k0s.0` |
| Cilium | `v1.20.0` |
| Tailscale Kubernetes Operator | `1.98.9` |
| Sonobuoy | `v0.57.5` |

Treat these as a tested set. Validate upgrades in a fresh playground before
changing a shared or long-lived cluster.

## 1. Prepare the control host

Run commands from the repository root unless a step says otherwise:

```bash
mise install
mise ls --local
uv sync --locked
uv run --locked python -m unittest scripts/test_update_k0s_tailscale_ips.py -v
```

The control host needs `k0sctl`, `kubectl`, Helm, Cilium CLI, Python, and a
Tailscale client connected to the same tailnet as the lab nodes.

Start both iximiuz Labs playgrounds described in the repository root
[`README.md`](../../README.md). Verify that their machine hostnames exactly match
[`k0s.yaml`](k0s.yaml):

```text
control-plane-01  control-plane-02  control-plane-03
node-01           node-02           node-03  node-04  node-05
```

## 2. Configure the tailnet policy

Use tags for lab machines so their identity is independent of the person who
enrolls them. The following HuJSON mirrors the policy used by this personal lab.
Replace `<TAILSCALE_LOGIN>` with the login name shown by `tailscale status`, such
as an email address.

```jsonc
{
  "tagOwners": {
    "tag:lab": [],
    "tag:k8s-operator": [],
    "tag:k8s": ["tag:k8s-operator"]
  },

  "grants": [
    {
      "src": ["*"],
      "dst": ["*"],
      "ip": ["*"]
    },
    {
      "src": ["<TAILSCALE_LOGIN>"],
      "dst": ["tag:k8s"],
      "ip": ["tcp:80", "tcp:443"]
    }
  ],

  "ssh": [
    {
      "action": "check",
      "src": ["autogroup:member"],
      "dst": ["autogroup:self"],
      "users": ["autogroup:nonroot", "root"]
    },
    {
      "action": "check",
      "src": ["<TAILSCALE_LOGIN>"],
      "dst": ["tag:lab"],
      "users": ["laborant", "root"]
    }
  ],

  "autoApprovers": {
    "services": {
      "svc:lab-k0s": ["tag:k8s"]
    }
  }
}
```

An empty tag-owner list means tags are assigned through an admin-created auth
key or the scoped operator credentials, not delegated to ordinary tailnet
members. The operator owns `tag:k8s` and the exact `svc:lab-k0s` auto-approver
prevents it from advertising arbitrary Tailscale Services.

> **Sharing boundary:** The wildcard grant is the convenient default retained
> by this personal tailnet. It allows every source to reach every destination
> and makes the narrower API grant redundant for network authorization. Before
> inviting colleagues into the tailnet, remove the wildcard rule and replace it
> with reviewed grants for administrators, `tag:lab` node-to-node cluster ports,
> and the `tag:k8s` API endpoint.

Tailscale SSH policy and network grants are separate controls. The `check`
action requires periodic reauthentication before granting `root` access. Use a
shorter period or a just-in-time access workflow for production
administration.

## 3. Enroll the playground machines

Create a pre-approved, tagged auth key for `tag:lab`. This lab stores the key at
`tailscale.auth_key` in the SOPS-encrypted
[`../../secrets/lab.sops.yaml`](../../secrets/lab.sops.yaml). Prefer a one-off
key. If a reusable key is required to enroll all eight machines, revoke it
immediately afterward.

On each machine, place the key in a root-only temporary file and enroll it:

```bash
sops decrypt --extract '["tailscale"]["auth_key"]' \
  secrets/lab.sops.yaml | ssh <PLAYGROUND_USER>@<NODE> \
  'sudo install -m 600 /dev/stdin /run/tailscale-auth-key'

ssh <PLAYGROUND_USER>@<NODE> sudo tailscale up \
  --auth-key=file:/run/tailscale-auth-key \
  --advertise-tags=tag:lab \
  --ssh
ssh <PLAYGROUND_USER>@<NODE> sudo rm -f /run/tailscale-auth-key
```

When already connected to an interactive node shell, the equivalent commands
are:

```bash
sudo install -m 600 /dev/stdin /run/tailscale-auth-key
sudo tailscale up \
  --auth-key=file:/run/tailscale-auth-key \
  --advertise-tags=tag:lab \
  --ssh
sudo rm -f /run/tailscale-auth-key
```

For the interactive form, enter the auth key on standard input and press
`Ctrl-D`. Repeat enrollment for all eight nodes. Do not put auth keys in shell
history, playground manifests, plaintext Git files, or command arguments.

Do not enable `--accept-routes` by default. A cluster node does not need other
subnet routes to communicate with tailnet peers, and an accepted route that
overlaps `10.244.0.0/16` or `10.96.0.0/12` can break Kubernetes networking. Add
it only when workloads have an explicit requirement for a routed subnet and all
CIDRs have been checked.

Tagged devices normally have key expiry disabled. If tailnet policy enables
expiry for tags, renew the nodes before expiry; losing the Tailscale underlay
partitions both etcd and the Kubernetes control plane.

## 4. Run the Tailscale preflight

All eight nodes must be online before bootstrap. From the control host:

```bash
tailscale status
tailscale ping control-plane-01
tailscale ping control-plane-02
tailscale ping control-plane-03
tailscale ping node-01
ssh root@control-plane-01 hostname
ssh root@node-01 hostname
```

Run a full peer and interface check from one controller and one worker:

```bash
ssh root@control-plane-01 'tailscale status; tailscale netcheck; ip -br addr show tailscale0'
ssh root@node-01 'tailscale status; tailscale netcheck; ip -br addr show tailscale0'
```

`tailscale ping` should eventually report a direct path when iximiuz networking
allows it. A DERP path is functionally valid, but etcd and VXLAN latency and
throughput will be worse. Do not bootstrap if peers are missing, hostnames are
duplicated, or connectivity is intermittent.

Confirm the cluster CIDRs do not overlap routes accepted by the control host or
nodes:

```bash
ip route get 10.244.0.1
ip route get 10.96.0.1
```

Before Cilium is installed these addresses must not resolve through another
VPN or Tailscale subnet router. If they overlap, choose unused Pod and Service
CIDRs in both [`k0s.yaml`](k0s.yaml) and
[`cilium-values.yaml`](cilium-values.yaml) before bootstrap.

## 5. Populate Tailscale addresses

Tailscale addresses are tailnet-specific. The checked-in addresses are examples,
not portable configuration. Preview and apply the discovered addresses:

```bash
uv run scripts/update_k0s_tailscale_ips.py --dry-run
uv run scripts/update_k0s_tailscale_ips.py
git diff -- docs/k0s/k0s.yaml
```

The updater reads `tailscale status --json`, requires every configured hostname
to be online, and rejects duplicate names, reused addresses, and addresses
outside `100.64.0.0/10`. It updates only:

- each host's `ssh.address`
- each host's `privateAddress`
- controller IPs in the API certificate SAN list

Review the diff. Hostnames, roles, interfaces, versions, and CIDRs remain manual
configuration.

## 6. Validate and bootstrap k0s

Always inspect a dry run first:

```bash
k0sctl apply --config docs/k0s/k0s.yaml --dry-run
```

Each generated controller configuration must use that controller's Tailscale IP
for `spec.api.address`. Join validation must not target an iximiuz Labs
`172.16.0.x` address.

Apply the cluster:

```bash
k0sctl apply --config docs/k0s/k0s.yaml
```

`spec.options.wait.enabled` is intentionally `false`: k0s uses a custom CNI and
kube-proxy is disabled, so workers remain `NotReady` until Cilium is installed.

Validate the control plane and etcd:

```bash
ssh root@control-plane-01 k0s status
ssh root@control-plane-02 k0s status
ssh root@control-plane-03 k0s status
ssh root@control-plane-01 k0s etcd member-list
ssh root@control-plane-01 k0s kubectl get nodes -o wide
```

The etcd member list should contain all three controller Tailscale addresses.
The five workers should exist with `100.x` InternalIP values and be `NotReady`.

If only the first controller starts, verify `api.onlyBindToAddress: true` and
rerun the dry run. `k0sctl` can normally reconcile the partial installation:

```bash
ssh root@control-plane-01 \
  "journalctl -u k0scontroller --no-pager | grep 'using api address'"
k0sctl apply --config docs/k0s/k0s.yaml --dry-run
k0sctl apply --config docs/k0s/k0s.yaml
```

## 7. Configure break-glass API access

Fetch the admin kubeconfig without overwriting an existing file blindly:

```bash
mkdir -p ~/.kube
if [[ -f ~/.kube/config ]]; then
  cp --backup=numbered --preserve=mode,timestamps \
    ~/.kube/config ~/.kube/config.pre-k0s
fi

tmp_kubeconfig=$(mktemp)
k0sctl kubeconfig --config docs/k0s/k0s.yaml >"$tmp_kubeconfig"
install -m 600 "$tmp_kubeconfig" ~/.kube/config
rm -f "$tmp_kubeconfig"

kubectl config current-context
kubectl get --raw=/readyz
```

The expected context is `tailscale-k0s`, and `/readyz` returns `ok`. This
kubeconfig contains a high-privilege client certificate and points directly to
the first controller. Protect it as a recovery credential.

There is no external virtual IP in this design. k0s node-local load balancing
protects worker components but not clients on the control host. Because every
controller address is a certificate SAN, an administrator can temporarily set
the kubeconfig server to another controller during recovery.

Do not configure `spec.api.externalAddress` while using k0s node-local load
balancing; these modes are incompatible.

## 8. Install Cilium

Install Cilium with the checked-in values:

```bash
cilium install --version 1.20.0 --values docs/k0s/cilium-values.yaml
cilium status --wait
```

Helm may warn that the Hubble Relay server listener is not TLS-enabled. In this
lab the `hubble-relay` Service remains `ClusterIP`, Hubble UI is the only Relay
client, and agent-to-Relay traffic uses Cilium's chart-managed Hubble TLS. Do not
expose the Relay Service outside the cluster without configuring Relay server
TLS and client authentication.

The important Tailscale-specific values are:

- `k8sServiceHost: 127.0.0.1` and port `7443` use k0s's worker-local API proxy
- `nodePort.directRoutingDevice: tailscale0` selects the node underlay
- `devices: [eth0, tailscale0]` explicitly attaches service handling and
  masquerading to the two stable lab interfaces
- `routingMode: tunnel` and `tunnelProtocol: vxlan` carry Pod traffic across
  the tailnet
- `MTU: 1230` fits VXLAN inside the `1280`-byte Tailscale interface MTU
- `socketLB.hostNamespaceOnly: true` is required for Tailscale operator proxy
  Pods when Cilium replaces kube-proxy

The values disable the Layer 7 proxy and omit Cilium Gateway API, standalone
Envoy, eBPF TPROXY, Cluster Mesh, Cilium encryption, and advanced load-balancer
modes. The lab does not use those features, and `bpf.tproxy` is beta in Cilium
1.20. Tailscale already encrypts the node underlay, while the Tailscale
Kubernetes Operator provides the private API endpoint.

Do not raise the Pod MTU unless the effective path MTU has been measured across
all node pairs. Nested WireGuard and VXLAN encapsulation makes MTU errors appear
as selective hangs on larger requests while simple health checks still pass.

## 9. Verify cluster networking

```bash
kubectl get nodes -o wide
kubectl -n kube-system get pods -o wide
kubectl -n kube-system get daemonset kube-proxy
cilium status --wait
```

Expected results:

- all five workers are `Ready` with Tailscale InternalIP addresses
- Cilium, CoreDNS, Hubble, NLLB, and konnectivity Pods are running
- the kube-proxy DaemonSet does not exist

Run focused connectivity tests after bootstrap, networking changes, and Cilium
upgrades:

```bash
cilium connectivity test \
  --ip-families ipv4 \
  --test '^no-policies/' \
  --test '^client-egress/' \
  --hubble=false \
  --flow-validation disabled \
  --junit-file /tmp/cilium-connectivity-junit.xml \
  --timeout 15m

cilium connectivity test --cleanup
```

These selectors cover baseline Pod connectivity, ClusterIP and NodePort
Services, DNS resolution, and controlled client egress without enabling
Cilium's Layer 7 proxy. The `dns-only` test is intentionally excluded because
it validates DNS-aware L7 policy and requires Envoy, which this lab does not
use. A successful run currently executes 70 actions across the two selected
tests, including same-node and cross-node Pod traffic, ClusterIP and NodePort
Services on every Tailscale node address, DNS, and Internet egress. Always run
the cleanup command, including after an interrupted or failed test.

Also inspect the effective MTU and Tailscale paths:

```bash
ssh root@node-01 ip -d link show tailscale0
ssh root@node-01 ip -d link show cilium_vxlan
kubectl -n kube-system exec daemonset/cilium -- \
  cilium-dbg status --verbose | grep -i mtu
ssh root@node-01 tailscale ping node-02
```

`tailscale0` should report MTU `1280`. With the documented uppercase Helm key,
the Cilium interfaces and workload routes should report MTU `1230`.

### Run Kubernetes conformance tests

[Sonobuoy](https://sonobuoy.io/docs/v0.57.5/) runs the upstream Kubernetes e2e
conformance suite without adding a permanent in-cluster component. Install the
tested CLI version through mise without changing the repository tool pins:

```bash
mise install sonobuoy@0.57.5
mise exec sonobuoy@0.57.5 -- sonobuoy version
```

Use the direct recovery context for the run and result transfer. The Tailscale
ProxyGroup path is tested separately below; routing a large result archive
through it adds an unrelated dependency to conformance collection.

Run quick mode after bootstrap to verify the Sonobuoy harness, plugin image
pulls, scheduling, and result collection:

```bash
(
  set -euo pipefail
  context=tailscale-k0s
  trap 'mise exec sonobuoy@0.57.5 -- sonobuoy \
    --context "$context" delete --wait' EXIT

  mise exec sonobuoy@0.57.5 -- sonobuoy \
    --context "$context" run --mode quick --wait
  results=$(mise exec sonobuoy@0.57.5 -- sonobuoy \
    --context "$context" retrieve /tmp)
  mise exec sonobuoy@0.57.5 -- sonobuoy results "$results"
)
```

Before accepting a Kubernetes, k0s, or Cilium upgrade, run the broader
non-disruptive conformance profile. It takes about two hours on this lab:

```bash
(
  set -euo pipefail
  context=tailscale-k0s
  trap 'mise exec sonobuoy@0.57.5 -- sonobuoy \
    --context "$context" delete --wait' EXIT

  mise exec sonobuoy@0.57.5 -- sonobuoy \
    --context "$context" run --mode non-disruptive-conformance --wait
  results=$(mise exec sonobuoy@0.57.5 -- sonobuoy \
    --context "$context" retrieve /tmp)
  mise exec sonobuoy@0.57.5 -- sonobuoy results "$results"
)
```

Acceptance requires zero failed e2e tests and all five `systemd-logs` plugin
results to pass. Inspect every failure in the retrieved archive. An isolated
rerun can distinguish a transient from a repeatable defect, but it does not
turn a failed full run into a passing upgrade gate. Sonobuoy's log summary also
counts lines containing words such as `error` or `warning`; those counts are
diagnostic leads, not failed tests by themselves.

For a fresh cluster without workloads, run the complete certification profile.
It includes disruptive conformance tests, so do not run it on a shared cluster
without an outage window and backups:

```bash
(
  set -euo pipefail
  context=tailscale-k0s
  trap 'mise exec sonobuoy@0.57.5 -- sonobuoy \
    --context "$context" delete --all --wait' EXIT

  mise exec sonobuoy@0.57.5 -- sonobuoy \
    --context "$context" run --mode certified-conformance --wait
  results=$(mise exec sonobuoy@0.57.5 -- sonobuoy \
    --context "$context" retrieve /tmp)
  sha256sum "$results"
  mise exec sonobuoy@0.57.5 -- sonobuoy results "$results"
)
```

The pinned Kubernetes `v1.36.3+k0s` and Sonobuoy `v0.57.5` set passed this
profile with 453 e2e tests passed, zero failed, and all five node log plugins
passed. The run took about two hours. The `--all` cleanup removes leaked
`e2e-*` namespaces in addition to Sonobuoy's own resources. Preserve the result
archive and checksum when conformance evidence must be retained beyond the
playground lifetime.

Finally, verify both API access paths and the ProxyGroup replicas:

```bash
kubectl --context tailscale-k0s get --raw=/readyz
kubectl --context lab-k0s.<TAILNET_DNS_NAME>.ts.net get --raw=/readyz
kubectl --context lab-k0s.<TAILNET_DNS_NAME>.ts.net auth whoami
kubectl --context tailscale-k0s wait proxygroup/lab-k0s \
  --for=condition=ProxyGroupReady=true \
  --timeout=30s
kubectl --context tailscale-k0s -n tailscale get pods \
  -l tailscale.com/parent-resource=lab-k0s \
  -o wide
```

Both readiness requests should return `ok`, `auth whoami` should show the
expected Tailscale login rather than the direct admin certificate identity, and
the two proxy Pods should be `Running` on different workers.

## 10. Optional: install the Tailscale Kubernetes Operator

The direct kubeconfig is suitable for bootstrap and recovery. For routine
shared access, the Tailscale Kubernetes Operator can expose an HA API endpoint
that authenticates users with their Tailscale identity and authorizes them with
Kubernetes RBAC.

This path requires the `tag:k8s-operator`, `tag:k8s`, grants, and service
auto-approver from step 2. Enable HTTPS on the Tailscale admin console DNS page.

Create an OAuth client with these write scopes and assign it
`tag:k8s-operator`:

- General / Services
- Devices / Core
- Keys / Auth Keys

Store the OAuth values at `tailscale.oauth.client_id` and
`tailscale.oauth.client_secret` in the SOPS-encrypted secrets file. The API
access token at `tailscale.access_token` is optional and is used only for the
manual Service-approval fallback below. Use placeholders when preparing a new
encrypted file:

```yaml
tailscale:
  access_token: <TAILSCALE_API_ACCESS_TOKEN>
  auth_key: <TAGGED_LAB_AUTH_KEY>
  oauth:
    client_id: <TAILSCALE_OPERATOR_OAUTH_CLIENT_ID>
    client_secret: <TAILSCALE_OPERATOR_OAUTH_CLIENT_SECRET>
  kubernetes_user: <TAILSCALE_LOGIN>
```

Edit these values only through `sops secrets/lab.sops.yaml`. Never commit the
plaintext placeholders after replacing them. The following command decrypts
only the two OAuth fields into a root-only temporary directory, avoiding command
arguments and Helm release values:

```bash
kubectl create namespace tailscale --dry-run=client -o yaml | kubectl apply -f -

(
  set -e
  if [[ $- == *x* ]]; then
    printf 'Disable shell tracing before handling OAuth credentials.\n' >&2
    exit 1
  fi

  oauth_dir=$(mktemp -d)
  chmod 700 "$oauth_dir"
  trap 'rm -rf "$oauth_dir"' EXIT
  umask 077
  sops decrypt --extract '["tailscale"]["oauth"]["client_id"]' \
    secrets/lab.sops.yaml >"$oauth_dir/client_id"
  sops decrypt --extract '["tailscale"]["oauth"]["client_secret"]' \
    secrets/lab.sops.yaml >"$oauth_dir/client_secret"

  kubectl -n tailscale create secret generic operator-oauth \
    --from-file=client_id="$oauth_dir/client_id" \
    --from-file=client_secret="$oauth_dir/client_secret" \
    --dry-run=client -o yaml | kubectl apply -f -
)

helm repo add tailscale https://pkgs.tailscale.com/helmcharts
helm repo update
helm upgrade --install tailscale-operator tailscale/tailscale-operator \
  --version 1.98.9 \
  --namespace tailscale \
  --set-string apiServerProxyConfig.allowImpersonation=true \
  --wait

kubectl -n tailscale rollout status deployment/operator --timeout=5m
```

For stricter secret handling, render the Secret from a secret-manager plugin or
an external-secrets controller instead of environment variables. Disable shell
tracing before handling secrets. Kubernetes Secrets are not encrypted at rest
unless API-server encryption is configured.

Create a two-replica API proxy:

```bash
kubectl apply -f - <<'YAML'
apiVersion: tailscale.com/v1alpha1
kind: ProxyGroup
metadata:
  name: lab-k0s
spec:
  type: kube-apiserver
  replicas: 2
  kubeAPIServer:
    mode: auth
    hostname: lab-k0s
YAML

kubectl wait proxygroup/lab-k0s \
  --for=condition=ProxyGroupReady=true \
  --timeout=5m
kubectl get proxygroup lab-k0s
```

Expected URL shape: `https://lab-k0s.<TAILNET_DNS_NAME>.ts.net`. If both proxy
Pods are running but `ProxyGroupReady` remains false, inspect the advertised
Service before changing Kubernetes configuration:

```bash
kubectl get proxygroup lab-k0s \
  -o jsonpath='{range .status.conditions[*]}{.type}{"="}{.status}{": "}{.message}{"\n"}{end}'
```

The preferred fix is the exact `svc:lab-k0s` auto-approver in step 2. As a
manual fallback, an owner-generated API access token can approve only the two
operator-created backends. This command keeps the token in memory and does not
print it:

```bash
(
  set -euo pipefail
  token=$(sops decrypt --extract '["tailscale"]["access_token"]' \
    secrets/lab.sops.yaml)
  trap 'unset token' EXIT

  hosts=$(curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $token" \
    'https://api.tailscale.com/api/v2/tailnet/-/services/svc%3Alab-k0s/devices')

  while IFS= read -r node_id; do
    curl --fail-with-body --silent --show-error \
      --request POST \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      --data '{"approved":true}' \
      "https://api.tailscale.com/api/v2/tailnet/-/services/svc%3Alab-k0s/device/${node_id}/approved"
  done < <(jq -r '.hosts[].nodeId' <<<"$hosts")
)

kubectl wait proxygroup/lab-k0s \
  --for=condition=ProxyGroupReady=true \
  --timeout=5m
```

The API token inherits its owner's authority and expires in at most 90 days.
Keep it encrypted, rotate or revoke it after use, and do not distribute it with
the runbook.

Bind Tailscale identities to the least Kubernetes privilege they require. The
lab owner's login is stored at `tailscale.kubernetes_user`; load it without
printing it. This personal lab grants that owner `cluster-admin`:

```bash
(
  set -euo pipefail
  kubernetes_user=$(sops decrypt \
    --extract '["tailscale"]["kubernetes_user"]' \
    secrets/lab.sops.yaml)
  trap 'unset kubernetes_user' EXIT

  kubectl create clusterrolebinding tailscale-lab-k0s-admin \
    --clusterrole=cluster-admin \
    --user="$kubernetes_user" \
    --dry-run=client -o yaml | kubectl apply -f -
)
```

Confirm the exact impersonated identity with `kubectl auth whoami`. Before
sharing the lab, create separate `view` or namespace-scoped bindings for guest
logins such as `<GUEST_TAILSCALE_LOGIN>`; do not add guests to the owner
`cluster-admin` binding.

Configure a client and verify its identity:

```bash
proxy_url=$(kubectl get proxygroup lab-k0s -o jsonpath='{.status.url}')
tailscale configure kubeconfig "$proxy_url"
kubectl auth whoami
kubectl get nodes
```

Keep the direct `tailscale-k0s` context. The ProxyGroup depends on working Pod
scheduling, Cilium, DNS, and the Kubernetes Service; the direct context remains
the recovery path when those dependencies fail.

## Operations

### Node address changes

Tailscale IPs normally remain stable for a node identity. Recreating a machine
or deleting and re-enrolling its Tailscale device can assign a new address.
Before applying k0s changes:

```bash
uv run scripts/update_k0s_tailscale_ips.py --dry-run
uv run scripts/update_k0s_tailscale_ips.py
k0sctl apply --config docs/k0s/k0s.yaml --dry-run
```

Changing a controller address affects etcd membership and API certificates. Do
not treat it as an ordinary worker replacement; back up etcd and follow the k0s
controller replacement procedure.

### Connectivity degradation

Use these checks before changing Kubernetes configuration:

```bash
tailscale status
tailscale netcheck
tailscale ping control-plane-01
ssh root@node-01 tailscale ping node-02
ssh root@node-01 ip route
```

`tailscale ping` identifies direct versus DERP connectivity. DERP preserves
encryption and correctness but can reduce throughput and increase latency. If a
previously direct cluster becomes relayed, investigate iximiuz firewall/NAT
changes and UDP reachability before tuning Cilium or etcd.

### Safe teardown

Export data and etcd backups before destroying playgrounds. Removing a
playground VM also removes its local k0s state. After teardown:

1. Remove stale machines from the Tailscale admin console.
2. Revoke any remaining enrollment auth key.
3. Remove operator-created Tailscale devices and Services if the Kubernetes
   resources can no longer reconcile their deletion.
4. Remove obsolete direct kubeconfig credentials from administrator machines.

## References

- [iximiuz Labs playgrounds](https://labs.iximiuz.com/docs/playgrounds)
- [k0sctl configuration](https://github.com/k0sproject/k0sctl#configuration-file)
- [k0s networking](https://docs.k0sproject.io/stable/networking/)
- [k0s node-local load balancing](https://docs.k0sproject.io/stable/nllb/)
- [Cilium 1.20 Helm reference](https://docs.cilium.io/en/v1.20/helm-reference/)
- [Cilium 1.20 kube-proxy replacement](https://docs.cilium.io/en/v1.20/network/kubernetes/kubeproxy-free/)
- [Cilium 1.20 routing](https://docs.cilium.io/en/v1.20/network/concepts/routing/)
- [Cilium 1.20 cluster-pool IPAM](https://docs.cilium.io/en/v1.20/network/concepts/ipam/cluster-pool/)
- [Tailscale auth keys](https://tailscale.com/docs/features/access-control/auth-keys)
- [Tailscale grants](https://tailscale.com/docs/features/access-control/grants)
- [Tailscale SSH](https://tailscale.com/docs/features/tailscale-ssh)
- [Tailscale connection types](https://tailscale.com/docs/reference/connection-types)
- [Install the Tailscale Kubernetes Operator](https://tailscale.com/docs/kubernetes-operator/install-operator)
- [Kubernetes API access over Tailscale](https://tailscale.com/docs/kubernetes-operator/api-server-access/setup-api-over-tailscale)
- [Tailscale and Cilium compatibility](https://tailscale.com/docs/kubernetes-operator/reference/compatibility)
