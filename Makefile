VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: setup test lint data drain clean

setup:  ## create venv + install dev/runtime deps
	python3 -m venv $(VENV)
	$(PIP) install -q -e ".[dev]"

test:  ## run the test suite
	$(PY) -m pytest -q

lint:  ## ruff check
	$(VENV)/bin/ruff check src scripts tests

data:  ## validate the Nezha dataset gates (GPU-free)
	$(PY) scripts/measure_gates.py
	$(PY) scripts/validate_design.py

drain:  ## run the Drain baseline on the trace-anomaly task (GPU-free)
	$(PY) scripts/run_drain.py

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__ results/runs/*.json
