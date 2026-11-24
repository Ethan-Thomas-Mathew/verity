# One image runs Shelf, the Verity API and the migrations, with different commands.
FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

FROM python:3.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY requirements ./requirements
COPY eval/ground_truth.json ./eval/ground_truth.json
COPY src ./src
RUN uv sync --frozen --no-dev

# Chromium and the system libraries it needs, for UI tests.
RUN playwright install --with-deps chromium && chmod -R a+rX /ms-playwright

RUN useradd --create-home --uid 10001 verity && chown -R verity /app
USER verity
EXPOSE 8000 8001
CMD ["uvicorn", "--factory", "verity.api.app:create_app", "--host", "0.0.0.0", "--port", "8000"]
