---
title: Container Backends
---

# Container Backends

SForge uses a container backend to create work containers and judge containers. The default backend is local Docker. Switch to the `k8s` backend when you want SForge workloads to run in a Kubernetes cluster.

## Choosing a Backend

| Backend | Best for | Main requirements |
|---------|----------|-------------------|
| `docker` | Local development, task debugging, single-machine evaluation, small experiments | A working local Docker daemon |
| `k8s` | Shared clusters, high-concurrency batch evaluation, running Work/Judge pods in a cluster | `kubectl` access, images pullable by the cluster, and a Judge URL reachable from pods |

If you are trying a task locally, use the default Docker backend first. The Kubernetes backend is intended for team environments that already have a cluster and container registry.

::: warning Docker backend does not scale to large batches
Each task runs a work container plus ephemeral judge containers, each with its own CPU/memory limits. Running many tasks concurrently on one host (roughly **20+**) causes severe resource contention even on a high-end server. For large batch runs, use the `k8s` backend.
:::

## Configuration

The backend can be configured through CLI flags, environment variables, or experiment YAML:

```bash
# Override for one run
sforge run \
  --task ad_placement_optimization \
  --agent claude-code \
  --backend k8s \
  --judge-url http://10.0.0.12:8080 --backend k8s

# Override through environment variables
export SFORGE_BACKEND=k8s
sforge run \
  --task ad_placement_optimization \
  --agent claude-code \
  --backend k8s \
  --judge-url http://10.0.0.12:8080
```

Experiment YAML can also set the default backend:

```yaml
defaults:
  agent: claude-code
  backend: k8s

tasks:
  ad_placement_optimization: {}
```

## Docker Backend

Docker is the default backend and needs no explicit backend configuration:

```bash
sforge build --task ad_placement_optimization
sforge serve

export SFORGE_AGENT_API_KEY="sk-..."
sforge run \
  --task ad_placement_optimization \
  --agent claude-code \
  --backend k8s \
  --judge-url http://10.0.0.12:8080
```

The Docker backend:

- uses the local Docker daemon to build and run images
- starts Work containers and Judge containers in local Docker
- uses the default `http://host.docker.internal:8080` so containers can reach the Judge HTTP server on the host
- uses host-side network isolation when `--disable-internet` is enabled

Resource limits can be configured through CLI flags or environment variables:

```bash
sforge run \
  --task ad_placement_optimization \
  --agent claude-code \
  --work-cpu-limit 4 \
  --work-mem-limit 8g \
  --judge-cpu-limit 2 \
  --judge-mem-limit 4g
```

## Kubernetes Backend

The Kubernetes backend creates pods through `kubectl`. Each SForge container maps to one Kubernetes Pod with a container named `work`. Pods are labeled with `app=sforge` and `sforge-pod=<pod-name>`.

### Prerequisites

Before using the `k8s` backend, make sure that:

1. `kubectl` is installed locally and can access the target cluster.
2. The target namespace exists, and your kubeconfig can create, query, and delete Pods.
3. Work/Judge images have been pushed to a registry reachable by Kubernetes nodes.
4. The SForge Judge HTTP server is reachable from pods in the cluster.
5. If you use `--disable-internet`, the cluster supports and enforces Kubernetes `NetworkPolicy`.

You can first verify cluster access with:

```bash
kubectl -n <namespace> cluster-info
kubectl -n <namespace> get pods
```

### Kubernetes Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SFORGE_BACKEND` | `docker` | Set to `k8s` to enable the Kubernetes backend |
| `SFORGE_K8S_NAMESPACE` | `default` | Namespace used for Pods and NetworkPolicies |
| `SFORGE_K8S_IMAGE_REGISTRY` | --- | Registry prefix prepended to image names when pods pull images |
| `SFORGE_K8S_KUBECONFIG` | --- | kubeconfig path; if unset, the default `kubectl` configuration is used |
| `SFORGE_K8S_NODE_SELECTOR` | --- | Pod node selector, format: `"key1=val1,key2=val2"` |

### Preparing Images

Kubernetes nodes cannot use images that exist only in your local Docker daemon. With the k8s backend, you usually need to build and push images first:

```bash
# Build images locally
sforge build --task ad_placement_optimization

# Push them to a registry reachable by the cluster
sforge push --task ad_placement_optimization --registry registry.example.com/sforge
```

