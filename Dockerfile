FROM python:3.12-slim

# lanforge-mcp: MCP server for Candela LANforge.
# Default entrypoint serves streamable HTTP on :8231 (suitable for remote MCP).

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY tools ./tools

RUN pip install --no-cache-dir .

# Non-root runtime user
RUN useradd --create-home mcp && mkdir -p /data && chown -R mcp:mcp /data
USER mcp
WORKDIR /data

ENV LANFORGE_MCP_REPORTS_DIR=/data/reports \
    LANFORGE_MCP_AUDIT_LOG=/data/audit.jsonl

EXPOSE 8231

ENTRYPOINT ["lanforge-mcp"]
CMD ["serve", "--transport", "http", "--bind", "0.0.0.0", "--port", "8231"]
