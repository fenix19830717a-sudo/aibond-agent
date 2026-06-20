# aibond 生产部署计划

> **目标**: 将 aibond 部署到云服务器，使用 `aib2b.bond` 域名对外提供服务
> **架构**: Nginx 反向代理 + FastAPI 后端 + 静态前端 + SQLite 数据库 + Systemd 服务管理
> **域名**: `aib2b.bond`

---

## 前置条件

- 一台云服务器（推荐 Ubuntu 22.04/24.04 LTS）
- 域名 `aib2b.bond` 已购买并配置 DNS A 记录指向服务器公网 IP
- 服务器已开放端口：22(SSH)、80(HTTP)、443(HTTPS)

---

## Task 1: 服务器环境准备

**目标**: 安装 Python、Node.js、Nginx 和必要的系统依赖

### Step 1.1: 更新系统并安装基础依赖

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv nodejs npm nginx git curl
```

### Step 1.2: 安装 PM2（Node.js 进程管理，可选）

```bash
sudo npm install -g pm2
```

### Step 1.3: 创建部署用户

```bash
sudo useradd -m -s /bin/bash aibond
sudo usermod -aG sudo aibond
sudo mkdir -p /opt/aibond
sudo chown aibond:aibond /opt/aibond
```

---

## Task 2: 部署后端服务

**目标**: 将 FastAPI 后端部署到 `/opt/aibond/backend`

### Step 2.1: 克隆/上传代码

```bash
sudo su - aibond
cd /opt/aibond
git clone <your-repo-url> .
# 或者通过 scp/rsync 上传代码
```

### Step 2.2: 创建 Python 虚拟环境并安装依赖

```bash
cd /opt/aibond/backend
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 2.3: 配置环境变量

```bash
cp .env.example .env
nano .env
```

编辑 `.env` 文件：

```env
SECRET_KEY=your-super-secret-jwt-key-change-this-in-production
DEBUG=false
DATABASE_URL=sqlite+aiosqlite:///./aibond.db
ACCESS_TOKEN_EXPIRE_MINUTES=60
CORS_ORIGINS=https://aib2b.bond,https://www.aib2b.bond
TUNNEL_ENABLED=false
```

> **重要**: `SECRET_KEY` 必须生成一个强随机密钥：
> ```bash
> python3 -c "import secrets; print(secrets.token_urlsafe(32))"
> ```

### Step 2.4: 初始化数据库

```bash
cd /opt/aibond/backend
source venv/bin/activate
python3 -c "from app.database import init_db; import asyncio; asyncio.run(init_db())"
```

### Step 2.5: 测试后端启动

```bash
cd /opt/aibond/backend
source venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

按 `Ctrl+C` 停止，确认无报错。

---

## Task 3: 部署前端

**目标**: 构建前端静态文件并部署到 `/opt/aibond/frontend/dist`

### Step 3.1: 安装前端依赖

```bash
cd /opt/aibond/frontend
npm install
```

### Step 3.2: 配置生产环境 API 地址

创建 `.env.production`：

```bash
cat > /opt/aibond/frontend/.env.production << 'EOF'
VITE_API_BASE=https://aib2b.bond
VITE_WS_BASE=wss://aib2b.bond
EOF
```

### Step 3.3: 修改 vite.config.ts（生产构建）

生产构建不需要 proxy，修改 `vite.config.ts`：

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
});
```

### Step 3.4: 构建前端

```bash
cd /opt/aibond/frontend
npm run build
```

构建输出在 `/opt/aibond/frontend/dist/`。

---

## Task 4: 配置 Nginx 反向代理

**目标**: Nginx 监听 80/443，静态文件直接服务，API/WebSocket 转发到后端

### Step 4.1: 创建 Nginx 配置文件

```bash
sudo nano /etc/nginx/sites-available/aib2b.bond
```

写入配置：

```nginx
server {
    listen 80;
    server_name aib2b.bond www.aib2b.bond;

    # 前端静态文件
    location / {
        root /opt/aibond/frontend/dist;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # API 请求转发到后端
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket 转发
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400;
    }

    # 静态文件缓存
    location /assets/ {
        root /opt/aibond/frontend/dist;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

### Step 4.2: 启用站点配置

```bash
sudo ln -sf /etc/nginx/sites-available/aib2b.bond /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

---

## Task 5: 配置 HTTPS（Let's Encrypt）

**目标**: 使用 Certbot 获取免费 SSL 证书

### Step 5.1: 安装 Certbot

