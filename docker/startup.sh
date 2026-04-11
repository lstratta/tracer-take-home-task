#!/bin/bash
echo "Starting container setup..."
apt update
apt upgrade -y
apt install -y curl
curl -fsSL https://claude.ai/install.sh | bash
touch /root/.bashrc
echo "PATH=PATH:/root/.local/bin/claude" >>/root/.bashrc
source /root/.bashrc
echo "Setup complete!"
