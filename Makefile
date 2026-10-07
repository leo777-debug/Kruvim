.PHONY: install api web worker test lint typecheck build up down logs migrate seed mock

install:
	cd backend && pip install -r requirements.txt -r requirements-dev.txt
	cd frontend && npm install

api:
	cd backend && uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

worker:          # requires KRUVIM_REDIS_URL
	cd backend && arq app.workers.main.WorkerSettings

migrate:
	cd backend && alembic upgrade head

seed:            # local demo account (never in production)
	cd backend && python -m scripts.seed_demo

mock:            # OpenAI-compatible mock model server on :8499
	cd backend && python tools/mock_openai_server.py

test:
	cd backend && pytest -q

lint:
	cd backend && ruff check app tests scripts migrations tools

typecheck:
	cd frontend && npx tsc --noEmit -p .

build:
	cd frontend && npx vite build

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api worker
