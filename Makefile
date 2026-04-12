run:
	@python main.py run

stats:
	@python main.py stats

enrich-all: 
	@python main.py enrich

enrich-10:
	@python main.py enrich --count 10

test:
	@pytest tests/

ubuntu-start:
	@podman compose -f docker/ubuntu-compose.yml up -d

ubuntu-exec:
	@podman exec -it dev-environment /bin/bash
