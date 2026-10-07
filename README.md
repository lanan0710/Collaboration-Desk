# Collaboration Desk

一个面向小团队的需求、成果提交与逐项验收协作平台。系统以不可覆盖的 V1、V2 等成果版本和操作日志保留完整过程，并在服务层统一执行角色权限、状态流转、并发版本检查与幂等校验。

## 主要功能

- 用户自主注册，注册后等待审批才能登录。
- 注册时可申请业务管理员；只有超级管理员可以批准管理员申请。
- 业务管理员可以审批普通成员，但不能创建其他管理员或超级管理员。
- 创建需求、指定负责人，并逐条维护验收条件。
- 首页分别展示“我创建的需求”和“我负责的需求”，支持按状态、角色关系和标题关键词组合筛选。
- 负责人搜索支持用户名和邮箱筛选。
- 状态化操作：开始处理、提交成果、逐项验收、退回修改、重新提交、确认完成。
- 成果按 V1、V2 等独立版本保存，旧提交、审核结果和附件不可覆盖。
- 成果必须提供 HTTP/HTTPS 链接，也可以同时附加多个文件。
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
| 待处理 | 开始处理 | 可编辑需求正文与验收条件 | 进行中 |
| 进行中 | 提交成果 | 等待 | 待验收 |
| 待验收 | 等待 | 逐项通过并确认完成 | 已完成 |
| 待验收 | 等待 | 标记未通过项并填写退回说明 | 进行中（退回修改） |
| 退回修改 | 提交下一版本 | 等待 | 待验收 |
| 已完成 | 只读 | 只读 | — |

页面按钮同时由用户角色和需求状态决定；服务层会再次校验权限、状态、`lock_version` 和幂等请求标识，不能依靠伪造表单绕过。

## 架构设计与关键取舍

```text
浏览器
  │  Django 模板表单 / CSRF
  ▼
Views + Forms（输入校验与反馈）
  │
  ▼
事务服务层（角色、状态、行锁、版本与幂等校验）
  │
  ├── Django ORM ── PostgreSQL 命名卷
  └── 受保护附件 ── media_data 命名卷
```

- 状态变化集中在 `demands/services.py`，页面隐藏按钮不是权限边界。
- `select_for_update()` 串行化同一需求的并发写入，`lock_version` 拒绝旧页面操作。
- 提交和审核使用 UUID 幂等标识；重复请求返回原记录，不生成重复版本。
- `Submission`、`Review`、`ReviewResult` 和 `OperationLog` 采用追加式历史，旧记录不可从业务页面修改或删除。
- 无关用户通过对象级查询范围得到 404；即使直接请求详情、附件或操作 URL，也无法越权。

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

4. 创建可复现的验收账号与演示数据：

   ```powershell
   docker compose exec web python manage.py seed_demo_data
   ```

5. 如需使用 Django 后台，再创建超级管理员：

   ```powershell
   docker compose exec web python manage.py createsuperuser
   ```

6. 打开 <http://localhost:8000/>。

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
5. 提出者可在待处理阶段编辑需求；负责人开始处理后正文和验收条件被冻结。
6. 负责人进入详情页开始处理，完成后提交 HTTP/HTTPS 成果链接和完成说明，可同时上传附件。
7. 提出者逐项选择通过/未通过；未通过项必须填写可执行的修改说明，退回时还必须填写总说明。
8. 负责人重新提交后会生成 V2，V1 及其审核结果仍永久保留。

## 成果附件规则

- HTTP/HTTPS 成果链接为必填项；FTP、文件协议和空链接均会被拒绝。
- 附件是补充材料，不能替代成果链接。
- 每次最多 5 个附件。
- 单个附件不超过 20 MiB，合计不超过 50 MiB。
- 支持常见文档、图片和压缩包格式。
- 附件存放在 `MEDIA_ROOT`，不会通过公开 `/media/` 路由直接暴露。
- 下载接口要求登录，并验证当前用户是需求提出者或负责人。
- 下载响应强制使用附件模式和 `nosniff`。
- Docker 中的附件保存在 `media_data` 命名卷。

## 验收账号与演示数据

在全新环境迁移完成后执行：

```powershell
docker compose exec web python manage.py seed_demo_data
```

命令可重复执行，不会重复创建需求；它会准备以下普通账号：

| 用途 | 用户名 | 密码 |
|---|---|---|
| 需求提出者 A | `demo_proposer` | `DemoPass!2026` |
| 需求负责人 B | `demo_assignee` | `DemoPass!2026` |
| 无关账号 C | `demo_outsider` | `DemoPass!2026` |

同时创建四条带 `[演示]` 前缀的需求：待处理、进行中、待验收、已完成各一条。待处理需求含三条验收条件；已完成需求保存 V1 退回、V2 通过以及两次逐项审核的完整历史。

这些账号仅用于本题本地验收，部署到公开环境前应删除或修改密码。

## 关键验收场景

### 场景一：V1 退回、V2 通过

