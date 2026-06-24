# Docker 部署指南（包含工具调用功能）

## 快速部署

新的工具调用功能已完全集成，无需修改 Docker 配置。

### 1. 首次部署

```bash
# 克隆仓库
git clone https://github.com/qingdeng888/kimi.git
cd kimi

# 切换到功能分支
git checkout 2026624

# 创建数据目录
mkdir -p data

# 配置环境变量
cp .env.example .env
nano .env  # 至少设置 ADMIN_PASSWORD

# 构建并启动
docker compose up -d --build
```

### 2. 更新部署

如果你已经在运行旧版本，更新到包含工具调用功能的版本：

```bash
# 拉取最新代码
git pull

# 重新构建并启动
docker compose up -d --build

# 查看日志
docker compose logs -f
```

### 3. 验证工具调用功能

部署完成后，测试工具调用功能：

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_api_key_here" \
  -d '{
    "model": "kimi-k2.6",
    "messages": [
      {"role": "user", "content": "帮我查询北京的天气"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "获取天气信息",
          "parameters": {
            "type": "object",
            "properties": {
              "city": {"type": "string", "description": "城市名称"}
            },
            "required": ["city"]
          }
        }
      }
    ]
  }'
```

如果响应中包含 `"finish_reason": "tool_calls"`，说明工具调用功能正常工作。

## 配置说明

### 必需配置

在 `.env` 文件中至少配置：

```env
# 管理面板密码（必填）
ADMIN_PASSWORD=your_admin_password

# Kimi Token（可选，也可以在管理面板添加）
KIMI_TOKEN=your_kimi_token

# 对外 API Key（可选，可在管理面板创建）
OPENAI_API_KEY=your_api_key
```

### 端口配置

默认端口为 8000，如需修改：

```env
PORT=8001
```

或在 `docker-compose.yml` 中修改端口映射。

## 服务管理

```bash
# 启动服务
docker compose up -d

# 停止服务
docker compose stop

# 重启服务
docker compose restart

# 查看日志
docker compose logs -f

# 查看状态
docker compose ps

# 完全删除（包括数据卷）
docker compose down -v
```

## 数据持久化

数据存储在 `./data` 目录下：

```
data/
├── kimi_accounts.json      # Kimi 账号池
├── api_keys.json           # API Keys
├── request_logs.sqlite3    # 请求日志
└── .session_secret         # 会话密钥
```

**重要：** 请备份 `data/` 目录！

## 访问服务

- **API 接口**: `http://localhost:8000/v1`
- **管理面板**: `http://localhost:8000/admin`
- **健康检查**: `http://localhost:8000/healthz`

## 使用工具调用

部署后，任何支持 OpenAI API 的客户端都可以使用工具调用功能：

### Python 示例

```python
from openai import OpenAI

client = OpenAI(
    api_key="your_api_key_here",
    base_url="http://localhost:8000/v1"
)

tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "获取天气信息",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string"}
            },
            "required": ["city"]
        }
    }
}]

response = client.chat.completions.create(
    model="kimi-k2.6",
    messages=[{"role": "user", "content": "北京天气"}],
    tools=tools
)

print(response.choices[0].message)
```

### LangChain 示例

```python
from langchain_openai import ChatOpenAI
from langchain.tools import tool

llm = ChatOpenAI(
    openai_api_key="your_api_key_here",
    openai_api_base="http://localhost:8000/v1",
    model="kimi-k2.6"
)

@tool
def get_weather(city: str) -> str:
    """获取指定城市的天气信息"""
    return f"{city}的天气是晴天，温度22度"

llm_with_tools = llm.bind_tools([get_weather])
response = llm_with_tools.invoke("北京天气怎么样？")
print(response)
```

## 故障排查

### 工具调用不生效

1. 检查模型是否支持（建议使用 `kimi-k2.6`）
2. 确认工具定义格式正确
3. 查看日志：`docker compose logs -f`
4. 检查管理面板的请求日志

### 无法访问服务

1. 检查容器状态：`docker compose ps`
2. 检查端口占用：`netstat -tuln | grep 8000`
3. 检查防火墙设置

### 性能问题

1. 增加账号并发限制（管理面板 -> 账号管理）
2. 调整环境变量：
   ```env
   KIMI_MAX_CONCURRENCY=5
   KIMI_MIN_REQUEST_INTERVAL=0.3
   ```

## 更多信息

- **完整文档**: [docs/TOOL_CALLING.md](docs/TOOL_CALLING.md)
- **示例代码**: [examples/tool_calling_example.py](examples/tool_calling_example.py)
- **实现总结**: [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)

## 安全建议

1. 使用强密码设置 `ADMIN_PASSWORD`
2. 仅在受信任网络暴露服务
3. 定期备份 `data/` 目录
4. 不要将 `.env` 文件提交到版本控制
5. 使用 HTTPS 反向代理（Nginx/Caddy）

## 生产环境部署

推荐配置：

```yaml
services:
  kimi2api:
    build: .
    container_name: kimi2api
    restart: always
    ports:
      - "127.0.0.1:8000:8000"  # 仅本地访问
    env_file:
      - .env
    volumes:
      - ./data:/app/data
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
```

配合 Nginx 反向代理：

```nginx
server {
    listen 443 ssl http2;
    server_name api.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 流式响应支持
        proxy_buffering off;
        proxy_cache off;
    }
}
```

---

**支持**: 如有问题，请查看日志或提交 Issue
