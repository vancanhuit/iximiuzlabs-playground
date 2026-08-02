# Tailscale Operator and Cilium Gateway Design

> **Implementation outcome (2026-08-02):** The API ProxyGroup design remains in
> use. The application ingress portion was replaced by a normal nginx Deployment
> behind a Tailscale `LoadBalancer` Service because Cilium 1.20 Gateway BPF
> TPROXY traffic was blackholed before Envoy and Envoy upstream traffic conflicted
> with host-level Tailscale policy routing. The authoritative implementation is
> documented in `docs/k0s/README.md`.

## Goal

Extend the existing `k0s` cluster with:

- the Tailscale Kubernetes Operator
- a two-replica Tailscale API server `ProxyGroup` using identity-backed
  Kubernetes RBAC
- Cilium Gateway API exposed through a Tailscale `LoadBalancer` Service
- public Cloudflare DNS-only records under `lab.canhdinh.com`
- cert-manager certificates issued through an ACME DNS-01 challenge
- an Echo Server deployment available at `https://echo.lab.canhdinh.com`

The implementation updates the operational runbook and the checked-in Cilium
values. It does not commit credentials or generated Secret manifests.

## Current State

The cluster runs Cilium `v1.20.0` in kube-proxy replacement mode. Gateway API is
enabled through the accepted `cilium` GatewayClass. Cilium currently exposes
Gateway listeners directly on every worker through host-network mode. No
Gateway or HTTPRoute resources currently exist, so changing the exposure model
does not require migrating an active Gateway.

## Architecture

The Tailscale operator uses its default tags:

- `tag:k8s-operator` for the operator
- `tag:k8s` for operator-managed proxies

The operator's OAuth client has write access only to Tailscale Services, core
devices, and auth keys. The tailnet policy makes `tag:k8s-operator` an owner of
`tag:k8s`.

Kubernetes API access uses a dedicated `ProxyGroup` with two replicas and
`kubeAPIServer.mode: auth`. The proxy impersonates the caller's Tailscale login,
and a Kubernetes ClusterRoleBinding grants that exact identity the required
permissions. Direct controller access remains available as a break-glass path.

Cilium host-network Gateway mode is disabled. A parameterized
`cilium-tailscale` GatewayClass uses the existing Cilium Gateway controller and
sets the generated Service to:

```yaml
type: LoadBalancer
loadBalancerClass: tailscale
```

This creates a standalone Tailscale ingress proxy for each Gateway using the
class. It does not install Envoy Gateway or an ingress ProxyGroup. Cilium's
existing Envoy implementation continues to terminate TLS and process
HTTPRoutes.

Because the cluster uses Cilium kube-proxy replacement, Cilium enables
`socketLB.hostNamespaceOnly` so traffic from Tailscale proxy Pods reaches the
generated ClusterIP and LoadBalancer Service through the packet-level service
path expected by the operator.

## DNS and TLS

Cloudflare remains authoritative for `canhdinh.com`. ExternalDNS watches Gateway
API HTTPRoutes and manages records only within `lab.canhdinh.com`. Records are
DNS-only, never Cloudflare-proxied, because Cloudflare's public proxy cannot
reach a Tailscale CGNAT address.

The public `echo.lab.canhdinh.com` record resolves to the Tailscale IP reported
in the Gateway status. Anyone can resolve the record, but only authorized
tailnet clients can route to it.

cert-manager watches annotated Gateway resources. A ClusterIssuer uses a
Cloudflare DNS-01 solver to prove control of `canhdinh.com`; the application
does not need to be publicly reachable for certificate issuance. Cilium Envoy
terminates TLS with the resulting Secret.

## Traffic Flow

```text
Tailnet client
  -> Cloudflare DNS-only record for echo.lab.canhdinh.com
  -> standalone Tailscale ingress proxy
  -> Cilium-generated LoadBalancer Service
  -> Cilium Envoy Gateway
  -> HTTPRoute
  -> Echo Server ClusterIP Service
  -> Echo Server Pod
```

The client-to-proxy leg is encrypted by Tailscale. HTTPS remains intact until
Cilium Envoy terminates TLS. The proxy-to-Gateway leg is a separate Kubernetes
network leg, not a nested Tailscale tunnel.

## Secret Boundaries

Repository-managed secret values live in `secrets/lab.sops.yaml`. SOPS encrypts
the document to the age recipient declared in `.sops.yaml`; the corresponding
private identity remains outside the repository at
`~/.config/sops/age/keys.txt`. Only the encrypted document and public recipient
are committed. Plaintext copies and private age identities must never enter Git.

