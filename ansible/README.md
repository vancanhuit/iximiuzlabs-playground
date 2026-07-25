# Ansible Playbooks

```bash
curl https://mise.run | sh
```

```bash
mise install
```

## Kubernetes

```bash
cilium install \
    --set ipam.mode=cluster-pool \
    --set ipam.operator.clusterPoolIPv4PodCIDRList="{10.244.0.0/16}" \
    --set ipam.operator.clusterPoolIPv4MaskSize=24 \
    --set gatewayAPI.enabled=true \
    --set gatewayAPI.hostNetwork.enabled=true \
    --set envoy.enabled=true \
    --set envoy.securityContext.capabilities.keepCapNetBindService=true \
    --set 'envoy.securityContext.capabilities.envoy[0]=NET_BIND_SERVICE' \
    --set 'envoy.securityContext.capabilities.envoy[1]=NET_ADMIN' \
    --set 'envoy.securityContext.capabilities.envoy[2]=SYS_ADMIN'
```
