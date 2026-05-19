.PHONY: build deploy

build:
	uv run modal run src/sandbox_image.py

deploy: build
	uv run modal deploy src/claude_webhook_handler.py
