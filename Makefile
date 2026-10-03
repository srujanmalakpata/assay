# Convenience targets. Everything runs through uv in the project-local .venv.
.PHONY: install run test smoke api ui a11y selenium load flaky lint format docker-up docker-test docker-down

install:
	uv sync
	uv run playwright install chromium

run:
	uv run uvicorn sut.app:create_app --factory --port 8000

test:            ## full suite (Selenium excluded), 2 workers, HTML + JUnit reports
	uv run pytest -n 2 --html=reports/report.html --self-contained-html --junitxml=reports/junit.xml

smoke:
	uv run pytest -m smoke -n 2

api:
	uv run pytest tests/unit tests/api tests/db -n 2

ui:
	uv run pytest tests/ui -n 2

a11y:
	uv run pytest -m a11y

selenium:
	uv run pytest -m selenium

load:
	uv run python load/run_load.py --users 20 --spawn-rate 5 --duration 30s

flaky:
	uv run python -m qa_suite.flaky --runs 3 --out reports/flaky -- -m smoke

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

docker-up:
	mkdir -p compose-data
	HOST_UID=$$(id -u) HOST_GID=$$(id -g) docker compose up -d --build --wait

docker-test: docker-up
	SUT_BASE_URL=http://127.0.0.1:8000 SUT_DB_PATH=compose-data/bookshop.sqlite3 uv run pytest -n 2

docker-down:
	docker compose down -v