1. 使用 A 创建需求并指定 B，B 点击“开始处理”。
2. B 提交 V1 的 HTTPS 链接和完成说明，状态变为待验收。
3. A 将至少一项标为未通过，填写逐项修改说明和退回总原因。
4. B 能看到 V1 反馈并提交 V2；A 全部勾选通过后确认完成。
5. 详情页应同时保留 V1、V2、对应审核人和时间、逐项反馈以及操作时间线。

`seed_demo_data` 创建的 `[演示] V1 退回后 V2 通过` 可直接用于检查该结果。

实际结果（2026-10-07）：PostgreSQL 演示库中保留 V1、V2 两条独立提交，审核结论依次为 `returned`、`approved`，操作日志依次为 `create → start → submit → return → submit → approve`；完整流程自动化测试通过。

### 场景二：权限与状态异常

1. C 直接访问 A/B 需求详情或附件，应得到 404。
2. B 伪造验收请求、A 伪造成果提交，应得到 403，需求状态不变。
3. 已完成需求不再展示提交或验收入口；伪造新请求也不能继续推进。

对应自动化测试覆盖详情、下载和操作接口，不依赖隐藏按钮实现权限。

实际结果（2026-10-07）：无关账号访问详情与附件返回 404；错误角色操作返回 403；已完成需求不能继续提交或验收，相关权限与状态测试全部通过。

### 场景三：重复、旧页面与持久化

1. 用同一幂等标识重复提交，提交数量仍为 1；相同标识配不同内容会明确报错。
2. 保留旧页面，在另一页面完成状态变化后再提交，页面提示“数据已过期”，不会越过流程。
3. 记录演示数据数量，执行 `docker compose up -d --force-recreate db web`，等待健康后再次登录；账号、需求、V1/V2、审核历史和附件仍应存在。

执行第三步时不要使用 `docker compose down -v`，因为 `-v` 会主动删除持久卷。

实际结果（2026-10-07）：重复幂等标识没有生成新版本，旧 `lock_version` 请求收到过期提示；保留命名卷强制重建 `db`、`web` 后，3 个账号、4 条演示需求、V1/V2、两次审核与六步日志均仍可读取，登录页返回 HTTP 200。

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

当前测试覆盖账号审批、待处理需求编辑与冻结、组合筛选、对象权限、状态按钮、HTTP/HTTPS 链接约束、完整 V1 → 退回 → V2 → 通过流程、并发版本校验、幂等提交、演示数据幂等性、附件限制、事务失败清理和受保护下载。

### 2026-10-07 实测结果

| 检查项 | 环境 | 结果 |
|---|---|---|
| `python manage.py check` | 本地虚拟环境 / SQLite | 通过，无系统检查问题 |
| `python manage.py makemigrations --check --dry-run` | 本地虚拟环境 / SQLite | 通过，无遗漏迁移 |
| `python manage.py test` | 本地虚拟环境 / SQLite | 45 项全部通过 |
| `python manage.py test` | Docker Compose / PostgreSQL 17 | 45 项全部通过 |
| `seed_demo_data` 连续执行两次 | Docker Compose / PostgreSQL 17 | 仍为 3 个账号、4 条演示需求，无重复数据 |
| 强制重建 `db`、`web` 容器后复查 | Docker Compose 命名卷 | 四种需求状态、V1/V2、退回/通过审核和六步日志均保留 |

测试使用独立测试数据库，不会修改正常运行库；持久化复查没有使用 `down -v`。

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

## 第三方组件与自行实现范围

| 组件 | 来源 | 本项目用途 |
|---|---|---|
| Django 5.2 | [Django 官方项目](https://www.djangoproject.com/) | Web 框架、ORM、认证、表单和测试框架 |
| PostgreSQL 17 | [PostgreSQL 官方项目](https://www.postgresql.org/) | Docker 环境的持久化关系数据库 |
| Gunicorn | [Gunicorn 官方文档](https://gunicorn.org/) | 容器内 WSGI 服务 |
| WhiteNoise | [WhiteNoise 官方文档](https://whitenoise.readthedocs.io/) | 容器内静态文件服务 |
| psycopg 3 | [Psycopg 官方项目](https://www.psycopg.org/) | Django 与 PostgreSQL 的数据库驱动 |
| Docker Compose | [Docker 官方文档](https://docs.docker.com/compose/) | Web、数据库、健康检查和命名卷编排 |

除上述通用开源组件外，需求状态机、对象级权限、事务服务、并发版本检查、幂等处理、逐项验收、版本历史、受保护附件接口、页面模板、演示数据命令和项目测试均为本项目自行实现。项目没有接入外部业务 API、CDN 或第三方身份提供商。

## 已知限制

- Compose 启动脚本会在 Web 启动前迁移数据库，适合当前单 Web 服务；横向扩容时应改为一次性发布任务。
- 附件保存在单机 Docker 命名卷，尚未接入共享对象存储、病毒扫描和异地备份。
- 首页筛选面向小团队数据量，尚未提供分页、全文检索、通知或邮件提醒。
- 注册审批和业务管理员是扩展功能；当前审批入口依赖 Django 管理后台，没有单独的前台审批工作台。
- 演示账号使用公开固定密码，只应用于本地验收，不能直接用于互联网生产环境。
- 退回说明通过必填与逐项反馈保证可执行信息入口，但未使用自然语言模型自动判断说明质量。

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
