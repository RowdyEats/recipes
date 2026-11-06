.PHONY: generate test build
generate:
	SITE_BASE_URL=https://rowdyeats.github.io/recipes python3 scripts/generate_content.py
test: generate
	python3 -m unittest discover -s tests -v
build: generate
	hugo build --gc --baseURL https://rowdyeats.github.io/recipes/
