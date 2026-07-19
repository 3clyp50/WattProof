.PHONY: run audit test lint typecheck build verify

run:
	python3 run.py

audit:
	python3 -m billhawk --sample authentic

test:
	python3 -m pytest

lint:
	python3 -m ruff check .

typecheck:
	python3 -m mypy billhawk tests

build:
	python3 -m compileall -q billhawk tests run.py

verify: test lint typecheck build
