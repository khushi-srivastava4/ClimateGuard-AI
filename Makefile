.PHONY: dev test build prod-up

dev:
	docker compose up --build

test:
	cd backend && python -m pytest tests -q

build:
	docker compose -f docker-compose.prod.yml build

prod-up:
	docker compose -f docker-compose.prod.yml up --build
