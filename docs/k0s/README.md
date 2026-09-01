# Build and operate a k0s cluster over Tailscale

**Owner:** Lab operator | **Frequency:** As needed
**Last updated:** 2026-09-01 | **Last run:** 2026-09-01

This runbook builds and operates an eight-node Kubernetes cluster across two iximiuz Labs playgrounds. Use it for initial deployment, validation, upgrades, recovery, and teardown.

## Plan and scope

This page serves an operator who controls the playgrounds, tailnet, and Kubernetes cluster.

- **Overview:** Build k0s on a private Tailscale underlay and install Cilium
- **Goal:** Deploy and verify a recoverable, kube-proxy-free Kubernetes cluster
- **Audience:** The lab operator responsible for Tailscale and Kubernetes administration
- **Content plan:** Prepare, secure, bootstrap, verify, operate, and remove the cluster
- **Open questions:** Record environment-specific contacts and the last successful run before sharing this runbook

This page is an operational how-to. Open the [interactive architecture](architecture/lab-architecture.html) to explore the system, the [interactive network data paths](architecture/network-data-paths.html) to trace packet flows, the [private Hubble HTTPS architecture](architecture/hubble-private-https.html) to inspect service and certificate ownership, the [DNS-01 issuance sequence](architecture/hubble-dns01.html) to follow certificate provisioning, or the [interactive bootstrap journey](architecture/bootstrap-journey.html) to explore the deployment sequence.

## Purpose

The procedure joins eight Debian hosts through Tailscale and bootstraps k0s with `k0sctl`. Cilium supplies the Pod network without kube-proxy.

The cluster uses three network layers:

| Layer | Classless Inter-Domain Routing (CIDR) range or interface | Purpose |
| --- | --- | --- |
| Node underlay | `tailscale0`, `100.64.0.0/10` | Carries Secure Shell (SSH), etcd, the Kubernetes application programming interface (API), kubelet, and Virtual Extensible LAN (VXLAN) traffic |
| Pod network | `10.244.0.0/16` | Assigns one `/24` range to each worker through Cilium |
| Service network | `10.96.0.0/12` | Assigns virtual Kubernetes Service addresses |

Do not advertise the Pod or Service CIDR through a Tailscale subnet route. Tailnet clients access services through Tailscale identities instead.

## Architecture requirements

Keep these requirements true throughout the cluster lifecycle:

- Every host has a unique, stable hostname and Tailscale IPv4 address
- Every host remains in one tailnet with policy-authorized peer connectivity
- `privateAddress` and `privateInterface` select `tailscale0` for k0s traffic
- `api.onlyBindToAddress: true` excludes iximiuz Labs `172.16.0.x` addresses
- Every controller name and Tailscale Internet Protocol (IP) address appears in the certificate Subject Alternative Name (SAN) list
- Pod, Service, playground local area network (LAN), and routed CIDR ranges do not overlap
- Cilium uses VXLAN because Tailscale does not route the Pod CIDR
- Workers retain Internet egress for registries, Tailscale coordination, and Designated Encrypted Relay for Packets (DERP)

Controllers do not run workloads. `kubectl get nodes` lists five workers. Use `k0s status` and `k0s etcd member-list` to inspect controllers.

[![k0s lab architecture](architecture/lab-architecture.svg)](architecture/lab-architecture.svg)

[![k0s bootstrap journey](architecture/bootstrap-journey.svg)](architecture/bootstrap-journey.svg)

## Network data paths

The diagram uses one representative source worker and one destination worker. The same stages apply to every pair among the five workers. Controllers run no workload Pods.

[![Kubernetes network data paths](architecture/network-data-paths.svg)](architecture/network-data-paths.svg)

Open the [interactive network data-path diagram](architecture/network-data-paths.html) and select a guided view to isolate cross-node, same-node, Service-backend, or Internet-egress traffic.

| Flow | Forward data path | Address and encapsulation behavior |
| --- | --- | --- |
| Node to node | Host process → Linux routing → `tailscale0` → peer `tailscale0` → destination host process | Uses `100.64.0.0/10` node addresses. Tailscale encrypts with WireGuard and prefers a direct peer path; DERP is an encrypted fallback. |
| Controller to controller | Controller service → `tailscale0` → peer controller | Kubernetes control traffic uses TCP `6443`; etcd client traffic uses TCP `2379`, and etcd peer quorum uses TCP `2380`. |
| Worker to controller | kubelet, Cilium, or another worker component → worker-local Envoy `127.0.0.1:7443` → selected controller `100.x:6443` over `tailscale0` | k0s node-local load balancing retries healthy controllers. It provides in-cluster API availability, not an external virtual IP. |
| Pod to same node | Pod `eth0` → host-side veth → source Cilium eBPF policy and routing → destination endpoint eBPF policy → destination veth | The packet keeps Pod IP addresses and never enters `cilium_vxlan` or `tailscale0`. |
| Pod to another node | Pod `eth0` → veth eBPF → `cilium_vxlan` encapsulation → UDP `8472` with remote `100.x` node destination → `tailscale0` → remote VXLAN decapsulation → ingress policy → destination veth | Inner source and destination remain `10.244.x.y`. VXLAN adds 50 bytes; Tailscale encrypts the outer node packet. Cilium MTU `1230` fits inside `tailscale0` MTU `1280`. |
| Pod to node process | Pod `eth0` → veth eBPF → host routing → local node socket, or VXLAN/Tailscale first when the node is remote | Cilium applies endpoint policy before host delivery. Host-network traffic is outside the Pod veth path. |
| Pod to ClusterIP Service | Pod → veth eBPF Service lookup → selected backend Pod → same-node or cross-node Pod path | `10.96.0.0/12` is virtual and is never routed through Tailscale. With `socketLB.hostNamespaceOnly: true`, Pod namespaces use the tc eBPF load balancer on the veth. |
| Tailnet client to Kubernetes API | Client → Tailscale Service HTTPS `443` → one API ProxyGroup Pod → API server `6443` | In auth mode, the proxy derives impersonation headers from Tailscale identity; Kubernetes RBAC makes the authorization decision. The direct client-certificate context remains the recovery path. |
| Tailnet client to NodePort | Client → node `100.x:NodePort` on `tailscale0` → Cilium eBPF Service lookup → local or remote backend | `nodePort.directRoutingDevice: tailscale0` selects the ingress device. The default Cilium load-balancer mode is SNAT; remote backends then use the cross-node path. |
| Pod to Internet | Pod → veth eBPF policy → Linux route → BPF masquerade on `eth0` → Internet | Cilium changes the source Pod IP to the worker `eth0` address. The reply is reverse-translated through BPF connection tracking and delivered to the Pod. |
| Pod DNS lookup | Pod → CoreDNS ClusterIP → Cilium Service lookup → selected CoreDNS Pod | Backend delivery follows the same-node or cross-node Pod path. No Layer 7 DNS proxy is in the path unless a Cilium DNS policy requires it. |

Reply packets traverse the corresponding stages in reverse. Cilium connection tracking restores Service and masquerade translations; a cross-node reply is independently VXLAN-encapsulated and WireGuard-encrypted between the two worker Tailscale addresses.

Do not advertise `10.244.0.0/16` or `10.96.0.0/12` as Tailscale subnet routes. Cilium owns those ranges, while Tailscale carries only the node underlay and explicitly exposed Tailscale Services.

## Tested versions

Treat these versions as one tested set. Validate upgrades in a fresh playground before changing a shared cluster.

| Component | Version |
| --- | --- |
| k0sctl | `v0.32.2` |
| k0s and Kubernetes | `v1.36.4+k0s.0` |
| Cilium | `v1.20.1` |
| Tailscale Kubernetes Operator | `1.102.3` |
| cert-manager | `v1.21.1` |
| ingress-nginx | chart `4.15.1`, controller `v1.15.1` |
| Envoy Gateway | `v1.9.1` |
| ExternalDNS | chart `1.21.1`, controller `v0.21.0` |
| Echo Server | `0.9.2` |
| kube-prometheus-stack | chart `88.6.2`, Prometheus Operator `v0.93.1` |
| Sonobuoy | `v0.57.5` |

The repository pins client tools in [`../../mise.toml`](../../mise.toml).

## Prerequisites

Complete every prerequisite before changing the cluster:

- [ ] Start both playgrounds from the repository [deployment guide](../../README.md)
- [ ] Obtain administrator access to the Tailscale tailnet
- [ ] Connect the control host to the same tailnet
- [ ] Obtain SSH root access to all eight hosts
- [ ] Configure SOPS access for `secrets/lab.sops.yaml`
- [ ] Install `mise`, `uv`, Tailscale, and the repository tools
- [ ] Confirm that no accepted route overlaps the Pod or Service CIDR
- [ ] Schedule an outage and back up data before disruptive changes

The machine hostnames must match [`k0s.yaml`](k0s.yaml):

```text
control-plane-01  control-plane-02  control-plane-03
node-01           node-02           node-03  node-04  node-05
```

## Procedure

Follow the steps in order for a new deployment. For recurring operations, start at the relevant step and preserve all preceding requirements.

### Step 1: Prepare the control host

Install the pinned tools and run the address-updater tests from the repository root:

```bash
mise install
mise ls --local
uv sync --locked
uv run --locked python -m unittest \
  scripts/test_update_k0s_tailscale_ips.py -v
```

**Expected result:** `mise` lists the local tools, and the unit tests pass.

**If it fails:** Resolve missing tool versions or Python dependencies before continuing. Do not bootstrap with an untested updater.

### Step 2: Configure the tailnet policy

Create a policy from [`tailnet-policy.hujson`](tailnet-policy.hujson). Replace `tailscale_login` with the login from `tailscale status`.

The example retains this personal lab's wildcard grant. That grant allows every source to reach every destination. It also makes the narrower API grant redundant for network authorization.

Before inviting another member, replace the wildcard with reviewed grants for:

- Administrator access
- `tag:lab` cluster ports between nodes
- The `tag:k8s` API endpoint

An empty tag-owner list restricts assignment to administrator auth keys or scoped operator credentials. The exact `svc:lab-k0s` approver prevents the operator from advertising other Tailscale Services.

Tailscale SSH policy and network grants are separate controls. The `check` action periodically reauthenticates administrators before granting root access.

**Expected result:** The Tailscale policy editor accepts the policy without warnings.

**If it fails:** Validate the login, tags, and HuJSON syntax. Do not weaken the policy to bypass validation.

### Step 3: Enroll every playground machine

Create a preapproved, reusable auth key for `tag:lab`. Store it at `tailscale.auth_key` in [`../../secrets/lab.sops.yaml`](../../secrets/lab.sops.yaml). Revoke the key immediately after enrolling all eight machines.

If this tailnet previously contained machines with the same hostnames, remove those stale device records before enrollment. Duplicate names receive suffixed MagicDNS names such as `node-01-1`, and the address updater intentionally rejects duplicate hostnames. Delete only records confirmed offline and belonging to destroyed playground sessions; never remove a live or unrelated device to make validation pass. Allow MagicDNS to converge before reusing canonical names.

From the control host, enroll one machine at a time. Replace `playground_id` with the playground run ID and `node_name` with the machine name:

```bash
sops decrypt --extract '["tailscale"]["auth_key"]' \
  secrets/lab.sops.yaml | labctl ssh playground_id \
  --machine node_name --user root -- \
  install -m 600 /dev/stdin /run/tailscale-auth-key

labctl ssh playground_id --machine node_name --user root -- \
  tailscale up \
  --auth-key=file:/run/tailscale-auth-key \
  --advertise-tags=tag:lab \
  --ssh
labctl ssh playground_id --machine node_name --user root -- \
  rm -f /run/tailscale-auth-key
```

