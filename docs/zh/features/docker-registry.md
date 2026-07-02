---
title: 容器镜像仓库
---

# 容器镜像仓库

容器镜像仓库（Container Registry）用于推送和拉取 SForge 预构建镜像，避免在每台机器上重复本地构建。

## 登录

```bash
docker login --username=<user> <registry-url>
```

## 拉取预构建镜像

```bash
sforge pull --task <task_list> --registry <registry-url>/<namespace>
```

示例：

```bash
sforge pull --task ad_placement_optimization --registry registry.example.com/sforge
```

- 不需要额外的环境变量
- 多任务会并行拉取
- 拉取完成后，启动 Judge Server 即可正常运行

## 推送镜像

```bash
sforge push --task <task_list> --registry <registry-url>/<namespace>
```

示例：

```bash
sforge push --task ad_placement_optimization --registry registry.example.com/sforge
```

通常只在需要将已构建镜像共享给其他机器或 Kubernetes 集群时推送。
