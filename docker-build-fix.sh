#!/bin/bash

echo "🔧 Docker 构建修复脚本"
echo "================================"

# 方案 1: 清理所有缓存
echo ""
echo "方案 1: 清理 Docker 和系统缓存"
echo "--------------------------------"
echo "执行命令:"
echo "  docker system prune -af --volumes"
echo "  rm -rf ~/.cache/uv"
echo "  docker compose build --no-cache"
echo ""

# 方案 2: 增加 Docker 资源
echo "方案 2: 增加 Docker 资源限制"
echo "--------------------------------"
echo "如果使用 Docker Desktop，请增加："
echo "  - 内存: 至少 4GB"
echo "  - CPU: 至少 2 核"
echo "  - 磁盘空间: 至少 20GB"
echo ""

# 方案 3: 使用更简单的构建方式
echo "方案 3: 使用普通 pip 而非 uv"
echo "--------------------------------"
echo "创建一个临时 Dockerfile.simple:"
echo ""
cat << 'DOCKERFILE'
FROM node:22-slim AS web-builder
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app

# 直接使用 pip 安装
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    fastapi>=0.115.0 \
    httpx>=0.24.0 \
    uvicorn>=0.30.0 \
    python-dotenv>=1.0.0 \
    itsdangerous>=2.1.0 \
    python-multipart>=0.0.6 \
    tzdata>=2024.1

COPY app/ app/
COPY --from=web-builder /app/static/dist/ app/static/dist/
COPY run.py .

RUN mkdir -p /app/data

ENV HOST=0.0.0.0
ENV PORT=8000
ENV TIMEZONE=Asia/Shanghai
ENV TZ=Asia/Shanghai

EXPOSE 8000

CMD ["python", "run.py"]
DOCKERFILE

echo ""
echo "然后执行:"
echo "  docker build -f Dockerfile.simple -t kimi2api:latest ."
echo ""

# 推荐方案
echo "🎯 推荐操作顺序"
echo "================================"
echo "1. 先尝试清理缓存重新构建："
echo "   docker system prune -af"
echo "   docker compose build --no-cache"
echo ""
echo "2. 如果还是失败，使用简化版 Dockerfile："
echo "   将上面的 Dockerfile.simple 保存"
echo "   docker build -f Dockerfile.simple -t kimi2api:latest ."
echo ""
echo "3. 确保系统资源充足："
echo "   - 可用内存 > 2GB"
echo "   - 可用磁盘 > 10GB"
echo "   - 关闭其他占用资源的程序"
echo ""

