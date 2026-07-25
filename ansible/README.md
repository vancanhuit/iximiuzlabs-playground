# Ansible Playbooks

```bash
curl https://mise.run | sh
```

```bash
mise install
```

## Kubernetes

```console
$ ansible-playbook k8s.yaml
```


```console
$ cilium install \
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

```console
$ cilium status
    /¯¯\
 /¯¯\__/¯¯\    Cilium:             OK
 \__/¯¯\__/    Operator:           OK
 /¯¯\__/¯¯\    Envoy DaemonSet:    OK
 \__/¯¯\__/    Hubble Relay:       disabled
    \__/       ClusterMesh:        disabled

DaemonSet              cilium                   Desired: 4, Ready: 4/4, Available: 4/4
DaemonSet              cilium-envoy             Desired: 4, Ready: 4/4, Available: 4/4
Deployment             cilium-operator          Desired: 1, Ready: 1/1, Available: 1/1
Containers:            cilium                   Running: 4
                       cilium-envoy             Running: 4
                       cilium-operator          Running: 1
                       clustermesh-apiserver
                       hubble-relay
Cluster Pods:          2/2 managed by Cilium
Helm chart version:    1.19.5
Image versions         cilium             quay.io/cilium/cilium:v1.19.5@sha256:20fbbc14ac20b55a292c0dcda5571bf31cde30a7dbc68c29db3e709390ab0732: 4
                       cilium-envoy       quay.io/cilium/cilium-envoy:v1.36.8-1781157951-a7f42a3390781539911b5b9107881b35ecc4e752@sha256:326f872e19ce8aa45170efbf583b3f301586ba3feead14b864676d4baf3b45ed: 4
                       cilium-operator    quay.io/cilium/operator-generic:v1.19.5@sha256:be848a365776e07d0c5a895eda7aec928ddc52a5a1fa2f432fd7a286609e1db4: 1
```

```console
$ kubectl get node -o wide
NAME               STATUS   ROLES           AGE   VERSION   INTERNAL-IP       EXTERNAL-IP   OS-IMAGE                       KERNEL-VERSION    CONTAINER-RUNTIME
control-plane-01   Ready    control-plane   32m   v1.36.3   100.108.214.118   <none>        Debian GNU/Linux 13 (trixie)   6.1.167 (amd64)   containerd://2.3.3
node-01            Ready    <none>          31m   v1.36.3   100.70.201.5      <none>        Debian GNU/Linux 13 (trixie)   6.1.167 (amd64)   containerd://2.3.3
node-02            Ready    <none>          31m   v1.36.3   100.101.106.59    <none>        Debian GNU/Linux 13 (trixie)   6.1.167 (amd64)   containerd://2.3.3
node-03            Ready    <none>          31m   v1.36.3   100.75.254.125    <none>        Debian GNU/Linux 13 (trixie)   6.1.167 (amd64)   containerd://2.3.3
```

```console
$ kubectl -n kube-system get all
NAME                                           READY   STATUS    RESTARTS   AGE
pod/cilium-envoy-4226f                         1/1     Running   0          18m
pod/cilium-envoy-7jxbg                         1/1     Running   0          18m
pod/cilium-envoy-w7wpr                         1/1     Running   0          18m
pod/cilium-envoy-wbbqj                         1/1     Running   0          18m
pod/cilium-h2ddz                               1/1     Running   0          18m
pod/cilium-jn8wc                               1/1     Running   0          18m
pod/cilium-n89cq                               1/1     Running   0          18m
pod/cilium-operator-79bf7b455c-dz59h           1/1     Running   0          18m
pod/cilium-r2lr5                               1/1     Running   0          18m
pod/coredns-589f44dc88-88qg4                   1/1     Running   0          47m
pod/coredns-589f44dc88-gr76f                   1/1     Running   0          47m
pod/etcd-control-plane-01                      1/1     Running   0          47m
pod/kube-apiserver-control-plane-01            1/1     Running   0          47m
pod/kube-controller-manager-control-plane-01   1/1     Running   0          47m
pod/kube-scheduler-control-plane-01            1/1     Running   0          47m

NAME                   TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)                  AGE
service/cilium-envoy   ClusterIP   None            <none>        9964/TCP                 36m
service/hubble-peer    ClusterIP   10.110.106.42   <none>        443/TCP                  36m
service/kube-dns       ClusterIP   10.96.0.10      <none>        53/UDP,53/TCP,9153/TCP   47m

NAME                          DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR            AGE
daemonset.apps/cilium         4         4         4       4            4           kubernetes.io/os=linux   36m
daemonset.apps/cilium-envoy   4         4         4       4            4           kubernetes.io/os=linux   36m

NAME                              READY   UP-TO-DATE   AVAILABLE   AGE
deployment.apps/cilium-operator   1/1     1            1           36m
deployment.apps/coredns           2/2     2            2           47m

NAME                                         DESIRED   CURRENT   READY   AGE
replicaset.apps/cilium-operator-66d4b75fcd   0         0         0       36m
replicaset.apps/cilium-operator-6bd9bd79df   0         0         0       29m
replicaset.apps/cilium-operator-79bf7b455c   1         1         1       18m
replicaset.apps/coredns-589f44dc88           2         2         2       47m
```
