run:
	@python main.py run

test:
	@pytest tests/

ubuntu-start:
	@podman compose -f docker/ubuntu-compose.yml up -d

ubuntu-exec:
	@podman exec -it dev-environment /bin/bash
