#!/bin/bash
echo "Starting container setup..."

install_packages() {
  local packages=(
    "curl"
    "python3"
    "python3-pip"
    "build-essential"
    "git"
  )
  export DEBIAN_FRONTEND=noninteractive
  export TZ=Europe/London
  apt-get update
  apt-get upgrade -y
  apt-get install -y "${packages[@]}"
  curl -fsSL https://claude.ai/install.sh | bash
  touch /root/.bashrc
  echo "PATH=PATH:/root/.local/bin/claude" >>/root/.bashrc
  source /root/.bashrc
}

install_packages

echo "Setup complete!"
