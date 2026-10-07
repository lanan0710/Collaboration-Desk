# Collaboration Desk

一个面向小团队的需求、成果提交与逐项验收协作平台。系统以不可覆盖的 V1、V2 等成果版本和操作日志保留完整过程，并在服务层统一执行角色权限、状态流转、并发版本检查与幂等校验。

## 主要功能

- 用户自主注册，注册后等待审批才能登录。
- 注册时可申请业务管理员；只有超级管理员可以批准管理员申请。
- 业务管理员可以审批普通成员，但不能创建其他管理员或超级管理员。
- 创建需求、指定负责人，并逐条维护验收条件。
- 首页分别展示“我创建的需求”和“我负责的需求”。
- 负责人搜索支持用户名和邮箱筛选。
- 状态化操作：开始处理、提交成果、逐项验收、退回修改、重新提交、确认完成。
- 成果按 V1、V2 等独立版本保存，旧提交、审核结果和附件不可覆盖。
- 成果可以提供链接、多个附件，或两者同时提供。
- 附件只能由需求提出者和负责人通过受保护接口下载。
- 操作日志、逐项审核结果和退回原因可追溯。

## 技术栈

- Python 3.12（容器镜像）
- Django 5.2
- PostgreSQL 17（Docker Compose）
- SQLite（无 PostgreSQL 环境变量时的本地默认数据库）
- Gunicorn
- WhiteNoise
- Docker / Docker Compose

## 目录结构

```text
Collaboration_Desk/
├── accounts/                  # 注册申请与账号审批
├── config/                    # Django 设置、URL、WSGI
├── demands/                   # 需求、提交、审核、附件和业务服务
├── templates/                 # 页面模板
├── media/                     # 本地成果附件，已被 Git 忽略
├── Dockerfile
├── compose.yaml
├── docker-entrypoint.sh
├── manage.py
└── requirements.txt
```

## 角色与权限

| 角色 | 能力 |
|---|---|
| 超级管理员 | Django 后台全部管理能力；可批准普通成员和业务管理员 |
| 业务管理员 | 可进入后台审批普通成员；不能批准业务管理员或创建超级管理员 |
| 需求提出者 | 创建需求；在待验收阶段逐项审核自己创建的需求 |
| 需求负责人 | 开始处理被分配的需求；提交 V1、V2 等成果版本 |

业务管理员身份不自动授予查看所有需求的权限。需求数据默认仅对该需求的提出者和负责人可见。

## 需求状态机

| 当前阶段 | 负责人操作 | 提出者操作 | 下一状态 |
|---|---|---|---|
| 待处理 | 开始处理 | 等待 | 进行中 |
| 进行中 | 提交成果 | 等待 | 待验收 |
| 待验收 | 等待 | 逐项通过并确认完成 | 已完成 |
| 待验收 | 等待 | 标记未通过项并填写退回说明 | 进行中（退回修改） |
| 退回修改 | 提交下一版本 | 等待 | 待验收 |
| 已完成 | 只读 | 只读 | — |

页面按钮同时由用户角色和需求状态决定；服务层会再次校验权限、状态、`lock_version` 和幂等请求标识，不能依靠伪造表单绕过。

## 本地运行（Windows PowerShell）

前置条件：Python 3.10 或更高版本。未设置 `POSTGRES_HOST` 时，本地默认使用项目目录中的 SQLite。

```powershell
cd D:\VSCodeProjects\Collaboration_Desk

py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

访问：

- 应用首页：<http://127.0.0.1:8000/>
- 登录：<http://127.0.0.1:8000/accounts/login/>
- 注册：<http://127.0.0.1:8000/accounts/register/>
- 管理后台：<http://127.0.0.1:8000/admin/>

`DJANGO_DEBUG=True` 且未设置 `DJANGO_SECRET_KEY` 时，仅为本地开发使用内置开发密钥。`DEBUG=False` 时必须显式提供安全密钥。

## Docker Compose 快速开始

前置条件：Docker Desktop，且支持 `docker compose` 命令。

1. 创建环境文件：

   ```powershell
   Copy-Item .env.example .env
   ```

2. 编辑 `.env`，至少替换以下值：

   ```dotenv
   DJANGO_SECRET_KEY=一段足够长且随机的值
   POSTGRES_PASSWORD=数据库强密码
   ```

   可用 Python 生成随机密钥：

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(50))"
   ```

3. 检查并启动：

   ```powershell
   docker compose config
   docker compose up --build -d
   docker compose logs -f web
   ```

4. 首次创建超级管理员：

   ```powershell
   docker compose exec web python manage.py createsuperuser
   ```

5. 打开 <http://localhost:8000/>。

容器启动脚本会在 Gunicorn 启动前执行数据库迁移和 `collectstatic`。Compose 会等待 PostgreSQL 健康检查通过，并使用命名卷保存数据库与成果附件。

停止服务但保留数据：

```powershell
docker compose down
```

删除容器及全部 PostgreSQL、附件卷数据：

```powershell
docker compose down -v
```

> `down -v` 会永久删除 Compose 卷中的业务数据和附件，请谨慎执行。

## 环境变量

