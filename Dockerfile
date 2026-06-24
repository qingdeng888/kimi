FROM node:22-slim AS web-builder
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
RUN npm run build

FROM python:3.12-slim AS python-builder
RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

# 清理缓存并添加重试逻辑
RUN rm -rf ~/.cache/uv /root/.cache/uv && \
    (uv sync --frozen --no-dev --no-install-project --compile-bytecode || \
     (echo "First attempt failed, retrying..." && sleep 2 && \
      uv sync --frozen --no-dev --no-install-project --compile-bytecode) || \
     (echo "Second attempt failed, trying without bytecode compilation..." && \
      uv sync --frozen --no-dev --no-install-project))

FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH"

COPY --from=python-builder /app/.venv /app/.venv
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
