# autogram — developer entrypoints. POSIX shells (Linux/macOS/WSL/Git Bash).
.DEFAULT_GOAL := help
SHELL := /bin/bash
PY ?= python3
VENV := .venv
BIN := $(VENV)/bin

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS=":.*?## "} {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(VENV):
	$(PY) -m venv $(VENV)

.PHONY: setup
setup: $(VENV) ## Create venv and install CPU deps + package
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/pip install -r requirements-cpu.txt
	$(BIN)/pip install -e ".[dev]"
	@echo "Setup complete. Copy .env.example to .env and edit config/config.yaml."

.PHONY: dry-run
dry-run: ## Full pipeline, save artifacts, post nothing
	$(BIN)/python -m autogram.run --dry-run

.PHONY: image-only
image-only: ## Generate + gate image only (no caption, no post)
	$(BIN)/python -m autogram.run --image-only

.PHONY: run
run: ## Full pipeline and publish (needs real credentials)
	$(BIN)/python -m autogram.run

.PHONY: test
test: ## Run unit tests (no network)
	$(BIN)/pytest

.PHONY: lint
lint: ## ruff + mypy
	$(BIN)/ruff check autogram tests
	$(BIN)/ruff format --check autogram tests
	$(BIN)/mypy

.PHONY: fmt
fmt: ## Auto-format with ruff
	$(BIN)/ruff format autogram tests
	$(BIN)/ruff check --fix autogram tests

.PHONY: clean
clean: ## Remove caches and generated artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache out
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
