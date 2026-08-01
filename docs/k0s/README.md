# `k0s` on Tailscale with Cilium

This runbook bootstraps an eight-node Kubernetes cluster with `k0sctl`, uses
Tailscale as the node-to-node underlay, and installs Cilium as a kube-proxy-free
CNI.

## Cluster topology

| Host | Role | Tailscale IPv4 |
| --- | --- | --- |
| `control-plane-01` | `controller` | `100.99.78.51` |
| `control-plane-02` | `controller` | `100.80.157.98` |
| `control-plane-03` | `controller` | `100.110.188.59` |
| `node-01` | `worker` | `100.100.187.71` |
| `node-02` | `worker` | `100.124.198.50` |
| `node-03` | `worker` | `100.114.226.97` |
| `node-04` | `worker` | `100.102.150.26` |
| `node-05` | `worker` | `100.108.18.99` |

Versions and networks:

| Component | Value |
| --- | --- |
| `k0sctl` | `v0.32.2` |
| `k0s` / Kubernetes | `v1.36.3+k0s.0` |
| Cilium CLI | `v0.19.7` |
| Cilium chart / agents | `v1.20.0` |
| Gateway API CRDs | standard channel `v1.6.1` |
| Pod CIDR | `10.244.0.0/16` |
| Service CIDR | `10.96.0.0/12` |
| Node interface | `tailscale0` |

The controllers are control-plane-only nodes. Workloads run on the five workers.

### Why controllers do not appear in `kubectl get nodes`

The three control-plane hosts use the `k0sctl` role `controller`, not
`controller+worker`. Dedicated `k0s` controllers run control-plane components and
`etcd`, but they do not run `kubelet`. Kubernetes `Node` objects represent kubelets,
so `kubectl get nodes -o wide` correctly lists only the five workers.

Check controller and etcd health separately:

```bash
ssh root@control-plane-01 k0s status
ssh root@control-plane-02 k0s status
ssh root@control-plane-03 k0s status
ssh root@control-plane-01 k0s etcd member-list
```

Use `controller+worker` only when a controller must also register as a Node and
run kubelet. Those nodes are tainted by default, so regular workloads remain
unschedulable unless they tolerate the controller taint or `noTaints: true` is
configured intentionally.

## Prerequisites

Install the pinned tools from the repository root:

```bash
mise install
mise ls --local
```

The control host and all cluster nodes must be connected to the same tailnet.
Tailscale SSH must permit `root` access from the control host to every node:

```bash
tailscale status
ssh root@control-plane-01 hostname
ssh root@node-01 hostname
```

Ensure the tailnet ACL and any host firewall permit required cluster traffic.
At minimum this includes:

- TCP `2380`, `6443`, `8132`, and `9443` between relevant `k0s` nodes
- TCP `10250` for kubelet access
- UDP `8472` between workers for Cilium VXLAN
- TCP `4240` between workers for Cilium health checks
- TCP `22` from the control host when not relying solely on Tailscale SSH policy

The Pod and Service CIDRs must not overlap the tailnet or another routed network.
In particular, do not allocate Pods from `100.64.0.0/10`; Tailscale uses that
CGNAT range for node addresses.

## Why the configuration matters

The cluster definition is [`k0s.yaml`](../../k0s.yaml). Every host sets both
`privateAddress` and `privateInterface: tailscale0`, making Tailscale the address
used by kubelet, etcd, and `k0sctl`-generated node settings.

The controllers are multihomed: each also has an iximiuz Labs LAN address on
`eth0`. Setting only `privateAddress` is not enough to select the `k0s` API address.
This setting is required:

```yaml
spec:
  api:
    onlyBindToAddress: true
```

With `k0sctl v0.32.2`, it causes each generated controller configuration to receive
its own Tailscale `spec.api.address`. Without it, `k0s` selected the first non-local
LAN address (`172.16.0.2`), and the other controllers could not join through the
tailnet.

The API certificate SANs include all three controller names and Tailscale IPs.
There is no `externalAddress`, HAProxy, virtual IP, or `k0s` control-plane load
balancer.

`k0s` node-local load balancing (NLLB) runs Envoy on each `worker` and exposes a
worker-local API endpoint at `127.0.0.1:7443`. NLLB makes in-cluster control-plane
access resilient, but it does not make the kubeconfig endpoint externally highly
available.

