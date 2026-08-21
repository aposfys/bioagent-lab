.PHONY: install serve test lint clean all

PYTHON ?= python3

all: test

install:
	$(PYTHON) -m pip install -e ".[dev]"

## Run the MCP server over stdio, read-only tools only
serve:
	$(PYTHON) -m bioagent.server

test:
	$(PYTHON) -m pytest -q

lint:
	ruff check src tests && ruff format --check src tests && mypy src

clean:
	find . -name __pycache__ -type d -exec rm -rf {} +
