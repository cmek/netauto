.PHONY: install test clean demo lint

# Default target
all: test

# Install dependencies using uv
install:
	uv sync

# Run all tests
test:
	uv run pytest -v

# Run tests with coverage
coverage:
	uv run pytest --cov=src/netauto --cov-report=term-missing

# Clean up temporary files
clean:
	rm -rf .pytest_cache
	rm -rf .coverage
	rm -rf dist
	find . -type d -name "__pycache__" -exec rm -rf {} +

# Run the EVPN demo script
demo:
	uv run python examples/demo_evpn.py

# Run the live device demo
demo-live:
	uv run python examples/demo_real_devices.py

# Placeholder for linting (e.g., ruff or pylint)
lint:
	@echo "Linting not yet configured. Suggest adding ruff."
