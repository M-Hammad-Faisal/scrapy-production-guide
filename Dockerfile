FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Install dependencies first so Docker caches this layer when only code changes.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install "scrapy>=2.13" sqlalchemy "psycopg[binary]" python-dotenv tzdata

COPY crawlers ./crawlers
COPY scripts ./scripts
COPY scrapy.cfg ./

# Run as a non-root user.
RUN useradd --create-home crawler && chown -R crawler /app
USER crawler

# The wrapper exits non-zero on a bad run, so the scheduler can alert.
ENTRYPOINT ["python", "scripts/run_spider.py"]
CMD ["books", "--max-items", "50"]
