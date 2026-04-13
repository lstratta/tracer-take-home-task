.PHONY: run stats enrich-all enrich-10 test install help ubuntu-start ubuntu-exec

COUNT ?= 10  # Default value if not provided

run:
	@python main.py run

stats:
	@python main.py stats

enrich: 
	@python main.py enrich --count $(COUNT)

enrich-all: 
	@python main.py enrich --all

test:
	@pytest tests/

install:
	@pip install -r requirements.txt

help:
	@python main.py --help

ubuntu-start:
	@podman compose -f docker/ubuntu-compose.yml up -d

ubuntu-exec:
	@podman exec -it dev-environment /bin/bash
