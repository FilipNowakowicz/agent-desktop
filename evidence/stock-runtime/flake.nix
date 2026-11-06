{
  description = "Desktop runtime for agent-desktop: STOCK labwc/wlroots (no repair), control arm for the 2026-11 wlroots measurement, and session tools";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/4975466d324710c576dc11ad614684e6bd8cad8e";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      runtime = pkgs:
        let
          labwc = pkgs.labwc;
        in
        pkgs.buildEnv {
          name = "agent-desktop-runtime";
          paths = with pkgs; [
            labwc grim dbus xwayland
            # Optional: viewer and takeover, clipboard, accessibility, test terminal.
            wayvnc tigervnc wl-clipboard at-spi2-core foot
          ];
          pathsToLink = [ "/bin" "/libexec" ];
        };
    in
    {
      packages = forAll (pkgs: { default = runtime pkgs; });
    };
}
