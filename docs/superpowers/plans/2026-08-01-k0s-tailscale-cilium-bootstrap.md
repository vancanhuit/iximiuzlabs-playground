# k0s Tailscale Cilium Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce validated k0sctl and Cilium configuration for an eight-node Kubernetes cluster whose underlay is Tailscale.

**Architecture:** Bootstrap k0s first with custom CNI, kube-proxy disabled, and worker-local API load balancing. Install Gateway API CRDs and Cilium in a second ordered stage using a dedicated Cilium values file.

**Tech Stack:** k0sctl v0.32.2, k0s/Kubernetes v1.36.3, Cilium v1.20.0, Gateway API v1.6.1, Tailscale.

## Global Constraints

- Use three dedicated controllers and five dedicated workers.
- Use Tailscale IPv4 addresses for SSH and k0s private addresses; force `tailscale0`.
- Connect as `root` on port 22 using Tailscale SSH; do not configure a key path.
- Use pod CIDR `10.244.0.0/16` and service CIDR `10.96.0.0/12`.
- Do not configure HAProxy, an external API address, or k0s control-plane load balancing.
- Use standard Gateway API CRDs v1.6.1.
- Do not apply the cluster configuration or create a git commit without explicit user approval.

---

### Task 1: k0sctl Cluster Definition

**Files:**
- Modify: `docs/k0s/k0s.yaml`

**Interfaces:**
- Consumes: eight Tailscale host addresses and the cluster-wide CIDRs.
- Produces: a k0sctl `Cluster` document accepted by k0sctl v0.32.2.

- [ ] **Step 1: Define all hosts**

Add each host with explicit `hostname`, `privateAddress`, `privateInterface: tailscale0`, role, and root SSH transport:

```text
control-plane-01  100.99.78.51    controller
control-plane-02  100.80.157.98   controller
control-plane-03  100.110.188.59  controller
node-01           100.100.187.71  worker
node-02           100.124.198.50  worker
node-03           100.114.226.97  worker
node-04           100.102.150.26  worker
node-05           100.108.18.99   worker
```

- [ ] **Step 2: Define embedded k0s configuration**

Set `spec.k0s.version` to `v1.36.3+k0s.0`. Under `spec.k0s.config.spec`, configure `api.onlyBindToAddress: true` so k0sctl injects each controller's Tailscale private address, plus API SANs with all three controller names and IPs. Set custom networking, both CIDRs, disabled kube-proxy, and EnvoyProxy node-local load balancing. Set `spec.options.wait.enabled` to `false`.

- [ ] **Step 3: Parse and dry-run k0sctl configuration**

Run:

```bash
rtk k0sctl apply --config docs/k0s/k0s.yaml --dry-run
```

Expected: configuration loads without YAML/schema errors; k0sctl reaches host discovery without planning mutations.

---

### Task 2: Cilium Values

**Files:**
- Create: `docs/k0s/cilium-values.yaml`

**Interfaces:**
- Consumes: k0s NLLB endpoint `127.0.0.1:7443`, pod CIDR `10.244.0.0/16`, and `tailscale0`.
- Produces: values accepted by the Cilium v1.20.0 Helm chart.

- [ ] **Step 1: Configure datapath and IPAM**

Set `kubeProxyReplacement: true`, `k8sServiceHost: 127.0.0.1`, `k8sServicePort: 7443`, `devices: [tailscale0]`, `routingMode: tunnel`, `tunnelProtocol: vxlan`, and cluster-pool IPAM using `10.244.0.0/16` with `/24` node allocations.

- [ ] **Step 2: Configure Envoy, Gateway API, and Hubble**

Set standalone `envoy.enabled: true`; enable Gateway API host-network mode with an empty node selector so listeners run on every Cilium worker; enable Hubble, Relay, and UI; set two operator replicas.

- [ ] **Step 3: Render Cilium chart**

Use Helm if installed:

```bash
rtk helm template cilium cilium \
  --repo https://helm.cilium.io \
  --version 1.20.0 \
  --namespace kube-system \
  --values docs/k0s/cilium-values.yaml
```

Expected: render succeeds with Cilium DaemonSet, standalone Envoy DaemonSet, operator Deployment, Hubble Relay, and Hubble UI resources.

If Helm is unavailable, use Cilium CLI dry-run against the values file and report that runtime discovery may require a kubeconfig.

---

### Task 3: Cross-Configuration Review

**Files:**
- Review: `docs/k0s/k0s.yaml`
- Review: `docs/k0s/cilium-values.yaml`

**Interfaces:**
- Consumes: both completed YAML documents.
- Produces: a verified two-stage bootstrap sequence.

- [ ] **Step 1: Check invariant pairs**

Confirm pod CIDRs match, kube-proxy is disabled in k0s and replaced in Cilium, Cilium's API endpoint matches k0s NLLB port 7443, and every node uses `tailscale0`.

- [ ] **Step 2: Check editor diagnostics and diff**

Run YAML diagnostics for both files, then review only relevant changes:

```bash
rtk git diff -- docs/k0s/k0s.yaml docs/k0s/cilium-values.yaml
```

Expected: only requested cluster and Cilium configuration; no secrets, unrelated edits, external API address, or HAProxy configuration.

- [ ] **Step 3: Report bootstrap sequence**

Provide these commands without executing state-changing operations:

```bash
k0sctl apply --config docs/k0s/k0s.yaml
k0sctl kubeconfig --config docs/k0s/k0s.yaml > k0s-kubeconfig
kubectl --kubeconfig k0s-kubeconfig apply --server-side \
  -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.1/standard-install.yaml
cilium install --version 1.20.0 \
  --kubeconfig k0s-kubeconfig \
  --values docs/k0s/cilium-values.yaml
```
