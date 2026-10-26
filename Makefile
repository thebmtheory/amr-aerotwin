PY ?= .venv/bin/python
export PYTHONPATH := backend/src

.PHONY: install test lint fetch build analyse report all serve event-report

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

EVENT ?= British Grand Prix
event-report:
	$(PY) -m amr_aerotwin.cli event-report --event "$(EVENT)"

serve:
	$(PY) -m http.server 8765 --directory site
