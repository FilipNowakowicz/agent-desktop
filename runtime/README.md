# Project-local Xwayland mapping repair

Supported installation paths (Nix runtime with this repair, Ubuntu 24.04) are in
`runtime/INSTALL.md`.

Stock labwc 0.20.2 / wlroots 0.20.2 and Fedora labwc 0.9.6 / wlroots 0.19.3 intermittently leave X11 windows unmapped
in the private headless desktop. Native Wayland tasks are unaffected by this
observed failure. Do not interpret earlier passing repetitions as a repair.

The retained protocol trace shows an Xwayland surface committing its buffer
before X11 association. In [wlroots 0.20.2](https://gitlab.freedesktop.org/wlroots/wlroots/-/blob/0.20.2/xwayland/xwm.c),
the commit listener is attached during association; only later commits trigger
mapping. The patch checks the existing buffer after notifying association
listeners, so the compositor can attach its map listener first. It uses the
same surface-role mapping function as the existing commit handler. This is a
local repair, not an upstream release or a universal X11 reliability claim.

For Arch with wlroots0.20 0.20.2 development files and labwc 0.20.2, or
Fedora with wlroots0.19-devel 0.19.3 and labwc 0.9.6:

```sh
# Build dependencies, in addition to the normal desktop runtime:
# Arch: base-devel meson ninja curl patchelf glslang vulkan-headers hwdata
# Fedora: wlroots0.19-devel gcc gcc-c++ meson ninja-build curl-minimal
#         patchelf patch glslang glslang-devel wayland-protocols-devel hwdata-devel
#         xorg-x11-server-Xwayland-devel
sh scripts/build_xwayland_runtime.sh artifacts/patched-runtime
PATH="$PWD/artifacts/patched-runtime/install/bin:$PATH" uv run agent-desktop create
```

The output directory must be new. The script downloads the pinned upstream
0.19.3 or 0.20.2 archive selected by the labwc library ABI, verifies its SHA-256, applies the patch and builds wlroots. It
copies the current labwc binary and changes only that copy's library search
path. No global libraries, profiles, loader settings or host compositor are
changed. Keep the output directory while using its runtime; deleting it removes
the repair. Choose this runtime explicitly on `PATH`, with `create --labwc`, with
`AGENT_DESKTOP_LABWC`, or through `core.create`'s `tools` argument. Python
dependencies and the core remain portable.

Arch CI 37214448862 passed its full suite, 100 loaded Xterm sessions and
lifecycle stress using this private repair. Both matching private repairs passed CI 37215643286: full suites, 100 loaded
Xterm repetitions per distribution, and lifecycle stress. Ubuntu continues
using its stock runtime packages. The patched local runtime passed 150 loaded Xterm sessions (one logged repair),
100 loaded sessions with an already-running XWM, and the full 33-test suite
with visible mode skipped. Other build environments, versions and visible-mode behavior
of the repair require separate validation. On NixOS the same patch was tested
using project-local `labwc.override { wlroots_0_20 = patchedWlroots; }`, with
`patchedWlroots` adding this patch via `overrideAttrs`; no host activation.
The shell build recipe targets conventional distribution development packages,
not Nix store libraries.