## 1. Validate the `k0sctl` plan

Run a dry run before every first installation or material configuration change:

```bash
k0sctl apply --config k0s.yaml --dry-run
```

Confirm the generated controller configurations contain these node-specific
addresses:

```text
control-plane-01: spec.api.address: 100.99.78.51
control-plane-02: spec.api.address: 100.80.157.98
control-plane-03: spec.api.address: 100.110.188.59
```

Controller and worker join validation must target `100.99.78.51`, not a
`172.16.0.x` address.

## 2. Bootstrap `k0s`

```bash
k0sctl apply --config k0s.yaml
```

`spec.options.wait.enabled` is intentionally `false`. A custom CNI is configured
and kube-proxy is disabled, so workers register as `NotReady` until Cilium is
installed. That intermediate state is expected.

Verify the controller processes and etcd membership:

```bash
ssh root@control-plane-01 k0s status
ssh root@control-plane-02 k0s status
ssh root@control-plane-03 k0s status
ssh root@control-plane-01 k0s etcd member-list
```

The `etcd` member list should contain all three Tailscale endpoints on TCP `2380`.

Verify worker registration:

```bash
ssh root@control-plane-01 k0s kubectl get nodes -o wide
```

Before Cilium, all five workers should exist with their `100.x` InternalIP and a
`NotReady` status.

### Recovering from a wrong API address

The first bootstrap attempt can leave `control-plane-01` running even when the
other controllers fail to join. Do not immediately reset a healthy first
controller. Add `api.onlyBindToAddress: true`, then verify the fix with a dry run.
`k0sctl` can reconcile the partial state on the next apply:

```bash
k0sctl apply --config k0s.yaml --dry-run
k0sctl apply --config k0s.yaml
```

Useful diagnostics:

```bash
ssh root@control-plane-01 \
  "journalctl -u k0scontroller --no-pager | grep 'using api address'"
ssh root@control-plane-01 \
  "ss -lntp | grep -E ':(2380|6443|9443)'"
```

## 3. Configure local cluster access

Back up an existing kubeconfig, fetch the `k0s` admin config, and secure both
files:

```bash
mkdir -p ~/.kube
if [[ -f ~/.kube/config ]]; then
  cp --backup=numbered --preserve=mode,timestamps \
    ~/.kube/config ~/.kube/config.pre-k0s
fi

tmp_kubeconfig=$(mktemp)
k0sctl kubeconfig --config k0s.yaml > "$tmp_kubeconfig"
install -m 600 "$tmp_kubeconfig" ~/.kube/config
rm -f "$tmp_kubeconfig"
chmod 600 ~/.kube/config.pre-k0s 2>/dev/null || true
```

Verify the active context and API:

```bash
kubectl config current-context
kubectl get --raw=/readyz
```

Expected context: `tailscale-k0s`. Expected readiness response: `ok`.

The generated kubeconfig points to the first controller. If it is unavailable,
change the kubeconfig server to another controller Tailscale IP. NLLB protects
worker components, not clients running on the control host.

## 4. Install Gateway API CRDs

Cilium Gateway API support requires the CRDs to exist before Cilium starts:

```bash
kubectl apply --server-side \
  -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.1/standard-install.yaml

kubectl wait --for=condition=Established --timeout=120s \
  crd/gatewayclasses.gateway.networking.k8s.io \
  crd/gateways.gateway.networking.k8s.io \
  crd/httproutes.gateway.networking.k8s.io \
  crd/grpcroutes.gateway.networking.k8s.io \
  crd/referencegrants.gateway.networking.k8s.io
```

## 5. Install Cilium

Cilium values are defined in [`cilium-values.yaml`](../../cilium-values.yaml).
They configure:

- full kube-proxy replacement
- Cilium access to `k0s` NLLB at `127.0.0.1:7443`
- `tailscale0` as the datapath device
- VXLAN tunneling over the Tailscale underlay
- cluster-pool IPAM with one `/24` per worker from `10.244.0.0/16`
- two Cilium operator replicas
- a separate Envoy DaemonSet
- Gateway API host-network mode
- Hubble, Hubble Relay, and Hubble UI

Install and wait for readiness:

```bash
cilium install --version 1.20.0 --values cilium-values.yaml
cilium status --wait
```

