# Tailscale Operator and Cilium Gateway Implementation Plan

> **Implementation outcome (2026-08-02):** Tasks for the API ProxyGroup were
> retained. The Cilium Gateway workload-ingress tasks were superseded by an nginx
> Deployment exposed through a Tailscale `LoadBalancer` Service. See
> `docs/k0s/README.md` for the deployed procedure and validation commands.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Document and configure Tailscale Operator API access and a Cilium Gateway exposed at `https://echo.lab.canhdinh.com` with Cloudflare DNS and ACME DNS-01 certificates.

**Architecture:** Store deployment credentials and runtime values in one SOPS-encrypted YAML document protected by an external age identity. Install the Tailscale Kubernetes Operator with a two-replica authenticated API server ProxyGroup, then replace Cilium Gateway host-network exposure with a parameterized Cilium GatewayClass whose generated LoadBalancer Service is managed by Tailscale while cert-manager and ExternalDNS automate TLS and public DNS-only records.

**Tech Stack:** SOPS `3.13.3`, age `1.3.1`, Tailscale Kubernetes Operator `1.98.9`, Cilium `1.20.0`, Gateway API `1.6.1`, cert-manager `1.21.1`, ExternalDNS chart `1.21.1` with app `0.21.0`, Echo Server `0.9.2`, Cloudflare DNS

## Global Constraints

- Keep direct controller kubeconfig access as a break-glass path.
- Use Tailscale API proxy auth mode and bind the exact Tailscale login identity through Kubernetes RBAC.
- Use a two-replica `kube-apiserver` ProxyGroup and a standalone workload ingress proxy.
- Publish `echo.lab.canhdinh.com` as a Cloudflare DNS-only record.
- Restrict both Cloudflare tokens to `canhdinh.com` with `Zone:Read` and `DNS:Edit`.
- Never commit OAuth credentials, Cloudflare tokens, rendered Secret manifests, or generated private keys.
- Commit only SOPS ciphertext and the public age recipient; keep the private age identity at `~/.config/sops/age/keys.txt`.
- Never write a complete decrypted secrets document to disk.
- Preserve the existing node-level Tailscale underlay, Cilium VXLAN routing, and Cilium Envoy implementation.

---

### Task 0: Add SOPS-Encrypted Lab Configuration

**Files:**
- Create: `.sops.yaml`
- Modify: `.gitignore`
- Create: `secrets/lab.sops.yaml`

**Interfaces:**
- Consumes: public age recipient `age134tr568at5vanpnt2f29925cxflwtzy2cmxrvcwt2e9tupm48vusvrl2t0` and the external identity at `~/.config/sops/age/keys.txt`.
- Produces: one encrypted source for all credential and runtime values consumed by the runbook.

- [ ] **Step 1: Configure SOPS creation rules**

Create `.sops.yaml`:

```yaml
creation_rules:
  - path_regex: ^secrets/.*\.sops\.ya?ml$
    age: age134tr568at5vanpnt2f29925cxflwtzy2cmxrvcwt2e9tupm48vusvrl2t0
```

- [ ] **Step 2: Allow only the encrypted document**

Ignore every path under `secrets/` and explicitly re-include only the reviewed
ciphertext file:

```gitignore
# Commit only the encrypted SOPS document from this directory.
secrets/**
!secrets/
!secrets/lab.sops.yaml
```

- [ ] **Step 3: Create and encrypt the schema**

Create `secrets/lab.sops.yaml` with this schema, then immediately encrypt it in
place using `sops encrypt --in-place secrets/lab.sops.yaml`:

```yaml
tailscale:
  oauth:
    client_id: REPLACE_WITH_TAILSCALE_OAUTH_CLIENT_ID
    client_secret: REPLACE_WITH_TAILSCALE_OAUTH_CLIENT_SECRET
  kubernetes_user: you@example.com
cloudflare:
  zone_id: REPLACE_WITH_CLOUDFLARE_ZONE_ID
  cert_manager_api_token: REPLACE_WITH_CERT_MANAGER_CLOUDFLARE_TOKEN
  external_dns_api_token: REPLACE_WITH_EXTERNAL_DNS_CLOUDFLARE_TOKEN
acme:
  email: you@example.com
```

- [ ] **Step 4: Verify encrypted round trips**

Run `sops filestatus secrets/lab.sops.yaml`, decrypt each required path with
`sops decrypt --extract`, and confirm the encrypted file contains SOPS metadata
but none of the plaintext placeholder values. Document
`sops secrets/lab.sops.yaml` as the only editing workflow.

### Task 1: Configure Cilium for Tailscale LoadBalancers

**Files:**
- Modify: `docs/k0s/cilium-values.yaml`

**Interfaces:**
- Consumes: Cilium `1.20.0` values and the existing kube-proxy replacement configuration.
- Produces: packet-level ClusterIP handling inside proxy Pods and LoadBalancer-backed Cilium Gateways.

- [ ] **Step 1: Enable the socket-LB compatibility mode**

Add this top-level value after `kubeProxyReplacement`:

