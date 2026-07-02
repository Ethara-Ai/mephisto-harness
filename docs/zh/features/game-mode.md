---
title: 游戏模式
---

# 游戏模式

交互式游戏任务，Agent 通过 HTTP API 玩文字冒险游戏，而非提交代码。

## 工作原理

- 任务 JSON 中标记 `"game_mode": true`
- Judge 镜像包含游戏服务器
- Agent 通过 HTTP 游戏端点进行交互
- 允许多个会话（探索不同策略）
- 使用游戏自身的评分（无测试套件）

## 游戏 API

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/v1/game/{run_id}/{task_id}/new` | 开始新会话 |
| `POST` | `/api/v1/game/{run_id}/{task_id}/{sid}/step` | 执行动作 |
| `GET` | `/api/v1/game/{run_id}/{task_id}/{sid}/status` | 查看会话状态 |
| `POST` | `/api/v1/game/{run_id}/{task_id}/{sid}/close` | 结束会话 |

## 响应格式

```json
{
  "session_id": "...",
  "observation": "You are in a dark room...",
  "score": 10,
  "peak_score": 15,
  "max_score": 350,
  "done": false,
  "moves": 5
}
```

## 可用的游戏任务

| 任务 | 类型 |
|------|------|
| Jericho Anchorhead | 文字冒险 |
| Jericho Trinity | 文字冒险 |
| Jericho Tryst of Fate | 文字冒险（草稿） |

## 会话管理

- 会话空闲 **10 分钟** 后自动关闭
- 最多 **200** 个并发会话
- 关闭某次运行的所有会话：

```
POST /api/v1/game/{run_id}/{task_id}/close-all
```
