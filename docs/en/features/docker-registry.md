---
title: Container Registry
---

# Container Registry

Container Registry is used to push and pull SForge pre-built images, avoiding repeated local builds on every machine.

## Login

```bash
docker login --username=<user> <registry-url>
```

## Pull Pre-Built Images

```bash
sforge pull --task <task_list> --registry <registry-url>/<namespace>
```

Example:

```bash
sforge pull --task ad_placement_optimization --registry registry.example.com/sforge
```

- No extra environment variables are required
- Multiple tasks are pulled in parallel
- After pulling, start the Judge Server and run normally

## Push Images

```bash
sforge push --task <task_list> --registry <registry-url>/<namespace>
```

Example:

```bash
sforge push --task ad_placement_optimization --registry registry.example.com/sforge
```

Usually push only when you need to share built images with other machines or a Kubernetes cluster.