```yaml
socketLB:
  hostNamespaceOnly: true
```

This is required by the Tailscale Operator compatibility guidance when Cilium
runs in kube-proxy replacement mode.

- [ ] **Step 2: Disable Gateway host-network mode**

Replace the current host-network block with:

```yaml
gatewayAPI:
  enabled: true
  gatewayClass:
    create: true
  hostNetwork:
    enabled: false
```

Host-network and generated LoadBalancer Service modes are mutually exclusive.

- [ ] **Step 3: Render the Cilium chart**

Run:

```bash
helm repo add cilium https://helm.cilium.io/
helm repo update
helm template cilium cilium/cilium \
  --version 1.20.0 \
  --namespace kube-system \
  --values docs/k0s/cilium-values.yaml >/dev/null
```

Expected: exit code `0` with no schema or template error.

- [ ] **Step 4: Validate the values against the live release**

Run:

```bash
helm upgrade cilium cilium/cilium \
  --version 1.20.0 \
  --namespace kube-system \
  --values docs/k0s/cilium-values.yaml \
  --dry-run=server >/dev/null
```

Expected: exit code `0`; no cluster mutation occurs.

### Task 2: Add the Operator and Gateway Runbook

**Files:**
- Modify: `docs/k0s/README.md`

**Interfaces:**
- Consumes: the values from Task 1 and the approved design at `docs/superpowers/specs/2026-08-02-tailscale-operator-cilium-gateway-design.md`.
- Produces: an ordered, copy-safe procedure with explicit secret boundaries and verification commands.

- [ ] **Step 1: Extend the version and prerequisite tables**

Record these exact versions:

```text
Tailscale Kubernetes Operator chart: 1.98.9
cert-manager chart: 1.21.1
ExternalDNS chart: 1.21.1 (app 0.21.0)
Echo Server image: ealen/echo-server:0.9.2
```

List the three user-provided secrets and three runtime values represented in
`secrets/lab.sops.yaml`.

- [ ] **Step 2: Document Tailscale policy and operator installation**

Add a section that:

- enables HTTPS for the tailnet
- defines `tag:k8s-operator` and `tag:k8s` ownership
- grants the chosen Tailscale user access to `tag:k8s` on TCP ports `80` and `443`
- auto-approves `svc:*` advertisements by `tag:k8s`
- creates an OAuth client tagged `tag:k8s-operator` with write access to Services,
  core devices, and auth keys
- installs chart `tailscale/tailscale-operator` version `1.98.9` with
  `apiServerProxyConfig.allowImpersonation=true`
- validates the Deployment, CRDs, and operator tailnet device

Extract the two OAuth fields separately with `sops decrypt --extract` into a
short-lived unexported shell variable, emit the exact value with `printf '%s'`
into a mode-`0600` temporary directory, create the Kubernetes Secret, and remove
the directory and variables through an exit trap. Do not decrypt the complete
document.

- [ ] **Step 3: Document authenticated API server ProxyGroup access**

Apply this logical configuration through a copy-safe heredoc:

```yaml
apiVersion: tailscale.com/v1alpha1
kind: ProxyGroup
metadata:
  name: tailscale-k0s-api
spec:
  type: kube-apiserver
  replicas: 2
  kubeAPIServer:
    mode: auth
    hostname: tailscale-k0s-api
```

Wait for `ProxyGroupReady=true`, bind the exact Tailscale login user to
`cluster-admin` for this personal lab, configure the proxy kubeconfig with
`tailscale configure kubeconfig`, preserve the direct context, and verify both
proxy replicas and API access. Delete one proxy Pod while issuing readiness
requests through the proxy context, require zero failed requests, and wait for
the StatefulSet to recover both replicas.

- [ ] **Step 4: Document the Cilium mode transition**

Explain why `socketLB.hostNamespaceOnly` is required and why host-network mode
must be disabled. Provide the exact `cilium upgrade --version 1.20.0 --values`
command, rollout checks, config check for `bpf-lb-sock-hostns-only: "true"`, and
GatewayClass validation.

- [ ] **Step 5: Document cert-manager and DNS-01 setup**

Install cert-manager `v1.21.1` from its OCI chart with CRDs and
`config.gatewayAPI.enabled=true`. Extract the dedicated Cloudflare token into a
short-lived unexported shell variable and emit it without SOPS's YAML newline
into `cert-manager/cloudflare-api-token`. Extract the ACME email into another
short-lived shell variable and apply a `letsencrypt-production` ClusterIssuer
using Cloudflare DNS-01.

Validate the Deployments and ClusterIssuer before creating any Certificate.

- [ ] **Step 6: Document ExternalDNS with Cloudflare**

Extract the separate ExternalDNS token into a short-lived unexported shell
variable and emit it without SOPS's YAML newline into its Kubernetes Secret.
Extract the zone ID into a short-lived shell variable. Install ExternalDNS chart
`1.21.1` with:

```text
provider.name=cloudflare
source=gateway-httproute
domain-filter=lab.canhdinh.com
zone-id-filter supplied by the operator
registry=txt
txt-owner-id=tailscale-k0s
policy=sync
```