| 变量 | 说明 | 示例/默认值 |
|---|---|---|
| `DJANGO_SECRET_KEY` | Django 密钥；`DEBUG=False` 时必填 | 无默认生产值 |
| `DJANGO_DEBUG` | 是否启用调试模式 | Compose 默认 `False` |
| `DJANGO_ALLOWED_HOSTS` | 逗号分隔的 Host | `localhost,127.0.0.1` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | 逗号分隔且包含协议的可信来源 | `https://desk.example.com` |
| `DJANGO_TRUST_PROXY_HEADERS` | 是否信任反向代理的 HTTPS 协议头 | `False` |
| `DJANGO_SECURE_SSL_REDIRECT` | 是否强制 HTTPS | `False` |
| `DJANGO_SESSION_COOKIE_SECURE` | Session Cookie 仅通过 HTTPS 发送 | `False` |
| `DJANGO_CSRF_COOKIE_SECURE` | CSRF Cookie 仅通过 HTTPS 发送 | `False` |
| `POSTGRES_DB` | PostgreSQL 数据库名 | `collaboration_desk` |
| `POSTGRES_USER` | PostgreSQL 用户名 | `collaboration_desk` |
| `POSTGRES_PASSWORD` | PostgreSQL 密码 | Compose 必填 |
| `POSTGRES_HOST` | 设置后启用 PostgreSQL | Compose 固定为 `db` |
| `POSTGRES_PORT` | PostgreSQL 端口 | `5432` |
| `DB_CONN_MAX_AGE` | 数据库连接复用秒数 | `60` |
| `APP_PORT` | 主机暴露端口 | `8000` |
| `GUNICORN_WORKERS` | Gunicorn worker 数量 | `3` |
| `GUNICORN_TIMEOUT` | 请求超时秒数 | `120` |

## 初次使用流程

1. 超级管理员进入 `/admin/`。
2. 新用户在 `/accounts/register/` 提交申请；申请业务管理员时必须填写理由。
3. 在后台“账号与审批 → 注册申请”中执行“批准为普通成员”“批准为业务管理员”或“拒绝注册申请”。
4. 已激活用户登录首页，创建需求、逐条添加验收条件并指定另一名已激活用户为负责人。
5. 负责人进入详情页开始处理，完成后提交成果链接、附件或两者。
6. 提出者逐项选择通过/未通过；未通过项必须填写可执行的修改说明，退回时还必须填写总说明。
7. 负责人重新提交后会生成 V2，V1 及其审核结果仍永久保留。

## 成果附件规则

- 链接和附件至少提供一项。
- 每次最多 5 个附件。
- 单个附件不超过 20 MiB，合计不超过 50 MiB。
- 支持常见文档、图片和压缩包格式。
- 附件存放在 `MEDIA_ROOT`，不会通过公开 `/media/` 路由直接暴露。
- 下载接口要求登录，并验证当前用户是需求提出者或负责人。
- 下载响应强制使用附件模式和 `nosniff`。
- Docker 中的附件保存在 `media_data` 命名卷。

## 测试与检查

本地执行：

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

容器中执行：

```powershell
docker compose exec web python manage.py check
docker compose exec web python manage.py test
```

当前测试覆盖账号审批、对象权限、状态按钮、完整 V1 → 退回 → V2 → 通过流程、并发版本校验、幂等提交、附件限制、事务失败清理和受保护下载。

## 常用维护命令

```powershell
# 查看迁移状态
docker compose exec web python manage.py showmigrations

# 手动执行迁移
docker compose exec web python manage.py migrate

# 打开 Django shell
docker compose exec web python manage.py shell

# 查看服务状态与日志
docker compose ps
docker compose logs -f web
docker compose logs -f db
```

PostgreSQL 备份示例：

```powershell
docker compose exec -T db pg_dump -U collaboration_desk collaboration_desk > backup.sql
```

还原前请先确认目标数据库和备份文件，避免覆盖错误环境。

## 生产部署注意事项

- 使用唯一且随机的 `DJANGO_SECRET_KEY`，禁止提交 `.env`。
- 设置真实域名的 `DJANGO_ALLOWED_HOSTS`。
- HTTPS 终止在可信反向代理时，配置 `DJANGO_CSRF_TRUSTED_ORIGINS=https://你的域名`，并在确认代理正确覆盖协议头后启用 `DJANGO_TRUST_PROXY_HEADERS`。
- HTTPS 验证完成后再启用三个安全开关：`DJANGO_SECURE_SSL_REDIRECT`、`DJANGO_SESSION_COOKIE_SECURE`、`DJANGO_CSRF_COOKIE_SECURE`。
- 定期备份 PostgreSQL 卷和 `media_data` 附件卷，并实际演练恢复。
- 不要由 Nginx 或对象存储直接公开整个附件目录；如迁移到外部存储，应保留应用层授权下载或使用短期签名 URL。
- 当前启动脚本适用于单个 Web 服务。横向扩容时，应将迁移拆成一次性发布任务，避免多个实例同时执行迁移。
- 正式环境建议在反向代理处设置请求体大小、速率限制、超时、访问日志与安全响应头。

## 故障排查

### Compose 提示缺少变量

确认已执行 `Copy-Item .env.example .env`，并替换 `DJANGO_SECRET_KEY` 与 `POSTGRES_PASSWORD`。

### 数据库尚未就绪

```powershell
docker compose ps
docker compose logs db
```

Web 服务会等待数据库健康检查；如果数据库持续不健康，优先检查密码、卷状态和磁盘空间。

### 管理后台没有样式

```powershell
docker compose exec web python manage.py collectstatic --noinput
docker compose restart web
```

### 修改依赖或 Dockerfile 后没有生效

```powershell
docker compose up --build -d
```

### 本地 SQLite 与 Docker 数据不一致

Docker Compose 使用独立的 PostgreSQL 命名卷，不会自动导入本地 `db.sqlite3`。如需迁移已有数据，应先制定并验证 `dumpdata` / `loaddata` 或专用迁移方案。
