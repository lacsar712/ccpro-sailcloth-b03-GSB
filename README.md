# SailCloth-01 · 帆布浸渍防水台

帆布间布卷与浸渍固化台账基线项目（Django 5 + DRF + Vue 3 SPA）。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Django 5 · DRF · SimpleJWT · django-cors-headers · Gunicorn |
| 前端 | Vue 3 · Vite · Pinia · Vue Router |
| 数据库 | PostgreSQL 15 |
| 部署 | Docker Compose · Nginx（前端反代 `/api`） |

## 路径与端口

- **项目路径**：`d:\work\document\bytecode\claudeCodePro\SailCloth\SailCloth-01`
- **前端**：http://localhost:3740
- **API**：http://localhost:8740
- **PostgreSQL**：localhost:6140

## 演示账号

| 用户名 | 密码 | 角色 |
| --- | --- | --- |
| `admin` | `123456` | 管理员 |
| `worker` | `123456` | 操作工 |

登录页已预填 `admin` / `123456`。后端 entrypoint 执行 migrate + seed。

## 业务规则

布卷状态不可设为「已固化」（`cured`），除非该卷**最近一条** `DipRun` 的 `cureHours` 已记录且 **≥ 12**。

冷却闸门（浸渍中 → 原布）：

- 卷处于「浸渍中」（`dipping`）时，**未勾选「冷却已满」不得拨回原布**；后端对浸渍中 → 原布做条件更新，未勾选返回 `400`。
- 「冷却已满」仅**管理员**可在布卷专页（晾晒架右侧面板）勾选：`POST /api/rolls/{id}/set_cool_down/`；操作工只读（勾选/直改字段均 `403`）。勾选后即可在同一面板拨回原布。
- **已固化不看此勾选**；固化 → 原布不受冷却闸门约束。
- 冷却不拦浸渍登记；再次登记浸渍会把勾选重置为未满（开启新一轮冷却），原布登记浸渍后自动转为浸渍中。
- 两人并发把同一浸渍中卷拨回原布时只许一笔成功，败者收到 `409`（`POST /api/rolls/{id}/revert_to_raw/`，PATCH 同规则）。

规则实现：`backend/core/rules.py`

## 快速启动

```bash
cd d:\work\document\bytecode\claudeCodePro\SailCloth\SailCloth-01
docker compose up --build
```

浏览器打开 http://localhost:3740

## SPA 信息架构

- **登录** → 进入主工作面
- **`/` 帆布间晾晒架（主）**：按帆布间挂布卷芯片（挂签状态 `raw` / `dipping` / `cured`）；点击打开右侧面板登记 `DipRun`、切换固化状态；架下为浸渍流水次要信息流
- **`/rolls` · `/dips`（次要台账）**：保留列表/表单 CRUD，侧栏降级为「台账」入口，非主路径

API 契约不变（JWT、`/api/lofts|rolls|dips|dashboard/`）。

## 配色

海军蓝（navy）+ 帆布米色（canvas），与温室绿主题区分。
