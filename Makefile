ubuntu-start:
	@podman compose -f docker/ubuntu-compose.yml up -d

ubuntu-exec:
	@podman exec -it dev-environment /bin/bash
