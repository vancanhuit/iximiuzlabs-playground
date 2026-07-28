# Ansible Playbooks

## Kubernetes

```sh
# HAProxy load balancer for control-plane nodes
ansible-playbook haproxy_k8s_control_plane.yaml
# Configure Kubernetes nodes before running kubeadm init/join
ansible-playbook k8s.yaml
```

```sh
# On control-plane-01
sudo kubeadm init \
    --control-plane-endpoint <endpoint> \
    --apiserver-advertise-address $(tailscale ip -4) \
    --skip-phases addon/kube-proxy \
    --upload-certs

# On control-plane-01 and control-plane-02
# Join command is shown in the output of the previous command, for example:
sudo kubeadm join <endpoint> \
    --apiserver-advertise-address $(tailscale ip -4) \
    --token <token> \
    --discovery-token-ca-cert-hash sha256:<hash> \
    --control-plane \
    --certificate-key <certificate-key>

# On node-01, node-02, and node-03
# Join command is shown in the output of the previous command, for example:
sudo kubeadm join <endpoint> \
    --token <token> \
    --discovery-token-ca-cert-hash sha256:<hash>
```

```sh
cilium install \
    --namespace kube-system \
    --set kubeProxyReplacement=true \
    --set ipam.mode=cluster-pool \
    --set ipam.operator.clusterPoolIPv4PodCIDRList="{10.244.0.0/16}" \
    --set ipam.operator.clusterPoolIPv4MaskSize=24 \
    --set gatewayAPI.enabled=true \
    --set gatewayAPI.hostNetwork.enabled=true \
    --set gatewayAPI.enableProxyProtocol=true \
    --set envoy.enabled=true \
    --set envoy.securityContext.capabilities.keepCapNetBindService=true \
    --set 'envoy.securityContext.capabilities.envoy[0]=NET_BIND_SERVICE' \
    --set 'envoy.securityContext.capabilities.envoy[1]=NET_ADMIN' \
    --set 'envoy.securityContext.capabilities.envoy[2]=SYS_ADMIN'

cilium status
cilium hubble enable
```
