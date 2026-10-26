# 가상 MCP 서버 — 개발·시험 전용(운영 금지). 표준 라이브러리만 사용한다.
FROM python:3.14-slim
RUN useradd --system --uid 10001 --no-create-home mcp
WORKDIR /app
COPY mcp_virtual /app/mcp_virtual
USER 10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8641
CMD ["python", "-m", "mcp_virtual.server"]
