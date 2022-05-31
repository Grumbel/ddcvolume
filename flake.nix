{
  description = "ddcvolume - Monitor Volume Control Over DDC";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-22.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in rec {
        packages = flake-utils.lib.flattenTree rec {
          ddcvolume = pkgs.python3Packages.buildPythonPackage rec {
            name = "ddcvolume";
            src = ./.;
            postPatch = ''
                substituteInPlace ddcvolume/cmd_ddcvolume.py \
                   --replace "default='ddcutil'" \
                             "default='${pkgs.ddcutil}/bin/ddcutil'"
            '';
            buildInputs = [
              pkgs.ddcutil
            ];
            propagatedBuildInputs = [
              pkgs.python3Packages.pyxdg
              pkgs.python3Packages.dbus-python
            ];
          };
        };
        defaultPackage = packages.ddcvolume;
      });
}
