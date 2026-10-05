{
  description = "Desktop runtime for agent-desktop: labwc with the repaired wlroots, and session tools";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/4975466d324710c576dc11ad614684e6bd8cad8e";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      patch = ../patches/wlroots-map-at-associate.patch;
      runtime = pkgs:
        let
          wlroots = pkgs.wlroots_0_20.overrideAttrs (old: {
            patches = (old.patches or [ ]) ++ [ patch ];
            # Lets `agent-desktop doctor` recognise the repaired library.
            postInstall = (old.postInstall or "") + ''
              printf 'wlroots %s with %s (nix)\n' ${old.version} \
                "$(sha256sum < ${patch} | cut -d' ' -f1)" \
                > $out/lib/agent-desktop-xwayland-repair
            '';
          });
          labwc = pkgs.labwc.override { wlroots_0_20 = wlroots; };
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
