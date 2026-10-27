# 部署到云服务器

目标：一台 Ubuntu 22.04 云服务器（2 核 2G 即可），用 Docker Compose 运行 PostgreSQL、API、Worker 和前端 nginx，通过 `http://<公网IP>` 访问。

以下命令以阿里云 ECS（华东 2 上海）为例。内地服务器未备案时只能用 IP 访问，因此这里只开 HTTP。

```text
浏览器 ──80──> web (nginx: 静态前端 + /api 反向代理 + 限流)
                 └──> api (FastAPI) ──> postgres
                                      worker (执行排队的 Agent 任务)
api 与 worker 共享 clause_agent_files 卷（上传与修订后的 Word）
```

## 1. 安全组放行 80 端口

ECS 控制台 → 实例 → 网络与安全组 → 安全组 → 配置规则 → 入方向 → 手动添加：

- 端口 `80/80`，授权对象 `0.0.0.0/0`（网站）
- 确认已有 `22/22`（SSH）。只放行这两个；**不要放行 5432**。

## 2. 登录服务器

在 ECS 控制台点「重置实例密码」设置 root 密码并重启实例，然后在本机终端：

```bash
ssh root@47.103.203.172
```

也可以直接用控制台的「远程连接」。以下命令都在服务器上执行。

## 3. 添加 2G swap

2G 内存在构建前端镜像时可能不够，先加 swap：

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
free -h
```

## 4. 安装 Docker（阿里云源）

```bash
apt-get update
apt-get install -y ca-certificates curl gnupg git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://mirrors.aliyun.com/docker-ce/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
docker compose version
```

`docker compose version` 需要 ≥ 2.24（生产配置用到了 `!override`）。

## 5. 配置镜像加速器

内地访问 Docker Hub 不稳定。阿里云控制台 → 容器镜像服务 ACR → 镜像工具 → 镜像加速器，复制「加速器地址」，然后：

```bash
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{ "registry-mirrors": ["https://<你的加速器地址>.mirror.aliyuncs.com"] }
EOF
systemctl restart docker
docker pull postgres:16
```

如果 `docker pull` 仍然失败，跳到文末「备用方案：本地构建后上传」。

## 6. 拉取代码

```bash
git clone https://github.com/wyj1224/DOC-AGENT.git /opt/doc-agent
cd /opt/doc-agent/backend
```

仓库是私有的话，Git 会要求输入用户名和 Personal Access Token（不是 GitHub 登录密码）。

## 7. 配置 .env

```bash
cp .env.example .env
openssl rand -hex 32   # 运行三次，分别作为下面三个值
nano .env
```

必须修改的项：

| 变量 | 值 |
|---|---|
| `DEEPSEEK_API_KEY` | 你的 DeepSeek Key |
| `VISITOR_COOKIE_SECRET` | 随机串 |
| `ADMIN_TOKEN` | 随机串，导入强条库和上传模板时输入 |
| `POSTGRES_PASSWORD` | 随机串（只用字母和数字，它会被拼进数据库连接串） |

`VISITOR_COOKIE_SECURE` 保持 `false`（目前是 HTTP）。`DATABASE_URL` 不用改，容器内由 compose 覆盖。缺少上面任意一项时，compose 会直接报错而不是带着默认值上线。

## 8. 启动

```bash
alias dc='docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile app'
echo "alias dc='docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile app'" >> ~/.bashrc
dc up -d --build
```

首次构建约 5–10 分钟（pip 和 npm 已默认走阿里云 / npmmirror 源）。完成后检查：

```bash
dc ps                          # 四个服务都应为 running / healthy
curl -s localhost/api/health   # {"status":"ok"}
```

浏览器打开 `http://47.103.203.172`。

## 9. 导入数据

打开页面左下角「资料管理」，上传强制性条文 Excel 和 Word 模板。第一次操作会弹出输入框，填 `.env` 里的 `ADMIN_TOKEN`；浏览器会记住它。

## 日常运维

```bash
cd /opt/doc-agent/backend
dc logs -f worker                  # 看任务执行日志（api / web 同理）
git pull && dc up -d --build       # 更新代码
dc restart worker                  # 重启某个服务
dc stop                            # 停止（worker 会等正在执行的任务结束，最长 5 分钟）
```

备份数据库：

```bash
dc exec postgres pg_dump -U clause_agent clause_agent | gzip > ~/backup-$(date +%F).sql.gz
```

## 公网运行的保护措施

- **LLM 费用**：nginx 对每个 IP 限制 Agent 任务提交 6 次/分钟（突发 3 次），其他写接口 30 次/分钟，超出返回 429。DeepSeek 是预付费，账户里只充少量余额，最坏损失就是余额。
- **管理接口**：导入强条库、上传/删除模板需要 `ADMIN_TOKEN`。
- **数据库**：5432 只绑定在服务器本机，安全组也不放行。
- **并发**：worker 2 个槽位，每个进程最多 4 个并发 LLM 请求，适配 2G 内存。
- **未做**：HTTPS（需要域名和备案）、多机部署、数据库自动备份。

## 备用方案：本地构建后上传

服务器无法拉取 Docker Hub 镜像时，在本机（Mac，需 Docker Desktop）构建 x86 镜像后上传。镜像名必须是 compose 项目 `backend` 下的默认名：

```bash
cd backend
docker build --platform linux/amd64 -t backend-api -t backend-worker .
docker build --platform linux/amd64 -t backend-web ../frontend-vue2
docker pull --platform linux/amd64 postgres:16
docker save backend-api backend-worker backend-web postgres:16 | gzip > /tmp/doc-agent-images.tar.gz
scp /tmp/doc-agent-images.tar.gz root@47.103.203.172:/root/
```

服务器上：

```bash
gunzip -c /root/doc-agent-images.tar.gz | docker load
cd /opt/doc-agent/backend
dc up -d --no-build
```

之后更新代码时，在本机重复上面的构建和上传，再在服务器执行 `git pull && dc up -d --no-build`。
