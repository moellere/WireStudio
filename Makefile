# Developer entry points. `make check` runs the fast gates CI runs, so a
# green check locally should mean a green PR. The heavy external-CLI gates
# (esphome / kicad / openscad) live under `make gates`; CI runs those on
# every PR regardless.

PY  ?= python
NPM ?= npm

.PHONY: check lint test web web-test gates examples schematics enclosures coverage clean

# Everyday pre-PR gate: lint + Python tests + a CLEAN web build + web tests.
check: lint test web web-test
	@echo "make check: OK"

lint:
	ruff check .

test:
	$(PY) -m pytest -q

# Clean web build -- mirrors the Docker/CI build, which always starts from a
# fresh container. `tsc -b` caches type results in web/node_modules/.tmp; a
# stale cache once hid a real type error locally while CI stayed red, so we
# wipe it before building.
web:
	rm -rf web/node_modules/.tmp
	cd web && $(NPM) run build

web-test:
	cd web && $(NPM) run test

# Heavy gates that shell out to external CLIs. Run before a release or when
# touching examples/library; require esphome, kicad-symbols, and openscad.
gates: examples schematics enclosures coverage

examples:
	$(PY) scripts/check_examples.py

schematics:
	$(PY) scripts/check_schematics.py

enclosures:
	$(PY) scripts/check_enclosures.py

coverage:
	$(PY) scripts/coverage_matrix.py --strict

clean:
	rm -rf web/node_modules/.tmp web/dist