Repeat enrollment for all eight nodes. A one-use key can enroll only one machine and is not suitable for this procedure.

Never place auth keys in shell history, manifests, plaintext Git files, or command arguments. Do not enable `--accept-routes` without an explicit routed-subnet requirement and a CIDR review.

**Expected result:** `tailscale status` shows eight online devices with `tag:lab`.

**If it fails:** Remove the temporary key file. Check key expiry, tag ownership, node time, and Tailscale connectivity before retrying.

### Step 4: Verify the Tailscale underlay

Confirm peer discovery and SSH access from the control host:

```bash
tailscale status
tailscale ping control-plane-01
tailscale ping control-plane-02
tailscale ping control-plane-03
tailscale ping node-01
ssh root@control-plane-01 hostname
ssh root@node-01 hostname
```

Inspect one controller and one worker:

```bash
ssh root@control-plane-01 \
  'tailscale status; tailscale netcheck; ip -br addr show tailscale0'
ssh root@node-01 \
  'tailscale status; tailscale netcheck; ip -br addr show tailscale0'
```

Check cluster routes on the control host and nodes:

```bash
ip route get 10.244.0.1
ip route get 10.96.0.1
```

Before Cilium installation, neither address may use another virtual private network (VPN) or subnet router.

**Expected result:** Every peer responds, hostnames are unique, and `tailscale0` has a `100.x` address. Direct paths offer better latency, but DERP paths remain functional.

`tailscale ping` exits nonzero when it receives DERP replies but cannot establish a direct path. In that case, confirm that the output contains successful `pong` replies, then use SSH and `tailscale netcheck` to distinguish functional DERP connectivity from a failed peer.

**If it fails:** Stop the deployment. Resolve missing peers, duplicate hostnames, intermittent links, or route overlap first.

### Step 5: Populate Tailscale addresses

Discover tailnet-specific addresses and preview the change:

```bash
uv run scripts/update_k0s_tailscale_ips.py --dry-run
uv run scripts/update_k0s_tailscale_ips.py
git diff -- docs/k0s/k0s.yaml
```

The updater requires every configured hostname to be online. It rejects duplicate names, reused addresses, and addresses outside `100.64.0.0/10`.

The updater changes only these values:

- Each host's `ssh.address`
- Each host's `privateAddress`
- Controller IPs in the API certificate SAN list

**Expected result:** The diff changes only the listed address fields.

**If it fails:** Restore connectivity or correct duplicate identities. Do not manually bypass updater validation.

### Step 6: Validate and bootstrap k0s

Inspect the generated configuration before applying it:

```bash
k0sctl apply --config docs/k0s/k0s.yaml --dry-run
```

Each controller's `spec.api.address` must use its Tailscale IP. Join validation must not use an iximiuz Labs `172.16.0.x` address.

Apply the validated configuration:

```bash
k0sctl apply --config docs/k0s/k0s.yaml
```

`spec.options.wait.enabled` remains `false`. Workers stay `NotReady` until Cilium starts because k0s uses a custom Container Network Interface (CNI).

Validate the control plane and etcd membership:

```bash
ssh root@control-plane-01 k0s status
ssh root@control-plane-02 k0s status
ssh root@control-plane-03 k0s status
ssh root@control-plane-01 k0s etcd member-list
ssh root@control-plane-01 k0s kubectl get nodes -o wide
```

**Expected result:** etcd lists three controller Tailscale addresses. Kubernetes lists five `NotReady` workers with `100.x` InternalIP values.

**If it fails:** Check `api.onlyBindToAddress: true`. Inspect the selected API address, then reconcile with `k0sctl`:

```bash
ssh root@control-plane-01 \
  "journalctl -u k0scontroller --no-pager | grep 'using api address'"
k0sctl apply --config docs/k0s/k0s.yaml --dry-run
k0sctl apply --config docs/k0s/k0s.yaml
```

### Step 7: Configure recovery API access

Create a protected admin kubeconfig without overwriting an existing file:

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

This kubeconfig contains a privileged client certificate. It connects directly to the first controller, so protect it as a recovery credential.

The design has no external virtual IP. Every controller address appears in the certificate SAN list. During recovery, an administrator can point the kubeconfig at another controller.

Do not set `spec.api.externalAddress` with k0s node-local load balancing. k0s does not support that combination.

**Expected result:** The context is `tailscale-k0s`, and `/readyz` returns `ok`.

**If it fails:** Confirm controller health, certificate SAN entries, Tailscale routes, and file permissions.

### Step 8: Install Cilium

Install Cilium with the checked-in values:

```bash
cilium install \
  --version 1.20.1 \
  --values docs/k0s/cilium-values.yaml
cilium status --wait
```

These settings bind Cilium to the Tailscale underlay:

- `k8sServiceHost: 127.0.0.1` and port `7443` use the worker-local API proxy
- `nodePort.directRoutingDevice: tailscale0` selects the node underlay
- `devices: [eth0, tailscale0]` selects the stable lab interfaces
- `routingMode: tunnel` and `tunnelProtocol: vxlan` tunnel Pod traffic
- `MTU: 1230` fits VXLAN within Tailscale's `1280` byte maximum transmission unit (MTU)
- `socketLB.hostNamespaceOnly: true` supports Tailscale operator proxy Pods

The configuration omits optional Layer 7 routing and encryption features. Tailscale encrypts the node underlay.

Hubble Relay may warn that its server listener lacks Transport Layer Security (TLS). The `ClusterIP` Service limits Relay access to the Hubble user interface (UI). Configure server TLS and client authentication before external exposure.

Do not raise the Pod MTU without measurements across every node pair. Encapsulation errors can stall large requests while health checks pass.

**Expected result:** `cilium status --wait` reports healthy agents and operators.

**If it fails:** Check the API proxy, selected devices, MTU, image pulls, and Cilium Pod logs.

### Step 9: Verify cluster networking

Check node readiness and system workloads:

```bash
kubectl get nodes -o wide
kubectl -n kube-system get pods -o wide
kubectl -n kube-system get daemonset kube-proxy
cilium status --wait
```

Run focused connectivity tests after bootstrap, network changes, and Cilium upgrades:

```bash
(
  set -euo pipefail
  context=tailscale-k0s
  cilium hubble port-forward \
    --context "$context" >/tmp/hubble-port-forward.log 2>&1 &
  port_forward_pid=$!
  trap 'kill "$port_forward_pid" 2>/dev/null || true; \
    cilium connectivity test --context "$context" --cleanup' EXIT

  until timeout 1 bash -c '</dev/tcp/127.0.0.1/4245' 2>/dev/null; do
    kill -0 "$port_forward_pid"
    sleep 1
  done

  hubble status --server localhost:4245

  cilium connectivity test \
    --context "$context" \
    --ip-families ipv4 \
    --test '^no-policies/' \
    --test '^client-egress/' \
    --flow-validation disabled \
    --junit-file /tmp/cilium-connectivity-junit.xml \
    --timeout 15m
)
```

The selectors test Pod traffic, ClusterIP and NodePort Services, Domain Name System (DNS), and client egress. They omit the `dns-only` Layer 7 test because this cluster has no Envoy proxy. The explicit Hubble status check verifies Relay access. Per-action flow matching remains disabled because socket load balancing can translate a ClusterIP before Hubble observes the flow; traffic test failures remain fatal.

Always run cleanup after a failed or interrupted test. The tested configuration executes 70 actions.

Inspect the effective MTU and peer path:

```bash
ssh root@node-01 ip -d link show tailscale0
ssh root@node-01 ip -d link show cilium_vxlan
kubectl -n kube-system exec daemonset/cilium -- \
  cilium-dbg status --verbose | grep -i mtu
ssh root@node-01 tailscale ping node-02
```

**Expected result:** Five workers are `Ready`. System Pods run, kube-proxy is absent, `tailscale0` reports MTU `1280`, and Cilium routes report MTU `1230`.

**If it fails:** Run cleanup, retain the JUnit file, and use the troubleshooting table before changing configuration.

### Step 10: Run Kubernetes conformance tests

Install the tested Sonobuoy version without changing repository pins:

```bash
mise install sonobuoy@0.57.5
mise exec sonobuoy@0.57.5 -- sonobuoy version
```

After bootstrap, run Sonobuoy's `quick` mode to validate the harness:

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

Before a Kubernetes, k0s, or Cilium upgrade, run the non-disruptive profile. This lab completes it in about two hours:

```bash
(
  set -euo pipefail
  context=tailscale-k0s
  trap 'mise exec sonobuoy@0.57.5 -- sonobuoy \
    --context "$context" delete --all --wait' EXIT

  mise exec sonobuoy@0.57.5 -- sonobuoy \
    --context "$context" run \
    --mode non-disruptive-conformance --wait
  results=$(mise exec sonobuoy@0.57.5 -- sonobuoy \
    --context "$context" retrieve /tmp)
  mise exec sonobuoy@0.57.5 -- sonobuoy results "$results"
)
```

The tested set completed 451 end-to-end (e2e) tests with zero failures. All five `systemd-logs` plugins passed in 1 hour 51 minutes.

Run certification only on an empty cluster with backups and an outage window:

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

The tested set completed 453 e2e tests with zero failures. All five node-log plugins passed in about two hours.

**Expected result:** The selected profile reports zero failed e2e tests and five passing log plugins.

**If it fails:** Preserve the archive and inspect every failure. A passing isolated rerun does not replace the failed full-run result.

### Step 11: Configure identity-based API access when needed

Use the direct kubeconfig for bootstrap and recovery. Install the Tailscale Kubernetes Operator when shared access needs Tailscale identity and Kubernetes role-based access control (RBAC).

