PY ?= .venv/bin/python
export PYTHONPATH := backend/src

.PHONY: install test lint fetch build analyse report all serve pages figures

install:
	python3 -m venv .venv && $(PY) -m pip install -e ".[dev]"

test:
	AEROTWIN_OFFLINE=1 $(PY) -m pytest -q backend/tests

lint:
	$(PY) -m ruff check backend
	$(PY) -m mypy backend/src --ignore-missing-imports

fetch:
	$(PY) -m amr_aerotwin.cli fetch

build:
	$(PY) -m amr_aerotwin.cli build

analyse:
	$(PY) -m amr_aerotwin.cli analyse

report:
	$(PY) -m amr_aerotwin.cli report

all:
	$(PY) -m amr_aerotwin.cli all

serve:
	$(PY) -m http.server 8765 --directory site

# Publish the built site to the gh-pages branch, which GitHub Pages serves (run `make report` first)
pages:
	scripts/publish_pages.sh

# README images from the served site (needs Google Chrome and Node 22+; run `make serve` first)
figures:
	node scripts/figures.mjs http://localhost:8765/ docs/img
