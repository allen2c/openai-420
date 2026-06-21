fmt:
	isort openai_420 scripts tests
	black openai_420 scripts tests
	ruff check --fix openai_420 scripts tests

test:
	pytest -q

update:
	poetry update
