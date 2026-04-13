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
  sudo apt-get update
  sudo apt-get upgrade -y
  sudo apt-get install -y "${packages[@]}"
  curl -fsSL https://claude.ai/install.sh | bash
  if [ ! -f "~/.bashrc" ]; then
    touch ~/.bashrc
  fi
  echo "PATH=PATH:/root/.local/bin/claude" >>~/.bashrc
  source /root/.bashrc
}

setup_python_packages() {
  python3-pip install -r requirements.txt
}

install_packages
setup_python_packages

echo "Setup complete!"
