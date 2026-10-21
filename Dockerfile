FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY domains ./domains
COPY mcp_server ./mcp_server
COPY src ./src
COPY vision ./vision

# Usuario sin privilegios (el server MCP corre como subproceso del mismo usuario).
RUN useradd --create-home app && mkdir -p /app/.data && chown -R app /app
USER app

EXPOSE 8000
# Railway inyecta PORT. Un solo worker: la memoria de conversación y el presupuesto viven en memoria.
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