The encrypted document contains both credentials and the runtime values needed
to make the runbook non-interactive:

- Tailscale OAuth client ID and client secret
- Tailscale login mapped into Kubernetes RBAC
- Cloudflare zone ID
- separate cert-manager and ExternalDNS Cloudflare API tokens
- ACME account email

The operator OAuth client is tagged `tag:k8s-operator` and has write scope for
Tailscale Services, core devices, and auth keys.

Cloudflare uses two independent API tokens, each restricted to the
`canhdinh.com` zone with `Zone:Read` and `DNS:Edit`:

- one token for cert-manager DNS-01 challenges
- one token for ExternalDNS record management

The runbook extracts only the field needed for each operation with
`sops decrypt --extract`. Because SOPS serializes a YAML scalar with a trailing
newline, command substitution first captures each credential in a short-lived,
unexported shell variable; `printf '%s'` then emits the exact bytes into
`kubectl` or a mode-`0600` temporary file. Variables are unset after use. No
complete decrypted document is written to disk.

The supported editing workflow is `sops secrets/lab.sops.yaml`. Git ignores
every path under `secrets/` and re-includes only `secrets/lab.sops.yaml`, making
the reviewed ciphertext the sole repository-trackable file in that directory.

The ACME account private key, issued TLS private key, and Tailscale proxy state
Secrets are generated by their controllers and do not require user-provided
values.

## Deployment Order

1. Verify cluster and direct kubeconfig access.
2. Enable tailnet HTTPS and update the Tailscale policy.
3. Create the scoped Tailscale OAuth client and install the operator.
4. Create and validate the API server ProxyGroup.
5. Bind the Tailscale login identity with Kubernetes RBAC and configure a
   separate proxy kubeconfig context.
6. Update and apply Cilium values, then validate Cilium and GatewayClass health.
7. Install cert-manager with Gateway API support and create the Cloudflare
   DNS-01 ClusterIssuer.
8. Install ExternalDNS with its separate Cloudflare token and scoped ownership
   settings.
9. Create the parameterized `cilium-tailscale` GatewayClass.
10. Deploy Echo Server, its Service, Gateway, and HTTPRoute.
11. Verify DNS, certificate issuance, Gateway status, HTTPS routing, tailnet
    access control, and API proxy resilience.

## Failure and Recovery

- Keep the original direct kubeconfig context until API proxy access is fully
  verified.
- If the operator fails, inspect its Deployment and OAuth Secret before creating
  proxy resources.
- If the API ProxyGroup is unavailable, use the direct controller context.
- If the Gateway remains unprogrammed, inspect the generated
  `cilium-gateway-*` Service, Tailscale operator logs, and Cilium Gateway
  conditions.
- If certificate issuance fails, inspect Certificate, Order, and Challenge
  resources and verify the cert-manager Cloudflare token permissions.
- If DNS is wrong, stop ExternalDNS before manually correcting records to avoid
  controller reconciliation undoing the repair.

## Validation

Success requires:

- the Tailscale operator Deployment is available
- both API ProxyGroup replicas are ready
- the proxy kubeconfig authenticates as the intended Tailscale identity
- Cilium and the `cilium` and `cilium-tailscale` GatewayClasses are accepted
- the generated Gateway Service has `loadBalancerClass: tailscale` and a
  Tailscale address
- the `echo.lab.canhdinh.com` Certificate is ready
- Cloudflare serves an unproxied record for `echo.lab.canhdinh.com`
- `curl https://echo.lab.canhdinh.com` succeeds from an authorized tailnet client
- the same endpoint is unreachable without tailnet connectivity

## References

- https://tailscale.com/docs/kubernetes-operator/install-operator
- https://tailscale.com/docs/kubernetes-operator/api-server-access/setup-api-over-tailscale
- https://tailscale.com/docs/solutions/kubernetes-operator-byod-gateway-api
- https://tailscale.com/docs/kubernetes-operator/reference/compatibility
- https://docs.cilium.io/en/stable/network/servicemesh/gateway-api/
- https://cert-manager.io/docs/usage/gateway/
- https://cert-manager.io/docs/configuration/acme/dns01/cloudflare/
- https://kubernetes-sigs.github.io/external-dns/latest/docs/tutorials/cloudflare/
- https://ealenn.github.io/Echo-Server/pages/quick-start/kubernetes.html
