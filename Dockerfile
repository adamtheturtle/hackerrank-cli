FROM python:3.13-slim AS build
LABEL org.opencontainers.image.source="https://github.com/adamtheturtle/hackerrank-cli"
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv
WORKDIR /build
COPY . .
ARG HACKERRANK_CLI_VERSION=0.0.0
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN SETUPTOOLS_SCM_PRETEND_VERSION_FOR_HACKERRANK_CLI=$HACKERRANK_CLI_VERSION uv build --wheel --out-dir /wheels
RUN uv pip compile pyproject.toml -o /tmp/runtime.txt && uv run --no-project --with pip python -m pip wheel --wheel-dir /wheels -r /tmp/runtime.txt

FROM python:3.13-slim
LABEL org.opencontainers.image.source="https://github.com/adamtheturtle/hackerrank-cli"
LABEL org.opencontainers.image.description="Upload HackerRank question starter code"
LABEL org.opencontainers.image.licenses="MIT"
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index --no-deps /wheels/*.whl && rm -rf /wheels
ENTRYPOINT ["hackerrank"]
