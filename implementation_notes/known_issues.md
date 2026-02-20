# Known Issues

## GTK warning when scrolling console dropdowns

- **Status:** Open / deferred
- **Observed on:** Settings > ROMs > Scan ROMs (console select dropdown), when scrolling with mouse wheel.
- **Warning:**
  - `Gtk-CRITICAL **: gtk_widget_compute_point: assertion 'GTK_IS_WIDGET (widget)' failed`

### Reproduction

1. Open `Settings`.
2. Go to `ROMs`.
3. Click `Scan ROMs` to open the dialog.
4. Open the console dropdown and scroll with mouse wheel.
5. Warning appears in app logs.

### Context

- Started after custom dropdown item rendering with icon + label.
- Debug click logger was simplified (`pick()` removed), but warning persisted.
- Icon rendering in console widgets was switched from `Gtk.Picture` to `Gtk.Image`; warning still persisted.

### Next investigation

- Isolate whether warning comes from `Gtk.DropDown` popup + custom factory during wheel scrolling.
- Test fallback rendering mode for dropdown list:
  - plain text in popup list (keep icon only in selected item), or
  - remove custom list factory only for affected dialogs.
- If GTK bug is confirmed, keep workaround and document GTK version constraints.
