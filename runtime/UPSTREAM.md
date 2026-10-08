# Upstream proposal for the wlroots mapping repair

Status: prepared, not submitted. The maintainer has a freedesktop GitLab account
(2026-10-08, signed in with Google), but a fork attempt was refused ("Limit
reached. You cannot create projects in your personal namespace"): new accounts
must first request fork permission, as the sign-in page says. After that, fork
`wlroots/wlroots`, replace `xwayland/xwm.c` on a branch with the patched file (or
push the commit) and open the merge request below. Not a release gate. `runtime/patches/wlroots-map-at-associate.patch` applies to wlroots
master `c5c57cd3` (2026-09-26) with a 110-line offset, and to 0.19.3 and 0.20.2.

Retire the local patch once a packaged wlroots release contains an equivalent
fix. Check each new wlroots release's `xwayland_surface_associate`.

## Proposed merge request

**Title:** xwayland/xwm: map a surface whose buffer was committed before association

**Description:**

`xwayland_surface_associate()` attaches the surface commit listener, and the map
check in `xwayland_surface_handle_commit()` runs only on later commits. When
Xwayland commits the surface's buffer before the WM receives `WL_SURFACE_SERIAL`
/ `WL_SURFACE_ID` for that window, no later commit arrives for a static window,
and the surface is never mapped. The compositor shows nothing, and no
foreign-toplevel handle is created.

Seen with labwc on headless wlroots 0.20.2 and 0.19.3 under CPU load. A
`WAYLAND_DEBUG=server` trace shows the `wl_surface.commit` with an attached
buffer before association. With four busy CPU processes, a plain xterm
failed to map roughly once every 30–60 sessions. After associating, this change
maps the surface if it already has a buffer. It emits the associate signal first,
so compositors can attach their map listeners. With the change, 150 of 150
loaded sessions mapped, one of them via the new path, and CI repetitions
passed (100 per distribution on Arch with 0.20.2 and Fedora with 0.19.3).

```diff
 	wl_signal_emit_mutable(&xsurface->events.associate, NULL);
+
+	/* The Wayland buffer may arrive before the X11 association. */
+	if (wlr_surface_has_buffer(surface)) {
+		wlr_log(WLR_DEBUG, "Mapping buffered Xwayland surface at association");
+		wlr_surface_map(surface);
+	}
 }
```

Reviewers may prefer to factor this together with the existing check in
`xwayland_surface_handle_commit()`, which applies the same condition.