Configure `CF_API_TOKEN` from the Secret and require DNS-only records on the
HTTPRoute.

- [ ] **Step 7: Document the parameterized Cilium GatewayClass**

Apply a `kube-system/cilium-tailscale` `CiliumGatewayClassConfig` with
`type: LoadBalancer` and `loadBalancerClass: tailscale`, then create
`GatewayClass/cilium-tailscale` with controller
`io.cilium/gateway-controller` and a parameters reference to that object.

Wait for both the config and class to report `Accepted=True`.

- [ ] **Step 8: Document the Echo Server test workload**

Deploy namespace `echoserver`, two replicas of
`ealen/echo-server:0.9.2`, and a ClusterIP Service on port `80`. Do not reuse the
upstream nginx Ingress resource.

Create an HTTPS Gateway using `cilium-tailscale`, infrastructure annotation
`tailscale.com/hostname: echo-gateway`, cert-manager annotation
`cert-manager.io/cluster-issuer: letsencrypt-production`, and TLS Secret
`echo-lab-canhdinh-com-tls`. Create an HTTPRoute for
`echo.lab.canhdinh.com` with
`external-dns.alpha.kubernetes.io/cloudflare-proxied: "false"`.

- [ ] **Step 9: Add end-to-end verification and recovery**

Include commands to verify:

- Gateway and HTTPRoute conditions
- generated `cilium-gateway-*` Service type, class, and Tailscale address
- Tailscale proxy Pod and operator logs
- Certificate, Order, and Challenge readiness
- Cloudflare A record and TXT ownership record
- `curl https://echo.lab.canhdinh.com`
- two ready Echo Server EndpointSlice endpoints
- optional Echo Server hostname responses using `?echo_env_body=HOSTNAME`
- failure without Tailscale connectivity

Keep direct kubeconfig recovery and controller-specific diagnostics adjacent to
the API proxy instructions.

### Task 3: Validate the Documentation Change

**Files:**
- Validate: `.sops.yaml`
- Validate: `secrets/lab.sops.yaml`
- Validate: `docs/k0s/README.md`
- Validate: `docs/k0s/cilium-values.yaml`
- Validate: `docs/superpowers/specs/2026-08-02-tailscale-operator-cilium-gateway-design.md`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: evidence that the checked-in configuration renders and the runbook contains no real credentials.

- [ ] **Step 1: Check patch formatting**

Run:

```bash
git diff --check
if rg -n '[[:blank:]]+$' \
  docs/superpowers/plans/2026-08-02-tailscale-operator-cilium-gateway.md \
  docs/superpowers/specs/2026-08-02-tailscale-operator-cilium-gateway-design.md; then
  exit 1
fi
```

Expected: no output and exit code `0`. The explicit scan covers the untracked
plan and specification, which `git diff --check` does not inspect.

- [ ] **Step 2: Parse repository YAML**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path
from ruamel.yaml import YAML

yaml = YAML(typ="safe")
for path in (Path("docs/k0s/cilium-values.yaml"),):
    with path.open() as stream:
        yaml.load(stream)
    print(f"valid: {path}")
PY
```

Expected: `valid: docs/k0s/cilium-values.yaml`.

- [ ] **Step 3: Validate SOPS encryption**

Verify the encrypted status and decrypt every required field independently:

```bash
sops filestatus secrets/lab.sops.yaml
sops decrypt --extract '["tailscale"]["oauth"]["client_id"]' secrets/lab.sops.yaml >/dev/null
sops decrypt --extract '["tailscale"]["oauth"]["client_secret"]' secrets/lab.sops.yaml >/dev/null
sops decrypt --extract '["tailscale"]["kubernetes_user"]' secrets/lab.sops.yaml >/dev/null
sops decrypt --extract '["cloudflare"]["zone_id"]' secrets/lab.sops.yaml >/dev/null
sops decrypt --extract '["cloudflare"]["cert_manager_api_token"]' secrets/lab.sops.yaml >/dev/null
sops decrypt --extract '["cloudflare"]["external_dns_api_token"]' secrets/lab.sops.yaml >/dev/null
sops decrypt --extract '["acme"]["email"]' secrets/lab.sops.yaml >/dev/null
```

Expected: encrypted status and exit code `0` for every extraction. Scan the
encrypted file to confirm that no placeholder value remains in plaintext.

- [ ] **Step 4: Render Cilium with the final values**

Run the Task 1 Helm template command again after all edits.

Expected: exit code `0`.

- [ ] **Step 5: Scan for accidental credentials**

Inspect the diff for values matching `tskey-`, Cloudflare bearer tokens, or
literal OAuth client secrets. Confirm that only placeholder variable names and
Kubernetes Secret names appear. Also scan the untracked plan and specification
directly instead of relying only on `git diff`.

- [ ] **Step 6: Review the final diff**

Confirm that changes are limited to the approved SOPS configuration, design,
implementation plan, runbook, Cilium values, and the user's mise tool additions.
Do not commit unless the user explicitly requests it.
