fmt:
	isort openai_420 tests
	black openai_420 tests
	ruff check --fix openai_420 tests

update:
	poetry update
