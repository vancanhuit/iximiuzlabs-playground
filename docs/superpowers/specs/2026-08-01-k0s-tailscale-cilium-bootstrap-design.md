# k0s Tailscale Cilium Bootstrap Design

## Goal

Bootstrap a Kubernetes v1.36.3 cluster across three dedicated control planes and five workers. All node-to-node Kubernetes and Cilium underlay traffic uses each node's Tailscale IPv4 address and `tailscale0` interface.

## Stage 1: k0s

`k0s.yaml` is a k0sctl v1beta1 cluster definition. It connects as `root` over Tailscale SSH on port 22, without a key path, and pins each host's discovered Tailscale IPv4 address as its SSH and private address.

The embedded k0s configuration uses:

- k0s `v1.36.3+k0s.0`
- three `controller` hosts and five `worker` hosts
- API TLS SANs for all three controller hostnames and Tailscale IPv4 addresses
- API binding restricted to each controller's Tailscale private address
- custom CNI with pod CIDR `10.244.0.0/16` and service CIDR `10.96.0.0/12`
- kube-proxy disabled
- k0s node-local Envoy load balancing enabled, with no external API address
- k0sctl wait disabled because workers cannot become Ready before Cilium is installed

No HAProxy, control-plane VIP, or k0s control-plane load balancer is configured. Node-local load balancing supplies each worker with a Kubernetes API endpoint at `127.0.0.1:7443`.

## Stage 2: Gateway API and Cilium

Install Gateway API standard-channel CRDs v1.6.1 first with server-side apply. Then install Cilium v1.20.0 using `cilium-values.yaml`.

Cilium uses:

- full kube-proxy replacement and the worker-local API endpoint `127.0.0.1:7443`
- `tailscale0` as the selected device
- VXLAN tunnel routing over the Tailscale underlay
- cluster-pool IPAM from `10.244.0.0/16`, allocating one `/24` per node
- standalone Envoy DaemonSet
- Gateway API with host-network mode on all Cilium worker nodes
- Hubble, Hubble Relay, and Hubble UI
- two operator replicas

Cilium Gateway host-network listeners bind all host interfaces by design. Tailscale-only external exposure must be enforced with host firewall policy if required later.

## Bootstrap Commands

```bash
k0sctl apply --config k0s.yaml
k0sctl kubeconfig --config k0s.yaml > k0s-kubeconfig
kubectl --kubeconfig k0s-kubeconfig apply --server-side \
  -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.1/standard-install.yaml
cilium install --version 1.20.0 \
  --kubeconfig k0s-kubeconfig \
  --values cilium-values.yaml
```

## Validation

Static validation checks YAML parsing, k0sctl schema loading/dry-run, and Cilium Helm values rendering when available. Runtime validation checks all five workers become Ready, Cilium and Envoy DaemonSets are available, both Cilium operators are ready, Hubble Relay/UI are ready, kube-proxy is absent, and the `cilium` GatewayClass exists.

## Sources

- https://github.com/k0sproject/k0sctl#configuration-file
- https://docs.k0sproject.io/stable/configuration/
- https://docs.k0sproject.io/stable/networking/
- https://docs.k0sproject.io/stable/nllb/
- https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/
- https://docs.cilium.io/en/stable/network/servicemesh/gateway-api/
- https://docs.cilium.io/en/stable/network/servicemesh/gateway-api/host-network-mode/
- https://docs.cilium.io/en/stable/observability/hubble/
- https://docs.cilium.io/en/stable/network/kubernetes/ipam-cluster-pool/
- https://docs.cilium.io/en/stable/helm-reference/
- https://gateway-api.sigs.k8s.io/guides/getting-started/introduction/
