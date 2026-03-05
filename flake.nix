{
  description = "polymarket-bot - paper trading bot for Polymarket prediction markets";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python313;
        pythonPkgs = python.pkgs;
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = [
            (python.withPackages (ps: with ps; [
              requests
              textual
              pytest
              pytest-cov
              pytest-asyncio
            ]))
          ];

          shellHook = ''
            echo "polymarket-bot dev shell ready"
            echo "Python: $(python --version)"
            export PYTHONPATH="$PWD/src:$PYTHONPATH"

            mkdir -p .dev-bin
            cat > .dev-bin/polymarket-bot <<SCRIPT
            #!/usr/bin/env python
            from polymarket_bot.runner import main
            main()
            SCRIPT
            chmod +x .dev-bin/polymarket-bot
            export PATH="$PWD/.dev-bin:$PATH"
          '';
        };
      }
    );
}
