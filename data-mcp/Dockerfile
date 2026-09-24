# Jennie Data MCP — thin Redshift + MWAA access service
# Deployed as data-mcp in np K8s (separate from Genie backend)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY data_mcp/ ./data_mcp/

ENV PYTHONPATH=/app
ENV REDSHIFT_MODE=real

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "data_mcp.main:app", "--host", "0.0.0.0", "--port", "8000"]
