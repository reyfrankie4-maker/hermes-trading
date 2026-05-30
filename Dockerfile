FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

COPY pyproject.toml ./
COPY hermes_trading ./hermes_trading
COPY state ./state
ENV UV_SYSTEM_PYTHON=1
RUN uv sync

ENV HERMES_TRADING_MODE=paper
CMD ["python", "-m", "hermes_trading.run"]
