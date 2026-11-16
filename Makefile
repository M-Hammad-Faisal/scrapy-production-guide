PY := .venv/bin/python
SCRAPY := .venv/bin/scrapy

.PHONY: setup test test-integration api lint check shell crawl-books crawl-quotes-api crawl-quotes-crawl crawl-iso crawl-iso-dst db-up db-down clean

setup:  ## create the virtualenv and install everything (needs uv: https://docs.astral.sh/uv/)
	uv venv --python 3.13 .venv
	uv pip install --python $(PY) -e ".[dev]"

test:  ## offline unit tests (fixtures, no network)
	$(PY) -m pytest -q

test-integration:  ## tests against REAL PostgreSQL + MongoDB (needs Docker running)
	docker compose up -d --wait db mongo
	-docker compose exec -T db psql -U crawler -d crawl -c "CREATE DATABASE crawl_test"
	INTEGRATION_POSTGRES_URL=postgresql+psycopg://crawler:crawler@localhost:5432/crawl_test \
	INTEGRATION_MONGO_URI=mongodb://localhost:27017 \
	$(PY) -m pytest tests/test_integration.py -q -rs

api:  ## manual-entry API on http://127.0.0.1:8000 (demo key: alice / s3cret)
	MANUAL_ENTRY_KEYS="alice:s3cret" $(PY) manage.py runserver 8000

lint:
	.venv/bin/ruff check .

check:  ## Scrapy contracts: hits the live practice site
	$(SCRAPY) check books

shell:  ## interactive selector playground
	$(SCRAPY) shell "https://books.toscrape.com/"

crawl-books:  ## 50 books, validated and stored (data/crawl.db)
	$(PY) scripts/run_spider.py books --max-items 50

crawl-quotes-api:
	$(PY) scripts/run_spider.py quotes_api

crawl-quotes-crawl:
	$(PY) scripts/run_spider.py quotes_crawl

crawl-iso:  ## mock market feed, a normal day with deliberately bad rows
	@$(PY) scripts/serve_mock.py & echo $$! > .mock.pid; sleep 1; \
	$(PY) scripts/run_spider.py iso_prices -a start_date=2026-06-15; status=$$?; \
	kill `cat .mock.pid`; rm -f .mock.pid; exit $$status

crawl-iso-dst:  ## the 23-hour and 25-hour days
	@$(PY) scripts/serve_mock.py & echo $$! > .mock.pid; sleep 1; \
	$(PY) scripts/run_spider.py iso_prices -a start_date=2026-03-08; s1=$$?; \
	$(PY) scripts/run_spider.py iso_prices -a start_date=2026-11-01; s2=$$?; \
	kill `cat .mock.pid`; rm -f .mock.pid; exit $$((s1 + s2))

db-up:  ## local PostgreSQL + MongoDB; then: export DATABASE_URL=postgresql+psycopg://crawler:crawler@localhost:5432/crawl
	docker compose up -d --wait db mongo

db-down:
	docker compose down

clean:
	rm -rf data .scrapy jobs .pytest_cache .ruff_cache
