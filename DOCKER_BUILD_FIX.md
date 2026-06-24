# Docker 构建失败解决方案

## 问题诊断

错误信息: `Resource temporarily unavailable (os error 11)`

这是由于 `uv` 包管理器在克隆文件时遇到系统资源不足导致的。

---

## 🎯 快速解决方案（推荐）

### 方案 1: 使用简化版 Dockerfile（最快）

项目已创建 `Dockerfile.simple`，使用普通 pip 而非 uv：

```bash
# 1. 停止并删除旧容器
docker compose down

# 2. 清理缓存
docker system prune -af

# 3. 使用简化版 Dockerfile 构建
docker build -f Dockerfile.simple -t kimi2api:latest .

# 4. 修改 docker-compose.yml 使用本地镜像
# 将 docker-compose.yml 中的 build: . 改为 image: kimi2api:latest

# 5. 启动服务
docker compose up -d
```

**优点:**
- 避免 uv 的资源问题
- 构建更快、更稳定
- 功能完全相同

---

### 方案 2: 清理缓存后重试原 Dockerfile

```bash
# 1. 清理 Docker 缓存
docker system prune -af --volumes

# 2. 清理 uv 缓存（如果存在）
rm -rf ~/.cache/uv

# 3. 重新构建（已添加重试逻辑）
docker compose build --no-cache

# 4. 启动服务
docker compose up -d
```

---

### 方案 3: 增加 Docker 资源（如果使用 Docker Desktop）

1. 打开 Docker Desktop 设置
2. 进入 Resources 部分
3. 调整资源：
   - **内存**: 至少 4GB
   - **CPU**: 至少 2 核
   - **磁盘**: 至少 20GB
4. 点击 "Apply & Restart"
5. 重新构建

---

## 📝 修改 docker-compose.yml（方案 1 需要）

如果使用 `Dockerfile.simple`，需要修改 `docker-compose.yml`：

```yaml
services:
  kimi2api:
    image: kimi2api:latest  # 改为使用镜像而非构建
    # build: .  # 注释掉这一行
    container_name: kimi2api
    ports:
      - "${PORT:-8000}:8000"
    env_file:
      - .env
    environment:
      - HOST=0.0.0.0
      - PORT=8000
      - TIMEZONE=${TIMEZONE:-Asia/Shanghai}
      - TZ=${TZ:-Asia/Shanghai}
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

---

## ✅ 验证构建

构建成功后验证：

```bash
# 查看容器状态
docker compose ps

# 查看日志
docker compose logs -f

# 测试 API
curl http://localhost:8000/healthz
```

应该返回: `{"status": "ok"}`

---

## 🔍 其他可能的原因

1. **磁盘空间不足**
   ```bash
   df -h  # 检查磁盘空间
   ```

2. **内存不足**
   ```bash
   free -h  # 检查可用内存
   ```

3. **并发构建冲突**
   - 确保没有其他 Docker 构建正在运行
   - 关闭其他占用资源的应用

---

## 📞 如果问题持续

1. **使用 Dockerfile.simple**（推荐）
   - 这是最稳定的方案
   - 功能完全相同
   - 避免了 uv 的复杂性

2. **查看完整日志**
   ```bash
   docker compose build --no-cache --progress=plain > build.log 2>&1
   ```

3. **手动分步构建**
   ```bash
   # 只构建前端
   docker build --target web-builder -t kimi-web .
   
   # 只构建 Python
   docker build --target python-builder -t kimi-python .
   ```

---

## 🎉 构建成功后

测试工具调用功能：

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_api_key" \
  -d '{
    "model": "kimi-k2.6",
    "messages": [{"role": "user", "content": "测试工具调用"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "test",
        "description": "测试工具",
        "parameters": {"type": "object", "properties": {}}
      }
    }]
  }'
```

---

**建议: 直接使用方案 1 (Dockerfile.simple)，这是最快最稳定的解决方案！**
