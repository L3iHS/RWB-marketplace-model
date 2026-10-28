PYTHON ?= python3
VENV = .venv/bin/python

.PHONY: setup build check answers test preview profile explore

# Окружение: .venv, данные, PostgreSQL на 127.0.0.1:5433, загрузка raw.
setup:
	PYTHON=$(PYTHON) bash scripts/setup.sh

# Сборка core и mart с нуля одной транзакцией, с проверками внутри.
build:
	bash build.sh

# Сверка ответов с контрольными цифрами задания.
check:
	bash build.sh answers/99_controls.sql

# Ответы на вопросы 1–5 в artifacts/answers/ (CSV и JSON).
answers:
	$(VENV) scripts/answers.py

# Тесты: настоящая выгрузка + искусственные крайние случаи во временной базе.
test:
	$(VENV) -m unittest discover -s tests -v

# Первые строки каждой таблицы core и mart в виде pandas.
preview:
	$(VENV) scripts/preview.py

# Профиль raw в artifacts/profile.json.
profile:
	$(VENV) scripts/profile.py

# Разведка raw: 14 блоков запросов.
explore:
	bash build.sh explore/01_profiling.sql