```bash
sudo apt install -y certbot python3-certbot-nginx
```

### Step 5.2: 申请证书

```bash
sudo certbot --nginx -d aib2b.bond -d www.aib2b.bond
```

按提示操作，选择自动重定向 HTTP 到 HTTPS。

### Step 5.3: 自动续期测试

```bash
sudo certbot renew --dry-run
```

---

## Task 6: 配置 Systemd 服务

**目标**: 后端作为系统服务自动启动和守护

### Step 6.1: 创建 Systemd 服务文件

```bash
sudo nano /etc/systemd/system/aibond-backend.service
```

写入：

```ini
[Unit]
Description=aibond FastAPI Backend
After=network.target

[Service]
Type=simple
User=aibond
Group=aibond
WorkingDirectory=/opt/aibond/backend
Environment=PATH=/opt/aibond/backend/venv/bin
EnvironmentFile=/opt/aibond/backend/.env
ExecStart=/opt/aibond/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Step 6.2: 启动并启用服务

```bash
sudo systemctl daemon-reload
sudo systemctl enable aibond-backend
sudo systemctl start aibond-backend
sudo systemctl status aibond-backend
```

---

## Task 7: 部署 Agent SDK

**目标**: 将 Agent SDK wheel 包提供给用户下载

### Step 7.1: 确保 wheel 包存在

```bash
ls -la /opt/aibond/backend/static/packages/aibond_agent-0.1.0-py3-none-any.whl
```

### Step 7.2: Nginx 已配置静态文件服务

上面的 Nginx 配置中，`/assets/` 和根路径已经配置好，SDK 包可通过 `https://aib2b.bond/static/packages/aibond_agent-0.1.0-py3-none-any.whl` 访问。

---

## Task 8: 验证部署

### Step 8.1: 检查各服务状态

```bash
# 后端服务
sudo systemctl status aibond-backend

# Nginx
sudo systemctl status nginx

# 端口监听
sudo ss -tlnp | grep -E '80|443|8000'
```

### Step 8.2: 浏览器访问测试

- 打开 `https://aib2b.bond`
- 确认页面加载正常
- 测试登录功能
- 测试消息发送
- 测试 WebSocket 连接（浏览器 DevTools Network -> WS）

### Step 8.3: API 健康检查

```bash
curl -s https://aib2b.bond/api/groups/ | head -c 200
```

---

## Task 9: 防火墙配置（安全加固）

```bash
# 安装 UFW
sudo apt install -y ufw

# 默认拒绝所有入站
sudo ufw default deny incoming
sudo ufw default allow outgoing

# 允许必要端口
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
sudo ufw allow 443/tcp  # HTTPS

# 启用防火墙
sudo ufw enable
```

---

## 回滚方案

如果部署失败，快速回滚：

```bash
# 停止服务
sudo systemctl stop aibond-backend
sudo systemctl stop nginx

# 恢复到之前版本（如果有备份）
cd /opt/aibond && git reset --hard <previous-commit>

# 重启服务
sudo systemctl start aibond-backend
sudo systemctl start nginx
```

---

## 监控与日志

### 查看后端日志

```bash
sudo journalctl -u aibond-backend -f
```

### 查看 Nginx 日志

```bash
sudo tail -f /var/log/nginx/aib2b.bond.access.log
sudo tail -f /var/log/nginx/aib2b.bond.error.log
```

### 查看后端应用日志

```bash
sudo tail -f /opt/aibond/backend/aibond.log
```

---

## 更新部署流程

后续代码更新时：

```bash
sudo su - aibond
cd /opt/aibond
git pull origin main

# 更新后端
cd backend
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart aibond-backend

# 更新前端
cd ../frontend
npm install
npm run build

# Nginx 自动服务新构建的静态文件
```

---

## 文件清单

| 文件 | 路径 | 说明 |
|------|------|------|
| 后端代码 | `/opt/aibond/backend/` | FastAPI 应用 |
| 前端构建 | `/opt/aibond/frontend/dist/` | 静态文件 |
| 环境配置 | `/opt/aibond/backend/.env` | 生产环境变量 |
| Nginx 配置 | `/etc/nginx/sites-available/aib2b.bond` | 反向代理配置 |
| Systemd 服务 | `/etc/systemd/system/aibond-backend.service` | 后端服务管理 |
| 数据库 | `/opt/aibond/backend/aibond.db` | SQLite 数据库 |
| SSL 证书 | `/etc/letsencrypt/live/aib2b.bond/` | HTTPS 证书 |
