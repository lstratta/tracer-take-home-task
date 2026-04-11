{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };
  outputs = { self, nixpkgs }:
  let
    system = "x86_64-linux";
    pkgs = import nixpkgs { inherit system; };
  in
  {

    devShells.${system}.default = pkgs.mkShell {
      buildInputs = with pkgs.python3Packages; [
        langgraph
        langchain
        langchain-core
        langchain-community
        langchain-anthropic
        langgraph-checkpoint

        ddgs
        beautifulsoup4
        requests
        python-dotenv
        pydantic
        typing-extensions
        python-lsp-server
        python-lsp-ruff
        pyyaml
        python-slugify
        click
        structlog
        tenacity
        python-dateutil
        tqdm
        pytest
      ] ++ [
        pkgs.starship
        streamlit
      ];

      shellHook = ''
        pip install simhash
        export SHELL=${ pkgs.lib.getExe pkgs.bash }
        eval "$(starship init bash)"
        export STARSHIP_CONFIG=$PWD/starship.toml
        echo "Welcome to the devShell!"
      '';
    };
  };
}
