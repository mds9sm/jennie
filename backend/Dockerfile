# Jennie — Backend (FastAPI)
# Works for both dev (docker-compose.yml) and prod (docker-compose.prod.yml)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

# Install system dependencies (git for repo ops, nodejs for MCP servers, ca-certificates for DOMO/external APIs)
RUN apt-get update && \
    apt-get install -y --no-install-recommends git nodejs npm ca-certificates && \
    update-ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# SSL: ensure Python requests uses system certs
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
# DOMO: verify SSL by default in prod. Set to false if corporate proxy re-signs certs.
# For Argo/K8s: IT can inject corporate CA cert into /etc/ssl/certs/ to enable verification.
ENV DOMO_VERIFY_SSL=true

# Pre-install GitHub MCP server
RUN npm install -g @modelcontextprotocol/server-github 2>/dev/null || true

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .
# VERSION file may be copied from repo root by CI/CD or docker-compose
COPY VERSION* ./

# Create directories for knowledge base and repo clones
RUN mkdir -p /app/knowledge /app/data-repo /app/data-repo-kb /app/data-repo-worktrees

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

# Production: no --reload (file changes from KB builds would restart the server)
# Dev: docker-compose.yml overrides with --reload
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
