# 生产部署（平台无关）

部署只依赖 `Dockerfile` 和环境变量，不绑定任何托管平台：可以部署到任意一台
装有 Docker 的 Linux 服务器，也可以部署到任何能构建 Dockerfile 的容器平台，
切换平台只需要搬同一组环境变量。

镜像内容：React 前端构建产物由 FastAPI 同源托管（不需要 CORS），容器监听
`8080`，启动时自动执行数据库迁移，`/api/health` 为健康检查端点。

个人数据（`config/config.toml`、`config/profile.md`、`resume/`）**不会**打进镜像；
服务器部署时从仓库目录只读挂载进容器。

## 方式一：任意 Linux 服务器（Docker Compose，推荐）

前置条件：Docker Engine 24+ 与 Compose v2.20+；服务器能 `git clone` 本仓库
（私有仓库请给服务器配只读 Deploy Key）。

首次部署：

```bash
git clone git@github.com:Lcc-CL/job-copilot.git
cd job-copilot
cp .env.production.example .env.production
# 编辑 .env.production：至少填写 SESSION_SECRET（>= 32 字符）
cp config/config.example.toml config/config.toml   # 按需填写 LLM 配置
# 把母版简历放进 resume/
./scripts/deploy.sh

# 创建登录账号（交互式输入密码，不回显）
docker compose -f docker-compose.prod.yml --env-file .env.production \
  exec app python -m job_copilot web reset-password --username <用户名>
```

`scripts/deploy.sh` 依次执行：拉取目标版本 → 构建镜像 → 启动（入口脚本自动
迁移）→ 等待健康检查通过，失败时输出最近日志并以非零退出码结束。

日常更新与回滚：

```bash
./scripts/deploy.sh                              # 部署 origin/main 最新提交
DEPLOY_REF=<tag 或 commit> ./scripts/deploy.sh   # 部署指定版本（回滚）
SKIP_PULL=1 ./scripts/deploy.sh                  # 按当前工作区部署，不拉代码
```

### 数据库

- **默认 SQLite**：`DATABASE_URL` 留空，数据库文件在 compose 的 `data` 卷
  （容器内 `/app/data`），重新部署不会丢失。导出备份（写到卷内
  `data/backups/`）：
  `docker compose -f docker-compose.prod.yml --env-file .env.production exec app python -m job_copilot web export-data`
  ，或直接备份该卷。
- **托管 PostgreSQL**：`DATABASE_URL=postgresql://user:pass@host:5432/jobcopilot`
  （`postgres://` 会自动转换）。
- **compose 自带 PostgreSQL**：在 `.env.production` 中设置
  `COMPOSE_PROFILES=postgres`、`POSTGRES_PASSWORD`，并把 `DATABASE_URL` 设为
  `postgresql://jobcopilot:<POSTGRES_PASSWORD>@postgres:5432/jobcopilot`。

### HTTPS 与反向代理

建议在同机放一个反向代理终止 TLS，并在 `.env.production` 中设置：

```
APP_BIND=127.0.0.1                 # 8080 只对本机开放
FORWARDED_ALLOW_IPS=172.16.0.0/12  # 信任 Docker 网桥传来的 X-Forwarded-For
```

登录失败限流按客户端 IP 计数。宿主机上的反向代理经 Docker 端口映射访问容器时，
容器看到的来源地址是 Docker 网桥网关；如果不设置 `FORWARDED_ALLOW_IPS`，
所有访问者会共用同一个失败计数。

Caddy 示例（自动申请证书）：

```
jobs.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

Nginx 示例：

```nginx
server {
    listen 443 ssl;
    server_name jobs.example.com;
    # ssl_certificate / ssl_certificate_key …
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 方式二：GitHub Actions 自动部署

`.github/workflows/deploy.yml` 在每次推送 `main`（或手动触发）时通过 SSH 登录
服务器，执行 `DEPLOY_REF=<本次提交> ./scripts/deploy.sh`。未配置时整个 job
自动跳过，不会报错。先按方式一完成首次部署，再在仓库
Settings → Secrets and variables → Actions 中添加：

| 类型 | 名称 | 内容 |
|---|---|---|
| Variable | `DEPLOY_HOST` | 服务器地址（设置后即启用自动部署） |
| Variable | `DEPLOY_USER` | SSH 用户（需能执行 docker） |
| Variable | `DEPLOY_PATH` | 服务器上仓库目录的绝对路径 |
| Variable | `DEPLOY_PORT` | SSH 端口，可选，默认 22 |
| Secret | `DEPLOY_SSH_KEY` | 该用户的 SSH 私钥（建议专用密钥） |
| Secret | `DEPLOY_KNOWN_HOSTS` | `ssh-keyscan -p <端口> <服务器>` 的输出，用于校验主机指纹 |

要暂停自动部署，删除 `DEPLOY_HOST` 变量即可。

## 方式三：任意容器平台

用仓库根目录的 `Dockerfile` 建一个服务，暴露端口 `8080`，健康检查路径
`/api/health`，然后按 `.env.production.example` 配置变量：

- 必填：`SESSION_SECRET`（Secret，>= 32 字符）。
- 数据库：平台提供的 PostgreSQL 连接串填到 `DATABASE_URL`。如果不设，会使用
  容器内的 SQLite，这时必须给 `/app/data` 挂持久卷，否则重启后数据丢失。
- 平台的入口代理地址填到 `FORWARDED_ALLOW_IPS`（不确定时可以询问平台或查看
  文档），否则登录限流会把所有访问者算成同一个 IP。
- `config/config.toml` 与简历不在镜像里：需要 LLM live 模式或简历改写时，
  把它们挂载到 `/app/config`、`/app/resume`。
- 账号：部署后在容器终端执行
  `python -m job_copilot web reset-password --username <用户名>`。
