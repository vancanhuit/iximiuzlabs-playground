# Build and operate a k0s cluster over Tailscale

**Owner:** Lab operator | **Frequency:** As needed
**Last updated:** 2026-08-29 | **Last run:** Not recorded

This runbook builds and operates an eight-node Kubernetes cluster across two iximiuz Labs playgrounds. Use it for initial deployment, validation, upgrades, recovery, and teardown.

## Plan and scope

This page serves an operator who controls the playgrounds, tailnet, and Kubernetes cluster.

- **Overview:** Build k0s on a private Tailscale underlay and install Cilium
- **Goal:** Deploy and verify a recoverable, kube-proxy-free Kubernetes cluster
- **Audience:** The lab operator responsible for Tailscale and Kubernetes administration
- **Content plan:** Prepare, secure, bootstrap, verify, operate, and remove the cluster
- **Open questions:** Record environment-specific contacts and the last successful run before sharing this runbook

This page is an operational how-to. Open the [interactive architecture](architecture/lab-architecture.html) to explore the system. Open the [interactive bootstrap journey](architecture/bootstrap-journey.html) to explore the deployment sequence.

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

## Tested versions

Treat these versions as one tested set. Validate upgrades in a fresh playground before changing a shared cluster.

| Component | Version |
| --- | --- |
| k0sctl | `v0.32.2` |
| k0s and Kubernetes | `v1.36.3+k0s.0` |
| Cilium | `v1.20.0` |
| Tailscale Kubernetes Operator | `1.102.3` |
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

Create a preapproved, one-use auth key for `tag:lab`. Store it at `tailscale.auth_key` in [`../../secrets/lab.sops.yaml`](../../secrets/lab.sops.yaml).

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

From an interactive node shell, enter the key through standard input. Press `Ctrl-D`, then enroll the node:

```bash
sudo install -m 600 /dev/stdin /run/tailscale-auth-key
sudo tailscale up \
  --auth-key=file:/run/tailscale-auth-key \
  --advertise-tags=tag:lab \
  --ssh
sudo rm -f /run/tailscale-auth-key
```

Repeat enrollment for all eight nodes. Revoke a reusable key immediately after the final enrollment.

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
  --version 1.20.0 \
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

The selectors test Pod traffic, ClusterIP and NodePort Services, Domain Name System (DNS), and client egress. They omit the `dns-only` Layer 7 test because this cluster has no Envoy proxy.

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
kubectl create namespace tailscale \
  --dry-run=client -o yaml | kubectl apply -f -
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
helm repo add tailscale https://pkgs.tailscale.com/helmcharts
helm repo update
helm upgrade --install tailscale-operator \
  tailscale/tailscale-operator \
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

Verify both API paths and ProxyGroup replicas:

```bash
kubectl --context tailscale-k0s get --raw=/readyz
kubectl --context lab-k0s.tailnet_dns_name.ts.net get --raw=/readyz
kubectl --context lab-k0s.tailnet_dns_name.ts.net auth whoami
kubectl --context tailscale-k0s wait proxygroup/lab-k0s \
  --for=condition=ProxyGroupReady=true --timeout=30s
kubectl --context tailscale-k0s -n tailscale get pods \
  -l tailscale.com/parent-resource=lab-k0s -o wide
```

## Recurring operations

Use these procedures after deployment without repeating the full bootstrap.

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
| Sonobuoy reports failures | Cluster behavior or the test environment failed | Preserve the archive and inspect each failed test |

## Rollback and safe teardown

Do not attempt an in-place rollback after partial bootstrap without checking etcd state. `k0sctl apply` can reconcile a partial installation when controller identities remain valid.

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
