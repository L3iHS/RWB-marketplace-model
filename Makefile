PYTHON ?= python3
PSQL = docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U hack -d marketplace

.PHONY: setup profile build check answers test diagram
setup:
	PYTHON=$(PYTHON) bash scripts/setup.sh
profile:
	.venv/bin/python scripts/profile.py
build:
	$(PSQL) -f /model/build.sql
check:
	$(PSQL) -f /checks/invariants.sql
	$(PSQL) -f /checks/reference.sql
answers:
	.venv/bin/python scripts/answers.py
test:
	.venv/bin/python -m unittest discover -s tests -v
diagram:
	$(PYTHON) scripts/render_model.py
