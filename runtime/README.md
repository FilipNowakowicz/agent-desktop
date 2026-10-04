# Project-local Xwayland mapping repair

Stock labwc 0.20.2 / wlroots 0.20.2 intermittently leaves X11 windows unmapped
in the private headless desktop. Native Wayland tasks are unaffected by this
observed failure. Do not interpret earlier passing repetitions as a repair.

The retained protocol trace shows an Xwayland surface committing its buffer
before X11 association. In [wlroots 0.20.2](https://gitlab.freedesktop.org/wlroots/wlroots/-/blob/0.20.2/xwayland/xwm.c),
the commit listener is attached during association; only later commits trigger
mapping. The patch checks the existing buffer after notifying association
listeners, so the compositor can attach its map listener first. It uses the
same surface-role mapping function as the existing commit handler. This is a
local repair, not an upstream release or a universal X11 reliability claim.

For Arch with wlroots0.20 0.20.2 development files and labwc 0.20.2:

```sh
# Build dependencies, in addition to the normal desktop runtime:
# base-devel meson ninja curl patchelf glslang vulkan-headers hwdata
sh scripts/build_xwayland_runtime.sh artifacts/patched-runtime
PATH="$PWD/artifacts/patched-runtime/install/bin:$PATH" uv run agent-desktop create
```

The output directory must be new. The script downloads the pinned upstream
0.20.2 archive, verifies its SHA-256, applies the patch and builds wlroots. It
copies the current labwc binary and changes only that copy's library search
path. No global libraries, profiles, loader settings or host compositor are
changed. Keep the output directory while using its runtime; deleting it removes
the repair. Choose this runtime explicitly on `PATH` or through `core.create`'s
`tools` argument. Python dependencies and the core remain portable.

Arch CI tests this private repair. Ubuntu/Fedora continue using their stock
runtime packages. Other build environments, versions and visible-mode behavior
of the repair require separate validation. On NixOS the same patch was tested
using project-local `labwc.override { wlroots_0_20 = patchedWlroots; }`, with
`patchedWlroots` adding this patch via `overrideAttrs`; no host activation.
The shell build recipe targets conventional distribution development packages,
not Nix store libraries.
