FROM python:3.11-slim
WORKDIR /app

COPY pyproject.toml ./
COPY hermes_trading ./hermes_trading
COPY state ./state
RUN pip install --no-cache-dir -e .

ENV HERMES_TRADING_MODE=paper
CMD ["python", "-m", "hermes_trading.run"]