Then configure the k8s backend to use the same registry prefix:

```bash
export SFORGE_K8S_IMAGE_REGISTRY=registry.example.com/sforge
```

The Kubernetes backend resolves internal image names as:

```text
${SFORGE_K8S_IMAGE_REGISTRY}/<sforge-image-name>:<tag>
```

::: tip
`sforge build` still builds images with local Docker. The `k8s` backend runs Work/Judge pods; it does not build images inside the cluster.
:::

### Judge URL

`--judge-url` is the Judge server address visible from inside the Work container or pod. The Docker default `http://host.docker.internal:8080` is usually only valid for local Docker, not for Kubernetes pods.

For k8s, pass a pod-reachable address with `--judge-url`, such as a host private IP, LoadBalancer, Ingress, or in-cluster Service.

Start the local Judge server with:

```bash
sforge serve --host 0.0.0.0 --port 8080
```

Then run:

```bash
sforge run \
  --task ad_placement_optimization \
  --agent claude-code \
  --backend k8s \
  --judge-url http://10.0.0.12:8080
```

### Full Example

```bash
# 1. Build and push images
sforge build --task ad_placement_optimization
sforge push --task ad_placement_optimization --registry registry.example.com/sforge

# 2. Configure the k8s backend
export SFORGE_BACKEND=k8s
export SFORGE_K8S_NAMESPACE=sforge
export SFORGE_K8S_IMAGE_REGISTRY=registry.example.com/sforge
export SFORGE_K8S_KUBECONFIG=$HOME/.kube/config

# Optional: schedule only onto a specific node pool
export SFORGE_K8S_NODE_SELECTOR="pool=sforge"

# 3. Start the Judge server, ensuring pods can reach this address
sforge serve --host 0.0.0.0 --port 8080

# 4. In another terminal, run the agent
export SFORGE_AGENT_API_KEY="sk-..."
sforge run \
  --task ad_placement_optimization \
  --agent claude-code \
  --backend k8s \
  --judge-url http://10.0.0.12:8080
```

### Resource Limits

Work/Judge CPU and memory limits also apply to the k8s backend. SForge converts them to Pod resource requests/limits:

```bash
sforge run \
  --task ad_placement_optimization \
  --agent claude-code \
  --backend k8s \
  --work-cpu-limit 4 \
  --work-mem-limit 8g \
  --judge-cpu-limit 2 \
  --judge-mem-limit 4g
```

Memory formats are converted from Docker style to Kubernetes style, for example `8g` to `8Gi` and `512m` to `512Mi`.

### Network Isolation

With the Docker backend, `--disable-internet` uses host-side network isolation. With the Kubernetes backend, SForge creates a Kubernetes `NetworkPolicy` to restrict pod egress to the Judge server, the configured LLM API endpoint, and DNS.

Notes:

- The cluster CNI must support and enforce `NetworkPolicy`; otherwise the policy may have no effect.
- Your kubeconfig must be allowed to create and delete `NetworkPolicy` resources.
- DNS, egress gateways, and policy implementations differ between clusters, so validate isolation with a small task first.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `kubectl cluster-info failed` | Wrong kubeconfig, unreachable cluster, or wrong namespace context | Check `kubectl -n <namespace> cluster-info`; set `SFORGE_K8S_KUBECONFIG` and `SFORGE_K8S_NAMESPACE` if needed |
| Pod never becomes Running | Image pull failure, scheduling failure, or insufficient resources | Run `kubectl -n <namespace> describe pod <pod>` and check events |
| Pod cannot pull image | Image was not pushed to a registry reachable by the cluster, or registry credentials are missing | Run `sforge push`; verify `SFORGE_K8S_IMAGE_REGISTRY`; configure image pull secrets for the namespace |
| Work pod cannot submit evaluations | `--judge-url` is not reachable from pods, or the Judge server is not listening externally | Start `sforge serve` with `--host 0.0.0.0` and pass a pod-reachable IP/Service URL with `--judge-url` |
| `--disable-internet` has no effect | CNI does not enforce NetworkPolicy, or permissions are insufficient | Confirm NetworkPolicy support and verify the current identity can create NetworkPolicies |
| Pod stays Pending after setting a node selector | No nodes match the selector | Check `SFORGE_K8S_NODE_SELECTOR` and node labels |
