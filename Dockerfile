FROM node:20-bookworm-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/usr/local/bin:$PATH

RUN sed -i 's|deb.debian.org/debian|mirrors.aliyun.com/debian|g; s|deb.debian.org/debian-security|mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::ForceIPv4=true update \
    && apt-get -o Acquire::ForceIPv4=true install -y --no-install-recommends bash ca-certificates ffmpeg nginx fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

WORKDIR /app
COPY backend/pyproject.toml backend/setup.py ./backend/
RUN python -m pip install --no-cache-dir --index-url https://mirrors.aliyun.com/pypi/simple/ ./backend
COPY backend/ ./backend/
COPY profiles/ ./profiles/
COPY --from=frontend-build /build/frontend/dist/ /usr/share/nginx/html/
COPY docker/nginx.conf /etc/nginx/conf.d/bili-knowledge.conf
COPY docker/entrypoint.sh /usr/local/bin/bili-knowledge-entrypoint
COPY docker/bashrc /root/.bashrc
RUN chmod +x /usr/local/bin/bili-knowledge-entrypoint \
    && mkdir -p /app/data /app/source-output /app/knowledge-base

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)"
ENTRYPOINT ["bili-knowledge-entrypoint"]
