FROM python:3.12-slim

WORKDIR /app

# system deps kept minimal; scientific wheels are prebuilt for 3.12
COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --no-cache-dir -e ".[dashboard,dev]"

# safe defaults baked in: nothing live, local sqlite
ENV LIVE_TRADING=false \
    CONFIRM_LIVE_TRADING=false \
    DATABASE_URL=sqlite:////data/stat_arb.db

VOLUME ["/data"]

ENTRYPOINT []
CMD ["statarb", "--help"]