The tailnet policy must include `tag:k8s-operator`, `tag:k8s`, grants, and the Service approver. Enable Hypertext Transfer Protocol Secure (HTTPS) on the [Tailscale DNS settings page](https://login.tailscale.com/admin/dns).

Create an Open Authorization (OAuth) client with `tag:k8s-operator` and these write scopes:

- General / Services
- Devices / Core
- Keys / Auth Keys

Store the values in the encrypted secrets file:

```yaml
tailscale:
  access_token: tailscale_api_access_token
  auth_key: tagged_lab_auth_key
  oauth:
    client_id: tailscale_operator_oauth_client_id
    client_secret: tailscale_operator_oauth_client_secret
  kubernetes_user: tailscale_login
```

Edit secrets only with `sops secrets/lab.sops.yaml`. Disable shell tracing before handling credentials.

Create the namespace:

```bash
kubectl create namespace tailscale
```

Create the OAuth Secret without exposing credentials in command arguments:

```bash
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
  sops decrypt --extract \
    '["tailscale"]["oauth"]["client_id"]' \
    secrets/lab.sops.yaml >"$oauth_dir/client_id"
  sops decrypt --extract \
    '["tailscale"]["oauth"]["client_secret"]' \
    secrets/lab.sops.yaml >"$oauth_dir/client_secret"

  kubectl -n tailscale create secret generic operator-oauth \
    --from-file=client_id="$oauth_dir/client_id" \
    --from-file=client_secret="$oauth_dir/client_secret" \
    --dry-run=client -o yaml | kubectl apply -f -
)
```

Kubernetes Secrets need API-server encryption for encryption at rest. Use an external secret controller when the environment provides one.

Install the operator:

```bash
helm upgrade --install tailscale-operator \
  tailscale-operator \
  --repo https://pkgs.tailscale.com/helmcharts \
  --version 1.102.3 \
  --namespace tailscale \
  --set-string apiServerProxyConfig.allowImpersonation=true \
  --wait
kubectl -n tailscale rollout status deployment/operator --timeout=5m
```

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
```

The URL follows `https://lab-k0s.tailnet_dns_name.ts.net`.

#### Understand identity impersonation

The API proxy in `auth` mode converts a Tailscale identity into a Kubernetes identity. It does not issue each tailnet user a Kubernetes client certificate, and reaching the proxy does not grant Kubernetes permissions.

[![Tailscale identity to Kubernetes RBAC](architecture/api-impersonation.svg)](architecture/api-impersonation.svg)

Open the [interactive impersonation sequence](architecture/api-impersonation.html) to isolate tailnet authentication, impersonation, and resource authorization.

Each request crosses three independent authorization boundaries:

1. Tailscale authenticates the calling user or tagged device. Tailnet grants decide whether that identity can reach the proxy on HTTPS port `443`.
2. The ProxyGroup authenticates to the Kubernetes API with its own workload credential and forwards `Impersonate-User` and, when applicable, `Impersonate-Group` headers. Kubernetes verifies that the ProxyGroup may impersonate those identity categories.
3. Kubernetes evaluates the requested verb and resource as the impersonated user and groups. A matching `RoleBinding` or `ClusterRoleBinding` permits the operation; otherwise the API returns `403 Forbidden`.

The request therefore carries two identities:

| Identity | Meaning | Authorization purpose |
| --- | --- | --- |
| ProxyGroup transport identity | The proxy workload that authenticated to the API server | Must be allowed to impersonate users and groups |
| Effective identity | The Tailscale user, device, and mapped groups in the impersonation headers | Must be allowed to perform the requested Kubernetes operation |

The Helm value `apiServerProxyConfig.allowImpersonation=true` provisions the operator RBAC for the first Kubernetes check. It does not grant the effective user access to resources. The later `tailscale-lab-k0s-admin` binding grants the owner’s Tailscale login its Kubernetes role.

The proxy derives headers from the caller:

| Tailscale caller | `Impersonate-User` | `Impersonate-Group` |
| --- | --- | --- |
| User-owned device | Tailscale login, such as `alice@example.com` | Groups supplied by matching Tailscale Kubernetes capability grants, when configured |
| Tagged device | Device fully qualified domain name (FQDN) | Groups supplied by matching capability grants; without those grants, the device tags are used as groups |

This lab currently binds the owner login directly as a Kubernetes user. The checked-in tailnet policy grants network access to `tag:k8s` but does not map a Tailscale group to a Kubernetes group. For shared access, prefer a purpose-specific group such as `tailnet-readers`, map it with a Tailscale Kubernetes capability grant, and bind that group to `view` or a namespace-scoped role. Do not map routine users to `system:masters`.

Verify the effective identity and authorization result through the proxy context:

```bash
kubectl --context lab-k0s.tailnet_dns_name.ts.net auth whoami
kubectl --context lab-k0s.tailnet_dns_name.ts.net auth can-i get pods --all-namespaces
```

Keep the direct `tailscale-k0s` context separate. It uses a privileged Kubernetes client certificate rather than Tailscale impersonation and remains the recovery path.

If readiness stalls, inspect the advertised Service:

```bash
kubectl get proxygroup lab-k0s -o jsonpath='\
{range .status.conditions[*]}{.type}{"="}{.status}{": "}\
{.message}{"\n"}{end}'
```

Prefer the exact `svc:lab-k0s` auto-approver. If policy approval is unavailable, approve only the operator-created backends with the encrypted API token:

```bash
(
  set -euo pipefail
  token=$(sops decrypt --extract \
    '["tailscale"]["access_token"]' secrets/lab.sops.yaml)
  trap 'unset token' EXIT
  api='https://api.tailscale.com/api/v2/tailnet/-/services'
  hosts=$(curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $token" \
    "$api/svc%3Alab-k0s/devices")
  while IFS= read -r node_id; do
    curl --fail-with-body --silent --show-error \
      --request POST \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      --data '{"approved":true}' \
      "$api/svc%3Alab-k0s/device/${node_id}/approved"
  done < <(jq -r '.hosts[].nodeId' <<<"$hosts")
)
```

Rotate or revoke the owner-scoped API token after use. Tailscale API tokens expire within 90 days.

Grant the owner administrator access without printing the identity:

```bash
(
  set -euo pipefail
  kubernetes_user=$(sops decrypt --extract \
    '["tailscale"]["kubernetes_user"]' secrets/lab.sops.yaml)
  trap 'unset kubernetes_user' EXIT

  kubectl create clusterrolebinding tailscale-lab-k0s-admin \
    --clusterrole=cluster-admin \
    --user="$kubernetes_user" \
    --dry-run=client -o yaml | kubectl apply -f -
)
```

Create separate `view` or namespace-scoped bindings for guests. Never add a guest login to the owner binding.

Configure the client and verify its identity:

```bash
proxy_url=$(kubectl get proxygroup lab-k0s \
  -o jsonpath='{.status.url}')
tailscale configure kubeconfig "$proxy_url"
kubectl auth whoami
kubectl get nodes
```

Keep the direct `tailscale-k0s` context. It remains the recovery path when cluster DNS, Cilium, or ProxyGroup fails.

**Expected result:** `ProxyGroupReady` is true. Two proxy Pods run on different workers, and `kubectl auth whoami` reports the Tailscale login.

**If it fails:** Check operator logs, Service approval, OAuth scopes, tailnet HTTPS, RBAC bindings, and Pod placement.

### Step 12: Expose Hubble UI through Tailscale with HTTPS

Hubble Relay and Hubble UI are enabled by [`cilium-values.yaml`](cilium-values.yaml). Install cert-manager and ingress-nginx to terminate browser-trusted TLS without changing Cilium's Helm-owned `hubble-ui` ClusterIP Service:

[![Private Hubble UI HTTPS architecture](architecture/hubble-private-https.svg)](architecture/hubble-private-https.html)

The request and certificate paths are deliberately separate. Cloudflare is authoritative for the public DNS records used by the custom hostname and ACME validation, but it does not proxy Hubble UI traffic. The DNS-only `A` record returns a private Tailscale address; a policy-authorized tailnet client then connects through the Tailscale Service to ingress-nginx, which terminates TLS and forwards HTTP to Cilium's `hubble-ui` Service.

#### How ingress-nginx and its load balancer are provisioned

This deployment separates the ingress controller from its external entry point:

1. Helm installs the `IngressClass/nginx`, the ingress-nginx controller `Deployment`, its admission webhook, RBAC, and controller `ConfigMap`. `controller.service.enabled=false` deliberately prevents the chart from creating its usual public-facing controller Service.
2. The hand-authored `Ingress/hubble-ui` declares host and path routing. The ingress-nginx controller watches resources whose `ingressClassName` is `nginx`, resolves the referenced `hubble-ui` Service endpoints, reads `Secret/hubble-ui-tls`, and renders those objects into its running NGINX configuration.
3. `ProxyGroup/lab-ingress` maintains two shared ingress proxy Pods. The separate `Service/ingress-nginx/hubble-ui-tailscale` selects the ingress-nginx controller Pod, declares `type: LoadBalancer` with `loadBalancerClass: tailscale`, and attaches to that ProxyGroup.
4. The Tailscale operator creates `svc:hubble-ui`, configures both ProxyGroup replicas to advertise its stable `100.x` virtual IP, and writes that address and `*.ts.net` name into the Service status.
5. Either ProxyGroup replica forwards ports 80 and 443 to the Service ClusterIP. Kubernetes service routing selects the ingress-nginx Pod; ingress-nginx terminates TLS, matches the host and path from the Ingress, and connects directly to a Hubble UI endpoint.

The `LoadBalancer` Service therefore represents desired state, not an external appliance. Its Tailscale Service virtual IP is advertised by both shared ProxyGroup replicas. Removing the Service removes its routing and advertisement without removing the shared proxies; changing the Ingress only changes NGINX routing.

```bash
helm upgrade --install cert-manager \
  oci://quay.io/jetstack/charts/cert-manager \
  --version v1.21.1 \
  --namespace cert-manager \
  --create-namespace \
  --set crds.enabled=true \
  --kube-context tailscale-k0s \
  --wait

helm upgrade --install ingress-nginx \
  ingress-nginx \
  --repo https://kubernetes.github.io/ingress-nginx \
  --version 4.15.1 \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.service.enabled=false \
  --kube-context tailscale-k0s \
  --wait
```

Create the Cloudflare API token Secret without exposing the credential in command arguments. The token needs `Zone - DNS - Edit` and `Zone - Zone - Read` for `canhdinh.com`:

```bash
(
  set -e
  if [[ $- == *x* ]]; then
    printf 'Disable shell tracing before handling Cloudflare credentials.\n' >&2
    exit 1
  fi
  token_file=$(mktemp)
  trap 'rm -f "$token_file"' EXIT
  umask 077
  sops decrypt --extract \
    '["cloudflare"]["cert_manager_api_token"]' \
    secrets/lab.sops.yaml >"$token_file"

  kubectl --context tailscale-k0s -n kube-system \
    create secret generic cloudflare-api-token \
    --from-file=api-token="$token_file" \
    --dry-run=client -o yaml | \
    kubectl --context tailscale-k0s apply -f -
)
```

Render the ACME email from SOPS, apply the issuer, certificate, ingress, and Tailscale Service, then wait for issuance:

[![Cloudflare DNS-01 certificate sequence](architecture/hubble-dns01.svg)](architecture/hubble-dns01.html)

```bash
(
  set -euo pipefail
  ACME_EMAIL=$(sops decrypt --extract \
    '["acme"]["email"]' secrets/lab.sops.yaml)
  export ACME_EMAIL
  trap 'unset ACME_EMAIL' EXIT
  envsubst <docs/k0s/hubble-ui-tls.yaml | \
    kubectl --context tailscale-k0s apply -f -
)

kubectl --context tailscale-k0s apply \
  -f docs/k0s/ingress-proxygroup.yaml
kubectl --context tailscale-k0s wait proxygroup/lab-ingress \
  --for=condition=ProxyGroupAvailable=true \
  --timeout=5m

kubectl --context tailscale-k0s apply \
  -f docs/k0s/hubble-ui-tailscale.yaml
kubectl --context tailscale-k0s -n kube-system \
  wait certificate/hubble-ui --for=condition=Ready=True \
  --timeout=5m
kubectl --context tailscale-k0s -n ingress-nginx \
  wait service/hubble-ui-tailscale \
  --for=jsonpath='{.status.conditions[?(@.type=="TailscaleIngressSvcConfigured")].status}'=True \
  --timeout=5m
```

The Tailscale operator preserves the existing `hubble-ui` endpoint and stable `100.x` Service address while routing ports `80` and `443` to ingress-nginx. The Cloudflare `A` record for `hubble-ui.playground.canhdinh.com` must point to that address with **DNS only** proxy status. Cloudflare's public reverse proxy cannot reach a tailnet-only `100.64.0.0/10` origin. DNS-01 uses temporary `_acme-challenge` TXT records and does not make the application public.

Verify certificate identity, redirect behavior, and private HTTPS access from a tailnet client:

```bash
dig +short hubble-ui.playground.canhdinh.com A
tailscale ping hubble-ui
curl --fail --show-error \
  --head http://hubble-ui.playground.canhdinh.com/
curl --fail --show-error \
  --head https://hubble-ui.playground.canhdinh.com/
openssl s_client \
  -connect hubble-ui.playground.canhdinh.com:443 \
  -servername hubble-ui.playground.canhdinh.com </dev/null 2>/dev/null | \
  openssl x509 -noout -issuer -subject -dates
```

**Expected result:** DNS returns the Service's `100.x` address, HTTP redirects to HTTPS, the certificate subject covers `hubble-ui.playground.canhdinh.com`, and HTTPS returns the Hubble UI only from a policy-authorized tailnet client. cert-manager renews the certificate and ingress-nginx reloads the updated Secret automatically.

**Client IP limitation:** This deployment exposes ingress-nginx through a Tailscale Layer 3 `LoadBalancer` Service. The selected ProxyGroup Pod forwards the connection to ingress-nginx, so ingress-nginx sees that proxy Pod IP rather than the tailnet client's `100.x` address. Setting `externalTrafficPolicy: Local`, `use-forwarded-headers`, or `proxy-real-ip-cidr` cannot recover an address that the Tailscale proxy did not pass in a trusted header or PROXY protocol record. Do not trust arbitrary incoming forwarding headers or enable PROXY protocol unless every connection comes from a trusted sender that emits it.

Track upstream support in [tailscale/tailscale#11024](https://github.com/tailscale/tailscale/issues/11024), with the related Tailscale Serve proxy work in [tailscale/tailscale#14531](https://github.com/tailscale/tailscale/issues/14531). The forwarded-header trust boundary is also documented by [kubernetes/ingress-nginx#9163](https://github.com/kubernetes/ingress-nginx/issues/9163).

Native Tailscale Layer 7 Ingress (`ingressClassName: tailscale`) uses Tailscale Serve and can provide sanitized Tailscale identity headers, but it terminates TLS at Tailscale and uses a tailnet `*.ts.net` hostname and certificate. It is not a drop-in replacement for this custom-domain, cert-manager, ingress-nginx design. Preserving a trustworthy client IP while retaining this design requires a deliberate topology change, such as co-locating Tailscale with ingress-nginx and using required PROXY protocol v2.

Track custom-domain support for the native Layer 7 alternative in [tailscale/tailscale#12709](https://github.com/tailscale/tailscale/issues/12709) and identity metadata for Layer 3 Services in [tailscale/tailscale#15657](https://github.com/tailscale/tailscale/issues/15657).

**If it fails:** Inspect `Certificate`, `Order`, and `Challenge` events; verify the Cloudflare token permissions and public TXT propagation; check ingress-nginx, the `hubble-ui` endpoints, the Tailscale Service and operator logs, the tailnet grant for `tag:k8s` on TCP ports `80` and `443`, and that the application `A` record remains DNS-only.

### Deploy Echo Server through Gateway API

Deploy Envoy Gateway as the Gateway API implementation, expose its managed Envoy Service through the Tailscale operator, and let ExternalDNS maintain the DNS-only Cloudflare record for `echo.playground.canhdinh.com`. The application address remains private: Cloudflare is authoritative for DNS and ACME DNS-01 only, while tailnet policy controls access to the Envoy gateway.

[![Echo Server private Gateway API architecture](architecture/echo-gateway-api.svg)](architecture/echo-gateway-api.html)

#### How Envoy Gateway and its load balancer are provisioned

Gateway API separates infrastructure selection, listener configuration, and application routing:

1. Helm installs the Gateway API and Envoy Gateway CRDs plus the Envoy Gateway controller. `GatewayClass/tailscale` selects that controller and references `EnvoyProxy/envoy-gateway-system/tailscale-proxy` as its infrastructure parameters.
2. The `EnvoyProxy` resource tells Envoy Gateway to create its managed data-plane Service as `type: LoadBalancer` with `loadBalancerClass: tailscale` and the requested Tailscale hostname `gateway-envoy`.
3. `Gateway/echo` requests an HTTPS listener for `echo.playground.canhdinh.com`, references its TLS Secret, and allows routes only from the same namespace. `HTTPRoute/echo` attaches to that listener and maps `/` to `Service/echo-server:80`.
4. The Envoy Gateway controller validates those references, creates and owns an Envoy proxy `Deployment` and its `Service` in `envoy-gateway-system`, and continuously translates the Gateway and HTTPRoute into xDS listener, TLS, route, cluster, and endpoint configuration for Envoy.
5. The generated Service has `loadBalancerClass: tailscale` and attaches to `ProxyGroup/lab-ingress`. The Tailscale operator creates `svc:gateway-envoy`, configures both shared replicas to advertise its `100.x` virtual IP, and publishes the address and `*.ts.net` name to the Service status.
6. Envoy Gateway copies that Service address into `Gateway.status.addresses`. ExternalDNS reads the accepted Gateway and HTTPRoute and synchronizes the custom DNS-only Cloudflare record. cert-manager reads the Gateway annotations and listener certificate reference, completes DNS-01, and maintains the TLS Secret consumed by Envoy.
7. At request time, the client resolves the custom hostname to the private `100.x` address, reaches either advertising ProxyGroup replica, crosses the generated Envoy Service to an Envoy Pod, terminates TLS at Envoy, and follows the HTTPRoute to an Echo Server endpoint.

Unlike the ingress-nginx deployment, the Envoy data-plane Deployment and LoadBalancer Service are generated resources. Change the `Gateway`, `HTTPRoute`, or referenced `EnvoyProxy`; do not hand-edit the generated `envoy-echo-*` resources because the Envoy Gateway controller will reconcile them back to declared state.

Install the pinned Envoy Gateway release. Its chart installs the Gateway API and Envoy Gateway CRDs before starting the controller:

```bash
helm upgrade --install envoy-gateway \
  oci://docker.io/envoyproxy/gateway-helm \
  --version v1.9.1 \
  --namespace envoy-gateway-system \
  --create-namespace \
  --kube-context tailscale-k0s \
  --wait

kubectl --context tailscale-k0s apply \
  -f docs/k0s/envoy-gateway-tailscale.yaml
kubectl --context tailscale-k0s wait gatewayclass/tailscale \
  --for=condition=Accepted=True --timeout=2m
```

Enable cert-manager's Gateway API controller after the CRDs exist, then create the application and controller namespaces:

```bash
helm upgrade cert-manager \
  oci://quay.io/jetstack/charts/cert-manager \
  --version v1.21.1 \
  --namespace cert-manager \
  --set crds.enabled=true \
  --set config.gatewayAPI.enabled=true \
  --kube-context tailscale-k0s \
  --wait

kubectl --context tailscale-k0s create namespace echo
kubectl --context tailscale-k0s create namespace external-dns
```

Create separate least-privilege Cloudflare Secrets for cert-manager and ExternalDNS. Both tokens need `Zone - DNS - Edit` and `Zone - Zone - Read` for `canhdinh.com`. Keep the ClusterIssuer token in cert-manager's cluster resource namespace so application workloads cannot mount it:

```bash
(
  set -euo pipefail
  if [[ $- == *x* ]]; then
    printf 'Disable shell tracing before handling Cloudflare credentials.\n' >&2
    exit 1
  fi
  cert_token_file=$(mktemp)
  dns_token_file=$(mktemp)
  trap 'rm -f "$cert_token_file" "$dns_token_file"' EXIT
  umask 077
  sops decrypt --extract \
    '["cloudflare"]["cert_manager_api_token"]' \
    secrets/lab.sops.yaml >"$cert_token_file"
  sops decrypt --extract \
    '["cloudflare"]["external_dns_api_token"]' \
    secrets/lab.sops.yaml >"$dns_token_file"

  kubectl --context tailscale-k0s -n cert-manager \
    create secret generic cloudflare-api-token \
    --from-file=api-token="$cert_token_file" \
    --dry-run=client -o yaml | \
    kubectl --context tailscale-k0s apply -f -
  kubectl --context tailscale-k0s -n external-dns \
    create secret generic cloudflare-api-token \
    --from-file=api-token="$dns_token_file" \
    --dry-run=client -o yaml | \
    kubectl --context tailscale-k0s apply -f -
)
```

Render the shared ClusterIssuer's ACME contact without writing it to the repository:

```bash
(
  set -euo pipefail
  ACME_EMAIL=$(sops decrypt --extract \
    '["acme"]["email"]' secrets/lab.sops.yaml)
  export ACME_EMAIL
  trap 'unset ACME_EMAIL' EXIT
  envsubst <docs/k0s/cert-manager-cloudflare.yaml | \
    kubectl --context tailscale-k0s apply -f -
)

kubectl --context tailscale-k0s wait \
  clusterissuer/letsencrypt-cloudflare \
  --for=condition=Ready=True --timeout=2m
```

Install ExternalDNS with a `sync` policy, a route and Gateway label filter, a unique TXT owner ID, and an exact Cloudflare zone ID filter. The controller deletes only records it owns when their source routes disappear:

```bash
helm upgrade --install external-dns \
  external-dns \
  --repo https://kubernetes-sigs.github.io/external-dns \
  --version 1.21.1 \
  --namespace external-dns \
  --values docs/k0s/external-dns-values.yaml \
  --kube-context tailscale-k0s \
  --wait
```

Deploy Echo Server `0.9.2`, then wait for the workload, route, certificate, and Tailscale-backed Gateway address:

```bash
kubectl --context tailscale-k0s apply \
  -f docs/k0s/echo-server.yaml

kubectl --context tailscale-k0s -n echo \
  rollout status deployment/echo-server --timeout=5m
kubectl --context tailscale-k0s -n echo \
  wait gateway/echo --for=condition=Programmed=True --timeout=5m
kubectl --context tailscale-k0s -n echo \
  wait certificate/echo-playground-canhdinh-com-tls \
  --for=condition=Ready=True --timeout=5m
kubectl --context tailscale-k0s -n echo \
  wait httproute/echo \
  --for=jsonpath='{.status.parents[0].conditions[?(@.type=="Accepted")].status}'=True \
  --timeout=5m
kubectl --context tailscale-k0s -n envoy-gateway-system \
  wait service \
  -l gateway.envoyproxy.io/owning-gateway-name=echo \
  --for=jsonpath='{.status.conditions[?(@.type=="TailscaleIngressSvcConfigured")].status}'=True \
  --timeout=5m
```

Verify from a policy-authorized tailnet client:

```bash
dig +short echo.playground.canhdinh.com A
tailscale ping gateway-envoy
curl --fail --show-error \
  'https://echo.playground.canhdinh.com/?echo_body=gateway-api'
openssl s_client \
  -connect echo.playground.canhdinh.com:443 \
  -servername echo.playground.canhdinh.com </dev/null 2>/dev/null | \
  openssl x509 -noout -issuer -subject -dates
```

**Expected result:** ExternalDNS creates a DNS-only `A` record containing the Gateway's private `100.x` Tailscale address, cert-manager obtains an ECDSA certificate through Cloudflare DNS-01, the `HTTPRoute` is accepted, and HTTPS returns `"gateway-api"` from Echo Server. Cloudflare never proxies application traffic.

**Client IP limitation:** Echo Server does not see the tailnet client's `100.x` address with this topology. The selected ProxyGroup Pod forwards the connection to Envoy, so Envoy receives the proxy Pod IP and writes that address to `X-Forwarded-For` and `X-Envoy-External-Address`. The generated Envoy Service uses `externalTrafficPolicy: Cluster` so either shared ProxyGroup replica can reach the Envoy Pod on another node. This does not preserve an address across the separate Tailscale proxy hop.

Track the missing source-address handoff in [tailscale/tailscale#11024](https://github.com/tailscale/tailscale/issues/11024), with the related proxy implementation work in [tailscale/tailscale#14531](https://github.com/tailscale/tailscale/issues/14531).

Keep the current configuration unless the topology is deliberately changed. Do not trust an incoming `X-Forwarded-For` header with `ClientTrafficPolicy.clientIPDetection`; clients can supply that header themselves. Do not enable required PROXY protocol on Envoy because the Tailscale LoadBalancer proxy does not emit a PROXY header and connections will be reset. Optional PROXY protocol neither restores the client address nor provides a safe trust boundary. A trustworthy client IP requires a different ingress design, such as placing Tailscale in Envoy's network namespace or introducing a trusted frontend that emits PROXY protocol.

For the downstream trust model, follow [envoyproxy/gateway#8542](https://github.com/envoyproxy/gateway/issues/8542) and [envoyproxy/gateway#7825](https://github.com/envoyproxy/gateway/issues/7825). Envoy Gateway's separate transparent-source forwarding proposal is tracked in [envoyproxy/gateway#3359](https://github.com/envoyproxy/gateway/issues/3359), but it cannot reconstruct an address already replaced by the Tailscale proxy.

**If it fails:** Check Gateway and `HTTPRoute` conditions first, then inspect the Envoy Gateway, Tailscale operator, ExternalDNS, and cert-manager logs. Confirm both Cloudflare tokens are limited to the expected zone, the Gateway address is present, the DNS record is not proxied, and tailnet grants permit clients to reach `gateway-envoy` on TCP `443`.

### Deploy monitoring through Gateway API

Install kube-prometheus-stack to collect cluster and node metrics and run Prometheus, Alertmanager, Grafana, Prometheus Operator, kube-state-metrics, and node-exporter. One Gateway owns three HTTPS listeners and one private Tailscale Service address. Its dedicated `GatewayClass` and `EnvoyProxy` give the generated LoadBalancer Service the unique Tailscale hostname `monitoring-gateway`; one ProxyGroup cannot attach two Services with the same Tailscale hostname. The tailnet policy must auto-approve the exact `svc:monitoring-gateway` identity for `tag:k8s`. Separate routes send each application hostname to its chart-managed ClusterIP Service. cert-manager issues one certificate per listener, and ExternalDNS creates the three DNS-only Cloudflare records from the accepted routes.

Open the [interactive monitoring Gateway API architecture](architecture/monitoring-gateway-api.html) to trace private HTTPS requests, DNS and certificate automation, or controller ownership.

[![Private Kubernetes monitoring through Gateway API](architecture/monitoring-gateway-api.svg)](architecture/monitoring-gateway-api.html)

This cluster has no StorageClass. The checked-in values therefore use ephemeral storage and bound Prometheus retention to three days or 8 GB. Prometheus and Alertmanager history, silences, and Grafana database changes are lost when their Pods are recreated or moved. Add a tested StorageClass and explicit persistence values before treating this as durable production monitoring.

Grafana loads Prometheus's alert and recording rules as read-only data-source-managed rules. Use **Alerting > Alert rules** to inspect rule health and active instances, and select the provisioned Alertmanager data source to inspect active alerts and silences. Alertmanager uses the chart's default null receiver, so no email, chat, paging, or webhook notification leaves the cluster. Grafana does not duplicate or forward these rules.

The k0s controllers do not run as Kubernetes Pods, and kube-proxy is disabled. The values disable the kube-controller-manager, scheduler, etcd, and kube-proxy scrape targets so the deployment does not create permanently failing targets or alerts for components this topology cannot discover.

Install the pinned chart and wait for its controllers and workloads:

```bash
helm upgrade --install monitoring \
  kube-prometheus-stack \
  --repo https://prometheus-community.github.io/helm-charts \
  --version 88.6.2 \
  --namespace monitoring \
  --create-namespace \
  --values docs/k0s/kube-prometheus-stack-values.yaml \
  --kube-context tailscale-k0s \
  --wait \
  --timeout 10m

kubectl --context tailscale-k0s -n monitoring \
  rollout status deployment/monitoring-kube-prometheus-operator --timeout=5m
kubectl --context tailscale-k0s -n monitoring \
  rollout status deployment/monitoring-grafana --timeout=5m
kubectl --context tailscale-k0s -n monitoring \
  rollout status statefulset/prometheus-monitoring-kube-prometheus-prometheus --timeout=5m
kubectl --context tailscale-k0s -n monitoring \
  rollout status statefulset/alertmanager-monitoring-kube-prometheus-alertmanager --timeout=5m
```

Apply the Gateway and routes, then wait for the data plane, certificates, routes, and Tailscale-backed address:

```bash
kubectl --context tailscale-k0s apply \
  -f docs/k0s/monitoring-gateway.yaml

kubectl --context tailscale-k0s wait gatewayclass/monitoring-tailscale \
  --for=condition=Accepted=True --timeout=2m
kubectl --context tailscale-k0s -n monitoring \
  wait gateway/monitoring --for=condition=Programmed=True --timeout=5m
kubectl --context tailscale-k0s -n monitoring \
  wait certificate --all --for=condition=Ready=True --timeout=5m
kubectl --context tailscale-k0s -n monitoring \
  wait httproute --all \
  --for=jsonpath='{.status.parents[0].conditions[?(@.type=="Accepted")].status}'=True \
  --timeout=5m
kubectl --context tailscale-k0s -n envoy-gateway-system \
  wait service \
  -l gateway.envoyproxy.io/owning-gateway-name=monitoring \
  --for=jsonpath='{.status.conditions[?(@.type=="TailscaleIngressSvcConfigured")].status}'=True \
  --timeout=5m
```

The exact `svc:monitoring-gateway` auto-approver in [`tailnet-policy.hujson`](tailnet-policy.hujson) should approve both ProxyGroup backends. If that policy change has not reached the tailnet yet, approve only this Service with the encrypted API token:

```bash
(
  set -euo pipefail
  token=$(sops decrypt --extract \
    '["tailscale"]["access_token"]' secrets/lab.sops.yaml)
  trap 'unset token' EXIT
  api='https://api.tailscale.com/api/v2/tailnet/-/services'
  hosts=$(curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $token" \
    "$api/svc%3Amonitoring-gateway/devices")
  while IFS= read -r node_id; do
    curl --fail-with-body --silent --show-error \
      --request POST \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      --data '{"approved":true}' \
      "$api/svc%3Amonitoring-gateway/device/${node_id}/approved"
  done < <(jq -r '.hosts[].nodeId' <<<"$hosts")
)
```

Rotate or revoke the owner-scoped API token after use.

Retrieve the generated Grafana administrator password without printing it to shell history:

```bash
kubectl --context tailscale-k0s -n monitoring \
  get secret monitoring-grafana \
  -o jsonpath='{.data.admin-password}' | base64 --decode
printf '\n'
```

Create or reconcile the API-managed Kubernetes command-center dashboard from the checked-in definition. A temporary curl configuration keeps the generated password out of command arguments, shell history, and tracked files:

```bash
(
  set -euo pipefail
  password=$(kubectl --context tailscale-k0s -n monitoring \
    get secret monitoring-grafana \
    -o jsonpath='{.data.admin-password}' | base64 --decode)
  payload=$(mktemp)
  curl_config=$(mktemp)
  trap 'unset password; rm -f "$payload" "$curl_config"' EXIT
  chmod 600 "$payload" "$curl_config"

  jq -Rrn --arg credentials "admin:$password" '
    "user = " + ($credentials | @json)
  ' >"$curl_config"
  unset password

  jq '{
    dashboard: .,
    overwrite: true,
    message: "Reconcile Kubernetes cluster command center"
  }' docs/k0s/grafana-kubernetes-dashboard.json >"$payload"

  curl --fail-with-body --silent --show-error \
    --config "$curl_config" \
    --header 'Content-Type: application/json' \
    --data-binary @"$payload" \
    https://grafana.playground.canhdinh.com/api/dashboards/db
)
```

Open `https://grafana.playground.canhdinh.com/d/kubernetes-command-center/kubernetes-cluster-command-center`. The dashboard combines node readiness, Pod health, CPU and memory capacity, restarts, actionable alerts, namespace resource usage, network throughput, API request rate, and unavailable workloads. Use its namespace and node variables for focused investigation, then follow the dashboard links to the chart-provisioned drill-down dashboards.

The API-created dashboard is stored in Grafana's local database and is therefore ephemeral in this cluster. Re-run the reconciliation command after a Grafana Pod replacement until persistent storage or file provisioning is configured.

Verify all three private endpoints from a policy-authorized tailnet client:

```bash
dig +short prometheus.playground.canhdinh.com A
dig +short alertmanager.playground.canhdinh.com A
dig +short grafana.playground.canhdinh.com A
tailscale ping monitoring-gateway
curl --fail --show-error \
  https://prometheus.playground.canhdinh.com/-/ready
curl --fail --show-error \
  https://alertmanager.playground.canhdinh.com/-/ready
curl --fail --show-error --head \
  https://grafana.playground.canhdinh.com/login
```

**Expected result:** The Gateway is programmed with a private `100.x` address, every route is accepted, all three certificates are Ready, Prometheus and Alertmanager return readiness responses, and Grafana returns its login page. All three DNS names resolve to the same DNS-only Tailscale Service address. Cloudflare never proxies application traffic.

**If it fails:** Inspect Gateway listener and route parent conditions first. Then check Prometheus Operator, Envoy Gateway, Tailscale operator, cert-manager, and ExternalDNS logs. Confirm the chart Services and endpoints exist, certificates reference the listener Secrets, records are DNS-only, and tailnet grants permit clients to reach `monitoring-gateway` on TCP `443`.

## Verification

Complete every check before recording a successful run:

- [ ] `kubectl get nodes -o wide` shows five `Ready` workers with Tailscale InternalIP values
- [ ] `k0s etcd member-list` shows three controller Tailscale addresses
- [ ] Cilium, CoreDNS, Hubble, node-local load balancing, and konnectivity Pods run
- [ ] The kube-proxy DaemonSet does not exist
- [ ] Focused Cilium connectivity tests pass and cleanup completes
- [ ] `tailscale0` reports MTU `1280`, while Cilium routes report MTU `1230`
- [ ] The selected Sonobuoy profile reports zero e2e failures
- [ ] Both API paths return `ok` when the ProxyGroup is installed
- [ ] `hubble-ui.playground.canhdinh.com` presents a valid certificate and reaches Hubble UI only from the tailnet
- [ ] The Echo Gateway and route are accepted, its Certificate is ready, and private HTTPS returns the expected body
- [ ] The monitoring Gateway and three routes are accepted, all Certificates are ready, and Prometheus, Alertmanager, and Grafana respond through private HTTPS
- [ ] `ProxyGroup/lab-ingress` has two Ready replicas, and the Hubble UI, Echo, and monitoring Services report `2/2 proxy backends ready and advertising`

Verify both API paths and ProxyGroup replicas:

```bash
kubectl --context tailscale-k0s get --raw=/readyz
kubectl --context lab-k0s.tailnet_dns_name.ts.net get --raw=/readyz
kubectl --context lab-k0s.tailnet_dns_name.ts.net auth whoami
kubectl --context tailscale-k0s wait proxygroup/lab-k0s \
  --for=condition=ProxyGroupReady=true --timeout=30s
kubectl --context tailscale-k0s -n tailscale get pods \
  -l tailscale.com/parent-resource=lab-k0s -o wide
kubectl --context tailscale-k0s wait proxygroup/lab-ingress \
  --for=condition=ProxyGroupReady=true --timeout=30s
kubectl --context tailscale-k0s -n tailscale get pods \
  -l tailscale.com/parent-resource=lab-ingress -o wide
kubectl --context tailscale-k0s get service \
  -n ingress-nginx hubble-ui-tailscale \
  -o jsonpath='{.status.conditions[?(@.type=="TailscaleIngressSvcConfigured")].message}{"\n"}'
kubectl --context tailscale-k0s get service \
  -n envoy-gateway-system \
  -l gateway.envoyproxy.io/owning-gateway-name=echo \
  -o jsonpath='{.items[0].status.conditions[?(@.type=="TailscaleIngressSvcConfigured")].message}{"\n"}'
kubectl --context tailscale-k0s get service \
  -n envoy-gateway-system \
  -l gateway.envoyproxy.io/owning-gateway-name=monitoring \
  -o jsonpath='{.items[0].status.conditions[?(@.type=="TailscaleIngressSvcConfigured")].message}{"\n"}'
```

### Live status reference

The following output was captured from the running lab on 2026-08-30. Use it as a structural reference, not as fixed expected output: resource names, ages, process IDs, Pod IPs, and Tailscale addresses change when the cluster is rebuilt.

List the worker nodes and confirm that every InternalIP belongs to the Tailscale underlay:

```console
$ kubectl get nodes -o wide
NAME      STATUS   ROLES    AGE     VERSION       INTERNAL-IP      EXTERNAL-IP   OS-IMAGE                       KERNEL-VERSION    CONTAINER-RUNTIME
node-01   Ready    <none>   3h24m   v1.36.3+k0s   100.116.95.79    <none>        Debian GNU/Linux 13 (trixie)   6.1.167 (amd64)   containerd://2.3.3
node-02   Ready    <none>   3h24m   v1.36.3+k0s   100.127.198.66   <none>        Debian GNU/Linux 13 (trixie)   6.1.167 (amd64)   containerd://2.3.3
node-03   Ready    <none>   3h24m   v1.36.3+k0s   100.94.184.38    <none>        Debian GNU/Linux 13 (trixie)   6.1.167 (amd64)   containerd://2.3.3
node-04   Ready    <none>   3h24m   v1.36.3+k0s   100.66.160.66    <none>        Debian GNU/Linux 13 (trixie)   6.1.167 (amd64)   containerd://2.3.3
node-05   Ready    <none>   3h24m   v1.36.3+k0s   100.120.47.6     <none>        Debian GNU/Linux 13 (trixie)   6.1.167 (amd64)   containerd://2.3.3
```

Inspect all namespaced workloads and the controllers that maintain them:

```console
$ kubectl get all --all-namespaces
NAMESPACE     NAME                                   READY   STATUS    RESTARTS   AGE
kube-system   pod/cilium-677d2                       1/1     Running   0          3h27m
kube-system   pod/cilium-6k9t7                       1/1     Running   0          3h27m
kube-system   pod/cilium-ccbd2                       1/1     Running   0          3h27m
kube-system   pod/cilium-kfqh2                       1/1     Running   0          3h27m
kube-system   pod/cilium-nqppf                       1/1     Running   0          3h27m
kube-system   pod/cilium-operator-6fdfd468dd-xhgsj   1/1     Running   0          3h27m
kube-system   pod/cilium-operator-6fdfd468dd-z5tsz   1/1     Running   0          3h27m
kube-system   pod/coredns-86f8659d76-j4hln           1/1     Running   0          3h28m
kube-system   pod/coredns-86f8659d76-nfvrv           1/1     Running   0          3h28m
kube-system   pod/hubble-relay-5fd64868c6-6pdk8      1/1     Running   0          3h27m
kube-system   pod/hubble-ui-5b94b84b8c-tm25j         2/2     Running   0          3h27m
kube-system   pod/konnectivity-agent-2rxsj           1/1     Running   0          3h28m
kube-system   pod/konnectivity-agent-h5nzp           1/1     Running   0          3h28m
kube-system   pod/konnectivity-agent-hpxvk           1/1     Running   0          3h28m
kube-system   pod/konnectivity-agent-jn6d7           1/1     Running   0          3h28m
kube-system   pod/konnectivity-agent-zhzmv           1/1     Running   0          3h28m
kube-system   pod/metrics-server-d987bf784-p7fhn     1/1     Running   0          3h28m
kube-system   pod/nllb-node-01                       1/1     Running   0          3h28m
kube-system   pod/nllb-node-02                       1/1     Running   0          3h28m
kube-system   pod/nllb-node-03                       1/1     Running   0          3h28m
kube-system   pod/nllb-node-04                       1/1     Running   0          3h28m
kube-system   pod/nllb-node-05                       1/1     Running   0          3h28m
tailscale     pod/lab-k0s-0                          1/1     Running   0          3h20m
tailscale     pod/lab-k0s-1                          1/1     Running   0          3h20m
tailscale     pod/operator-548c6f88bc-m8dvg          1/1     Running   0          3h21m

NAMESPACE     NAME                     TYPE        CLUSTER-IP       EXTERNAL-IP   PORT(S)                  AGE
default       service/kubernetes       ClusterIP   10.96.0.1        <none>        443/TCP                  3h29m
kube-system   service/hubble-peer      ClusterIP   10.101.251.91    <none>        443/TCP                  3h27m
kube-system   service/hubble-relay     ClusterIP   10.103.81.195    <none>        80/TCP                   3h27m
kube-system   service/hubble-ui        ClusterIP   10.106.61.237    <none>        80/TCP                   3h27m
kube-system   service/kube-dns         ClusterIP   10.96.0.10       <none>        53/UDP,53/TCP,9153/TCP   3h29m
kube-system   service/metrics-server   ClusterIP   10.107.188.107   <none>        443/TCP                  3h28m

NAMESPACE     NAME                                DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR            AGE
kube-system   daemonset.apps/cilium               5         5         5       5            5           kubernetes.io/os=linux   3h27m
kube-system   daemonset.apps/konnectivity-agent   5         5         5       5            5           <none>                   3h29m

NAMESPACE     NAME                              READY   UP-TO-DATE   AVAILABLE   AGE
kube-system   deployment.apps/cilium-operator   2/2     2            2           3h27m
kube-system   deployment.apps/coredns           2/2     2            2           3h29m
kube-system   deployment.apps/hubble-relay      1/1     1            1           3h27m
kube-system   deployment.apps/hubble-ui         1/1     1            1           3h27m
kube-system   deployment.apps/metrics-server    1/1     1            1           3h28m
tailscale     deployment.apps/operator          1/1     1            1           3h21m

NAMESPACE     NAME                                         DESIRED   CURRENT   READY   AGE
kube-system   replicaset.apps/cilium-operator-6fdfd468dd   2         2         2       3h27m
kube-system   replicaset.apps/coredns-84958f7b59           0         0         0       3h29m
kube-system   replicaset.apps/coredns-86f8659d76           2         2         2       3h28m
kube-system   replicaset.apps/hubble-relay-5fd64868c6      1         1         1       3h27m
kube-system   replicaset.apps/hubble-ui-5b94b84b8c         1         1         1       3h27m
kube-system   replicaset.apps/metrics-server-d987bf784     1         1         1       3h28m
tailscale     replicaset.apps/operator-548c6f88bc          1         1         1       3h21m

NAMESPACE   NAME                       READY   AGE
tailscale   statefulset.apps/lab-k0s   2/2     3h20m
```

Check Cilium independently of generic Kubernetes readiness:

```console
$ cilium status
Cilium:             OK
Operator:           OK
Envoy DaemonSet:    disabled (using embedded mode)
Hubble Relay:       OK
ClusterMesh:        disabled

DaemonSet              cilium           Desired: 5, Ready: 5/5, Available: 5/5
Deployment             cilium-operator  Desired: 2, Ready: 2/2, Available: 2/2
Deployment             hubble-relay     Desired: 1, Ready: 1/1, Available: 1/1
Deployment             hubble-ui        Desired: 1, Ready: 1/1, Available: 1/1
Cluster Pods:          8/8 managed by Cilium
Helm chart version:    1.20.1
```

Controllers are intentionally absent from `kubectl get nodes`. Query each controller directly to confirm its k0s process and role:

```console
$ ssh root@control-plane-01 k0s status
Version: v1.36.4+k0s.0
Process ID: 2157
Role: controller
Workloads: false
SingleNode: false
```

Healthy output has five `Ready` workers, no non-running workload in the full `kubectl get all --all-namespaces` output, all desired Cilium replicas available, and every controller reporting `Role: controller` with `Workloads: false`.

#### Post-deployment application status

The following output was captured after deploying Hubble UI, Echo Server, and the shared HA ingress ProxyGroup on 2026-09-01. Ages, Pod IPs, generated names, node placement, and Tailscale Service addresses change across rebuilds.

Confirm that both API and ingress ProxyGroups are Ready and that the ingress replicas run on different workers:

```console
$ kubectl --context tailscale-k0s get proxygroup
NAME          STATUS            URL                                 TYPE             AGE
lab-ingress   ProxyGroupReady                                       ingress          54m
lab-k0s       ProxyGroupReady   https://lab-k0s.tailaa4bf1.ts.net   kube-apiserver   2d5h

$ kubectl --context tailscale-k0s -n tailscale get pods \
    -l tailscale.com/parent-resource=lab-ingress -o wide
NAME            READY   STATUS    RESTARTS   AGE   IP             NODE
lab-ingress-0   1/1     Running   0          12m   10.244.3.190   node-01
lab-ingress-1   1/1     Running   0          53m   10.244.4.241   node-04
```

Inspect the Tailscale-backed application Services. A Ready Service reports that every ingress replica advertises its virtual IP:

```console
$ kubectl --context tailscale-k0s get service \
    -n ingress-nginx hubble-ui-tailscale
NAME                  TYPE           CLUSTER-IP       EXTERNAL-IP     PORT(S)                      AGE
hubble-ui-tailscale   LoadBalancer   10.101.237.207   100.99.104.91   80:32718/TCP,443:31195/TCP   2d1h

$ kubectl --context tailscale-k0s get service \
    -n envoy-gateway-system \
    -l gateway.envoyproxy.io/owning-gateway-name=echo
NAME                       TYPE           CLUSTER-IP      EXTERNAL-IP       PORT(S)         AGE
envoy-echo-echo-85befeca   LoadBalancer   10.111.10.133   100.107.252.170   443:30553/TCP   2d

$ kubectl --context tailscale-k0s -n ingress-nginx \
    get service hubble-ui-tailscale \
    -o jsonpath='{.status.conditions[?(@.type=="TailscaleIngressSvcConfigured")].message}{"\n"}'
2/2 proxy backends ready and advertising

$ kubectl --context tailscale-k0s -n envoy-gateway-system \
    get service -l gateway.envoyproxy.io/owning-gateway-name=echo \
    -o jsonpath='{.items[0].status.conditions[?(@.type=="TailscaleIngressSvcConfigured")].message}{"\n"}'
2/2 proxy backends ready and advertising
```

Confirm the application workloads, Gateway API state, and certificates:

```console
$ kubectl --context tailscale-k0s get deployment --all-namespaces \
    -l 'app.kubernetes.io/name in (ingress-nginx,echo-server,external-dns,cert-manager)'
NAMESPACE       NAME                       READY   UP-TO-DATE   AVAILABLE   AGE
cert-manager    cert-manager               1/1     1            1           2d1h
echo            echo-server                2/2     2            2           2d
external-dns    external-dns               1/1     1            1           2d1h
ingress-nginx   ingress-nginx-controller   1/1     1            1           2d1h

$ kubectl --context tailscale-k0s -n echo get gateway,httproute
NAME                                     CLASS       ADDRESS           PROGRAMMED   AGE
gateway.gateway.networking.k8s.io/echo   tailscale   100.107.252.170   True         2d

NAME                                       HOSTNAMES                          AGE
httproute.gateway.networking.k8s.io/echo   ["echo.playground.canhdinh.com"]   2d

$ kubectl --context tailscale-k0s get certificate --all-namespaces
NAMESPACE     NAME                               READY   SECRET                             AGE
echo          echo-playground-canhdinh-com-tls   True    echo-playground-canhdinh-com-tls   2d
kube-system   hubble-ui                          True    hubble-ui-tls                      2d1h
```

Finally, verify both private HTTPS paths from an authorized tailnet client:

```console
$ curl --fail --show-error --head \
    https://hubble-ui.playground.canhdinh.com/
HTTP/2 200
content-type: text/html
strict-transport-security: max-age=31536000; includeSubDomains

$ curl --fail --show-error \
    'https://echo.playground.canhdinh.com/?echo_body=gateway-api'
"gateway-api"
```

This snapshot demonstrates the completed lab: Hubble UI and Echo each have a private Tailscale Service VIP, both VIPs are advertised by two shared proxies, both TLS certificates are Ready, and both HTTPS endpoints respond successfully.

#### Monitoring stack status

The following output was captured after installing kube-prometheus-stack, exposing its three interfaces through Gateway API, enabling read-only Prometheus rule visibility in Grafana, and reconciling the API-managed Kubernetes command-center dashboard on 2026-09-01. Ages, Pod IPs, generated names, and Tailscale Service addresses change across rebuilds.

Confirm that every monitoring workload is Ready. The node-exporter Pods use host networking and therefore show each worker's Tailscale InternalIP:

```console
$ kubectl --context tailscale-k0s -n monitoring get pods -o wide
NAME                                                     READY   STATUS    RESTARTS   NODE
alertmanager-monitoring-kube-prometheus-alertmanager-0   2/2     Running   0          node-05
monitoring-grafana-7b7975d6d7-s82vl                      3/3     Running   0          node-04
monitoring-kube-prometheus-operator-8dccd655b-6fm62      1/1     Running   0          node-05
monitoring-kube-state-metrics-7b56559c6f-2rdh4           1/1     Running   0          node-01
monitoring-prometheus-node-exporter-5h65t                1/1     Running   0          node-02
monitoring-prometheus-node-exporter-mw9hc                1/1     Running   0          node-01
monitoring-prometheus-node-exporter-qr8b5                1/1     Running   0          node-03
monitoring-prometheus-node-exporter-rmjtj                1/1     Running   0          node-05
monitoring-prometheus-node-exporter-zrff8                1/1     Running   0          node-04
prometheus-monitoring-kube-prometheus-prometheus-0       2/2     Running   0          node-04
```

Inspect the Gateway, routes, certificates, and generated Tailscale LoadBalancer Service:

```console
$ kubectl --context tailscale-k0s -n monitoring get gateway,httproute
NAME                                           CLASS                  ADDRESS          PROGRAMMED
gateway.gateway.networking.k8s.io/monitoring   monitoring-tailscale   100.89.207.205   True

NAME                                               HOSTNAMES
httproute.gateway.networking.k8s.io/alertmanager   ["alertmanager.playground.canhdinh.com"]
httproute.gateway.networking.k8s.io/grafana        ["grafana.playground.canhdinh.com"]
httproute.gateway.networking.k8s.io/prometheus     ["prometheus.playground.canhdinh.com"]

$ kubectl --context tailscale-k0s -n monitoring get certificate
NAME                                       READY   SECRET
alertmanager-playground-canhdinh-com-tls   True    alertmanager-playground-canhdinh-com-tls
grafana-playground-canhdinh-com-tls        True    grafana-playground-canhdinh-com-tls
prometheus-playground-canhdinh-com-tls     True    prometheus-playground-canhdinh-com-tls

$ kubectl --context tailscale-k0s -n envoy-gateway-system get service \
    -l gateway.envoyproxy.io/owning-gateway-name=monitoring
NAME                                   TYPE           CLUSTER-IP       EXTERNAL-IP      PORT(S)
envoy-monitoring-monitoring-9b4a98e3   LoadBalancer   10.103.128.133   100.89.207.205   443:31004/TCP

$ kubectl --context tailscale-k0s -n envoy-gateway-system get service \
    -l gateway.envoyproxy.io/owning-gateway-name=monitoring \
    -o jsonpath='{.items[0].status.conditions[?(@.type=="TailscaleIngressSvcConfigured")].message}{"\n"}'
2/2 proxy backends ready and advertising
```

Verify scrape health and the loaded rule set through Prometheus:

```console
$ curl --fail --silent --show-error \
    https://prometheus.playground.canhdinh.com/api/v1/targets | \
    jq '{active: (.data.activeTargets | length), up: ([.data.activeTargets[] | select(.health == "up")] | length), down: ([.data.activeTargets[] | select(.health != "up")] | length)}'
{
  "active": 32,
  "up": 32,
  "down": 0
}

$ curl --fail --silent --show-error \
    https://prometheus.playground.canhdinh.com/api/v1/rules | \
    jq '{groups: (.data.groups | length), alertRules: ([.data.groups[].rules[] | select(.type == "alerting")] | length), recordingRules: ([.data.groups[].rules[] | select(.type == "recording")] | length), firing: [.data.groups[].rules[] | select(.type == "alerting" and .state == "firing") | .name]}'
{
  "groups": 30,
  "alertRules": 134,
  "recordingRules": 85,
  "firing": ["Watchdog"]
}
```

Grafana's provisioned Prometheus data source has `manageAlerts: true`, so **Alerting > Alert rules** displays these 134 rules as read-only data-source-managed rules. The expected always-firing `Watchdog` is the only active rule in this snapshot. The reconciled `Kubernetes / Cluster Command Center` dashboard has UID `kubernetes-command-center`, version `1`, and 17 panels. Because Grafana uses ephemeral storage, a Helm upgrade that recreates its Pod removes this API-managed dashboard; rerun the dashboard reconciliation command before recording the deployment as complete.

This snapshot demonstrates the completed monitoring deployment: all scrape targets are healthy, the three interfaces share one private Gateway VIP and valid certificates, both ingress proxies advertise the Service, Grafana displays the Prometheus rule set, and no external notification receiver is configured for this lab.

## Recurring operations

Use these procedures after deployment without repeating the full bootstrap.

### Upgrade Cilium within the 1.20 release

Render and inspect the target chart with the complete checked-in values before changing the cluster:

```bash
helm template cilium cilium/cilium \
  --version 1.20.1 \
  --namespace kube-system \
  --values docs/k0s/cilium-values.yaml >/dev/null

helm upgrade cilium cilium/cilium \
  --version 1.20.1 \
  --namespace kube-system \
  --kube-context tailscale-k0s \
  --values docs/k0s/cilium-values.yaml \
  --dry-run=server
```

Apply the reviewed release and wait for the rollout:

```bash
helm upgrade cilium cilium/cilium \
  --version 1.20.1 \
  --namespace kube-system \
  --kube-context tailscale-k0s \
  --values docs/k0s/cilium-values.yaml \
  --rollback-on-failure \
  --timeout 20m

cilium status --context tailscale-k0s --wait
```

Keep `upgradeCompatibility: "1.20"` set to the cluster's initial Cilium release series. Run the focused connectivity tests from Step 9 after every upgrade. That procedure forwards Hubble Relay before enabling flow validation and removes generated resources even when the test fails or is interrupted.

### Reconcile a node address change

Refresh addresses before applying k0s changes:

```bash
uv run scripts/update_k0s_tailscale_ips.py --dry-run
uv run scripts/update_k0s_tailscale_ips.py
k0sctl apply --config docs/k0s/k0s.yaml --dry-run
```

A controller address change affects etcd membership and certificates. Back up etcd and follow the k0s controller replacement procedure instead of treating it as a worker replacement.

### Diagnose degraded connectivity

Check the Tailscale path before changing Kubernetes:

```bash
tailscale status
tailscale netcheck
tailscale ping control-plane-01
ssh root@node-01 tailscale ping node-02
ssh root@node-01 ip route
```

DERP preserves encryption and connectivity but increases latency. Investigate firewall, Network Address Translation (NAT), and User Datagram Protocol (UDP) reachability when a direct path becomes relayed.

### Inspect Hubble UI certificate renewal

Check the certificate condition and renewal schedule without reading the private key:

```bash
kubectl --context tailscale-k0s -n kube-system \
  get certificate hubble-ui
kubectl --context tailscale-k0s -n kube-system \
  get certificate hubble-ui -o jsonpath='{range .status.conditions[*]}\
{.type}{"="}{.status}{": "}{.message}{"\n"}{end}\
{"notAfter="}{.status.notAfter}{"\n"}\
{"renewalTime="}{.status.renewalTime}{"\n"}'
kubectl --context tailscale-k0s -n kube-system \
  get orders.acme.cert-manager.io,challenges.acme.cert-manager.io
```

`Ready=True` is the steady state. No active `Order` or `Challenge` is required between issuance and renewal. During renewal, cert-manager creates a temporary `_acme-challenge.hubble-ui.playground.canhdinh.com` TXT record, validates it through public DNS, replaces `hubble-ui-tls`, and removes the TXT record. ingress-nginx watches the Secret and reloads the keypair without changing the Tailscale Service address.

Compare the live Issuer email to the encrypted source without printing either value:

```bash
(
  set -euo pipefail
  expected_file=$(mktemp)
  live_file=$(mktemp)
  trap 'rm -f "$expected_file" "$live_file"' EXIT
  umask 077
  sops decrypt --extract '["acme"]["email"]' \
    secrets/lab.sops.yaml >"$expected_file"
  kubectl --context tailscale-k0s -n kube-system \
    get issuer letsencrypt-cloudflare \
    -o jsonpath='{.spec.acme.email}' >"$live_file"
  cmp --silent "$expected_file" "$live_file"
)
```

An exit status of zero confirms that `acme.email` in `secrets/lab.sops.yaml` remains the source of truth.

## Troubleshooting

Use observed symptoms to select the narrowest corrective action:

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Only the first controller starts | k0s selected a playground address | Set `api.onlyBindToAddress: true`, inspect the dry run, and reconcile |
| Workers remain `NotReady` after Cilium installation | Cilium cannot reach the API or attach devices | Check Cilium status, logs, `k8sServiceHost`, and `devices` |
| Large requests stall | MTU exceeds the encapsulated path | Restore MTU `1230` and measure every node pair |
| `ProxyGroupReady` remains false | Tailscale Service approval is missing | Add the exact auto-approver or approve only the two backends |
| Tailscale paths use DERP | Direct UDP connectivity is unavailable | Check `tailscale netcheck`, firewall rules, and NAT behavior |
| Cluster routes use another VPN | Accepted subnet routes overlap cluster CIDR ranges | Remove the route or choose unused Pod and Service ranges |
| Canonical hostnames resolve to stale addresses or fresh devices receive `-1` suffixes | Destroyed playground devices remain registered in the tailnet | Remove only the confirmed offline records, restore the fresh devices' canonical names, and wait for MagicDNS convergence |
| `tailscale ping` prints `pong` but exits nonzero | DERP works but no direct peer path was established | Verify SSH succeeds, inspect `tailscale netcheck`, and troubleshoot UDP or NAT without blocking bootstrap on a functional DERP path |
| Sonobuoy reports failures | Cluster behavior or the test environment failed | Preserve the archive and inspect each failed test |
| `Certificate/hubble-ui` remains `Ready=False` | Cloudflare token permissions, ACME account, or DNS propagation failed | Inspect the related `Order` and `Challenge`; confirm `Zone - DNS - Edit` and `Zone - Zone - Read` for `canhdinh.com` without printing the token |
| HTTPS presents the ingress default certificate | `hubble-ui-tls` is missing, invalid, or not loaded by ingress-nginx | Check the Certificate condition, Secret type, Ingress TLS reference, and ingress-nginx events and logs |
| Hubble hostname resolves but TCP 443 fails | The DNS record points to a stale Tailscale Service IP or tailnet policy denies access | Compare the DNS-only `A` record with the Service external IP and verify the TCP 443 grant |
| HTTPS returns `503 Service Temporarily Unavailable` | The Ingress cannot reach Cilium's `hubble-ui` Service endpoints | Check the Ingress backend, `hubble-ui` endpoints, Hubble UI Pod readiness, and ingress-nginx logs |
| ingress-nginx reports a Tailscale proxy Pod IP as the client | The Layer 3 Tailscale LoadBalancer proxy is the TCP peer seen by ingress-nginx | This is expected; retain tailnet grants as the access boundary and do not trust client-supplied forwarding headers |
| Echo Gateway remains unprogrammed | Envoy could not provision its data plane or the Tailscale LoadBalancer | Inspect Gateway conditions, Envoy Gateway Pods, the generated Service, and Tailscale operator logs |
| Echo `HTTPRoute` is not accepted | Its hostname, parent reference, listener, or namespace policy does not match | Inspect `status.parents` and keep the route in the `echo` namespace unless the Gateway policy is intentionally broadened |
| Echo DNS resolves to a stale address | ExternalDNS is unhealthy or cannot update the Cloudflare zone | Compare the Gateway address with the DNS-only `A` record; inspect ExternalDNS logs, token scope, zone filter, and TXT ownership record |
| Echo Certificate remains `Ready=False` | The ClusterIssuer, cert-manager namespace token, or DNS-01 propagation failed | Inspect the ClusterIssuer, Certificate, Order, and Challenge without printing the token |
| Echo reports a Tailscale proxy Pod IP as the client | The selected ingress ProxyGroup replica is the TCP peer seen by Envoy | This is expected; do not trust client-supplied forwarding headers or enable PROXY protocol without a trusted sender |
| `_acme-challenge` TXT remains after issuance | Challenge cleanup failed or another ACME flow owns the record | Inspect active Challenges before deleting anything; let cert-manager reconcile first |

## Rollback and safe teardown

Do not attempt an in-place rollback after partial bootstrap without checking etcd state. `k0sctl apply` can reconcile a partial installation when controller identities remain valid.

To roll back only Hubble UI HTTPS while preserving Cilium and the cluster, remove resources in dependency order:

```bash
kubectl --context tailscale-k0s -n ingress-nginx \
  delete service hubble-ui-tailscale
kubectl --context tailscale-k0s -n kube-system \
  delete ingress hubble-ui certificate hubble-ui \
  issuer letsencrypt-cloudflare
kubectl --context tailscale-k0s -n kube-system \
  delete secret cloudflare-api-token
helm --kube-context tailscale-k0s -n ingress-nginx \
  uninstall ingress-nginx
```

Delete the DNS-only `hubble-ui.playground.canhdinh.com` `A` record after the Tailscale Service is gone. Do not delete `_acme-challenge` TXT records manually until active cert-manager Challenges have been inspected. Preserve cert-manager while Echo or any other certificate consumer remains. If no `Certificate`, `Issuer`, or `ClusterIssuer` resources remain and permanent removal is intended, uninstall cert-manager separately. Helm intentionally retains cert-manager custom resource definitions to prevent accidental data loss; remove them only after confirming no certificate resources remain anywhere in the cluster.

To remove Echo Server while preserving shared Gateway API, DNS, and certificate controllers, delete the route and Gateway first. Wait for ExternalDNS to remove its owned Cloudflare records before removing the namespace:

```bash
kubectl --context tailscale-k0s -n echo \
  delete httproute echo gateway echo

until [[ -z $(dig +short echo.playground.canhdinh.com A) ]]; do
  sleep 5
done

kubectl --context tailscale-k0s delete namespace echo
```

The Tailscale operator removes the Envoy Tailscale Service advertisement after the Gateway disappears; `ProxyGroup/lab-ingress` remains for Hubble UI and other consumers. If the DNS record remains after two ExternalDNS reconciliation intervals, inspect the controller logs and remove only `echo.playground.canhdinh.com` plus its ExternalDNS ownership TXT record after confirming their owner ID is `lab-k0s-gateway`. Do not uninstall shared controllers merely to remove Echo Server.

To remove monitoring while preserving the shared Gateway API, DNS, and certificate controllers, remove its routes and Gateway first. Wait for ExternalDNS to remove the three owned Cloudflare records, then remove monitoring's dedicated GatewayClass and EnvoyProxy before uninstalling the chart:

```bash
kubectl --context tailscale-k0s -n monitoring delete \
  httproute prometheus alertmanager grafana gateway monitoring

until [[ -z $(dig +short prometheus.playground.canhdinh.com A) ]] && \
      [[ -z $(dig +short alertmanager.playground.canhdinh.com A) ]] && \
      [[ -z $(dig +short grafana.playground.canhdinh.com A) ]]; do
  sleep 5
done

kubectl --context tailscale-k0s delete \
  gatewayclass monitoring-tailscale
kubectl --context tailscale-k0s -n envoy-gateway-system delete \
  envoyproxy.gateway.envoyproxy.io monitoring-proxy
helm --kube-context tailscale-k0s -n monitoring uninstall monitoring
kubectl --context tailscale-k0s delete namespace monitoring
```

The monitoring chart installs Prometheus Operator CRDs that Helm retains during uninstall. Remove those cluster-scoped CRDs only after confirming no other Prometheus Operator release or custom resource uses them.

Remove the shared components only when no other Gateways, routes, certificates, or managed DNS records depend on them:

```bash
kubectl --context tailscale-k0s delete \
  -f docs/k0s/envoy-gateway-tailscale.yaml
kubectl --context tailscale-k0s delete \
  -f docs/k0s/ingress-proxygroup.yaml
helm --kube-context tailscale-k0s -n external-dns \
  uninstall external-dns
kubectl --context tailscale-k0s delete namespace external-dns
kubectl --context tailscale-k0s delete \
  clusterissuer letsencrypt-cloudflare
kubectl --context tailscale-k0s -n cert-manager \
  delete secret cloudflare-api-token
helm --kube-context tailscale-k0s -n envoy-gateway-system \
  uninstall envoy-gateway
```

The Envoy Gateway Helm release owns Gateway API and Envoy CRDs. Helm does not remove CRDs during uninstall; delete them only after confirming no resources of those APIs remain and permanent removal is intended.

Before destroying playgrounds, export workload data and an etcd backup. Then complete these actions:

1. Remove Kubernetes workloads and the ProxyGroup while the cluster can reconcile deletion.
2. Remove operator-created Tailscale devices and Services.
3. Destroy the playgrounds through iximiuz Labs.
4. Remove stale machines from the Tailscale admin console.
5. Revoke every remaining enrollment key and API token.
6. Remove obsolete direct kubeconfig credentials from administrator machines.

Destroying a playground removes its local k0s state. Restore from the etcd backup only into a compatible, isolated recovery cluster.

## Escalation

Record environment-specific contacts before another operator uses this runbook:

| Situation | Contact | Method |
| --- | --- | --- |
| Tailnet policy, device identity, or Service approval failure | Tailnet owner | Organization-approved operations channel |
| etcd quorum loss or controller replacement | Kubernetes platform owner | Organization-approved incident channel |
| iximiuz Labs provisioning or network failure | iximiuz Labs support | [iximiuz Labs documentation](https://labs.iximiuz.com/docs) |
| Reproducible repository defect | Repository owner | Repository issue tracker |

## Run history

Update this table after every deployment, upgrade, recovery, or teardown:

| Date | Run by | Notes |
| --- | --- | --- |
| 2026-08-29 | Not recorded | Converted the deployment guide into an operational runbook |
| 2026-08-30 | Repository owner and OpenCode | Rebuilt two playgrounds from scratch; verified k0s, Cilium connectivity, Sonobuoy quick mode, and both Kubernetes API paths |
| 2026-08-30 | Repository owner and OpenCode | Exposed Hubble UI through a private Tailscale LoadBalancer; installed cert-manager and ingress-nginx; issued and verified a Let's Encrypt ECDSA certificate with Cloudflare DNS-01 |
| 2026-08-30 | Repository owner and OpenCode | Deployed Echo Server through Envoy Gateway and a private Tailscale LoadBalancer; automated Cloudflare DNS with ExternalDNS and issued a Let's Encrypt ECDSA certificate with DNS-01 |
| 2026-09-01 | Repository owner and OpenCode | Deployed kube-prometheus-stack and its Kubernetes command-center dashboard; exposed Prometheus, Alertmanager, and Grafana through one private Envoy Gateway with ExternalDNS and Let's Encrypt DNS-01 certificates |
| 2026-09-01 | Repository owner and OpenCode | Upgraded all eight hosts to k0s `v1.36.4+k0s.0` and Cilium to `1.20.1`; verified API and etcd health, five Ready workers, 70 focused connectivity actions with Hubble Relay forwarded, ingress endpoints, and 32 healthy Prometheus targets |

## Supporting references

Use these sources to validate version-specific behavior:

- [iximiuz Labs playgrounds](https://labs.iximiuz.com/docs/playgrounds)
- [k0sctl configuration](https://github.com/k0sproject/k0sctl#configuration-file)
- [k0s networking](https://docs.k0sproject.io/stable/networking/)
- [k0s node-local load balancing](https://docs.k0sproject.io/stable/nllb/)
- [Cilium 1.20 Helm reference](https://docs.cilium.io/en/v1.20/helm-reference/)
- [Cilium 1.20 kube-proxy replacement](https://docs.cilium.io/en/v1.20/network/kubernetes/kubeproxy-free/)
- [Cilium 1.20 routing](https://docs.cilium.io/en/v1.20/network/concepts/routing/)
- [Cilium 1.20 cluster-pool IP address management](https://docs.cilium.io/en/v1.20/network/concepts/ipam/cluster-pool/)
- [Tailscale auth keys](https://tailscale.com/docs/features/access-control/auth-keys)
- [Tailscale grants](https://tailscale.com/docs/features/access-control/grants)
- [Tailscale SSH](https://tailscale.com/docs/features/tailscale-ssh)
- [Tailscale connection types](https://tailscale.com/docs/reference/connection-types)
- [Install the Tailscale Kubernetes Operator](https://tailscale.com/docs/kubernetes-operator/install-operator)
- [Kubernetes API access over Tailscale](https://tailscale.com/docs/kubernetes-operator/api-server-access/setup-api-over-tailscale)
- [Tailscale and Cilium compatibility](https://tailscale.com/docs/kubernetes-operator/reference/compatibility)
- [Tailscale Layer 3 workload exposure](https://tailscale.com/docs/kubernetes-operator/ingress/expose-workload-to-tailnet-l3)
- [Tailscale custom domains with Gateway API](https://tailscale.com/docs/solutions/kubernetes-operator-byod-gateway-api)
- [Envoy Gateway Helm installation](https://gateway.envoyproxy.io/docs/install/install-helm/)
- [ExternalDNS Gateway sources](https://kubernetes-sigs.github.io/external-dns/latest/docs/sources/gateway/)
- [ExternalDNS Cloudflare provider](https://kubernetes-sigs.github.io/external-dns/latest/docs/tutorials/cloudflare/)
- [cert-manager installation with Helm](https://cert-manager.io/docs/installation/helm/)
- [cert-manager Cloudflare DNS-01](https://cert-manager.io/docs/configuration/acme/dns01/cloudflare/)
- [cert-manager Gateway certificates](https://cert-manager.io/docs/usage/gateway/)
- [ingress-nginx installation](https://kubernetes.github.io/ingress-nginx/deploy/)
- [kube-prometheus-stack chart](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