Expected readiness:

```text
Cilium:          OK (5/5)
Operator:        OK (2/2)
Envoy DaemonSet: OK (5/5)
Hubble Relay:    OK (1/1)
Hubble UI:       Ready (1/1)
```

## 6. Verify the cluster

```bash
kubectl get nodes -o wide
kubectl -n kube-system get pods -o wide
kubectl get gatewayclass cilium -o wide
kubectl -n kube-system get daemonset kube-proxy
```

Expected results:

- all five workers are `Ready` and use their Tailscale InternalIP
- Cilium, Envoy, CoreDNS, Hubble, NLLB, and konnectivity Pods are running
- GatewayClass `cilium` is `Accepted=True`
- querying the kube-proxy DaemonSet returns `NotFound`

Run a focused connectivity test:

```bash
cilium connectivity test \
  --ip-families ipv4 \
  --test '^no-policies/' \
  --test '^client-egress/' \
  --test '^dns-only/' \
  --hubble=false \
  --flow-validation disabled \
  --timeout 15m
```

This verified three tests and 85 actions covering baseline pod, Service,
NodePort, world, egress-policy, and DNS-policy paths.

With Cilium CLI `v0.19.7`, the `--test` flag matches the combined
`test/scenario` string. To select a whole test by name, include its trailing
slash, for example `^no-policies/`. A pattern such as `pod-to-pod` matches that
scenario in many tests and creates a much larger run. In the verified CLI,
`^no-policies$` matched nothing because the selector includes `/scenario`.

Clean test resources afterward:

```bash
cilium connectivity test --cleanup
kubectl get cnp,ccnp -A
kubectl get namespaces | grep cilium-test || true
```

## Tailscale networking notes

### MTU

Tailscale uses an MTU of `1280` in this environment. Cilium detects that device
MTU and installs cross-node VXLAN routes with an effective MTU of `1230` after
encapsulation overhead. Verify it when diagnosing fragmented packet drops:

```bash
ssh root@node-01 ip -d link show tailscale0
ssh root@node-01 ip -d link show cilium_vxlan
ssh root@node-01 ip route show
```

Do not raise the Cilium MTU above what `tailscale0` can carry. Large pings may
fail even while correctly sized application traffic works.

### Gateway listeners

Cilium Gateway API host-network mode binds listeners to all host interfaces
(`0.0.0.0` and/or `::`), not only `tailscale0`. An empty node selector exposes
listeners on every Cilium worker. Use Gateway-specific node labels to restrict
placement, and use host firewall rules when listener access must be limited to
the tailnet.

### Control-plane availability

- etcd and controller joins use Tailscale IPs.
- worker control-plane traffic uses local NLLB and can tolerate a controller
  outage.
- the local kubeconfig is not load-balanced; switch its server or later expose
  the API through the Tailscale Kubernetes Operator.
- do not add `spec.api.externalAddress` while relying on `k0s` NLLB; the two modes
  are incompatible.

### Address stability

The `k0sctl` file pins Tailscale IPv4 addresses. If a node is removed and re-added
to the tailnet with a new address, update its SSH address, `privateAddress`, API
SANs when applicable, and any Tailscale ACL grants before applying `k0sctl` again.

## References

- [`k0sctl` configuration](https://github.com/k0sproject/k0sctl#configuration-file)
- [`k0s` configuration](https://docs.k0sproject.io/stable/configuration/)
- [`k0s` networking](https://docs.k0sproject.io/stable/networking/)
- [`k0s` node-local load balancing](https://docs.k0sproject.io/stable/nllb/)
- [Cilium kube-proxy replacement](https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/)
- [Cilium Gateway API](https://docs.cilium.io/en/stable/network/servicemesh/gateway-api/)
- [Cilium Gateway host-network mode](https://docs.cilium.io/en/stable/network/servicemesh/gateway-api/host-network-mode/)
- [Cilium Hubble](https://docs.cilium.io/en/stable/observability/hubble/)
- [Cilium cluster-pool IPAM](https://docs.cilium.io/en/stable/network/kubernetes/ipam-cluster-pool/)
- [Cilium connectivity test command](https://docs.cilium.io/en/latest/cmdref/cilium_connectivity_test/)
- [Gateway API installation](https://gateway-api.sigs.k8s.io/guides/getting-started/introduction/)
