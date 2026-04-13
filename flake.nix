{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };
  outputs = { self, nixpkgs }:
  let
    system = "x86_64-linux";
    pkgs = import nixpkgs { inherit system; };

    # Define simhash as a custom package
    simhash = pkgs.python3Packages.buildPythonPackage rec {
      pname = "simhash";
      version = "2.1.2"; # Check PyPI for the latest version if needed
      
      format = "setuptools";
      
      src = pkgs.fetchPypi {
        inherit pname version;
        # Nix will tell you the correct hash on the first run if this is empty
        hash = "sha256-UzvIz0Hk5t2D8LGEc2NRa/MyPg+pLmPZ5t9OKB6ILhs="; 
      };

      # Simhash usually has few dependencies, but add them if the build fails
      propagatedBuildInputs = with pkgs.python3Packages; [
        # Add dependencies here if the build complains (e.g., setuptools)
      ];
    };
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

        pip
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
        simhash
      ] ++ [
        pkgs.starship
        pkgs.asciinema
      ];

      shellHook = ''
        
        export SHELL=${ pkgs.lib.getExe pkgs.bash }
        eval "$(starship init bash)"
        export STARSHIP_CONFIG=$PWD/starship.toml
        echo "Welcome to the devShell!"
      '';
    };
  };
}
