# OpenEmux 1.3.1

A small release about the context menus: one bug that made the console menu nearly unusable, and two changes so the menus are easier to find in the first place.

## The sidebar menu stayed open only while you held the button

Right-clicking a console in the sidebar opened its menu and closed it again in the same gesture. The menu was only visible while the right button was held down, so reaching an entry meant holding and dragging onto it.

The popover was being shown on the gesture's *press*, which left the matching *release* — the second half of the very same click — to close it. It now opens on release, and claims the click so the row does not react to it as well.

## Icons in the context menus

Every entry in the ROM and console menus now carries an icon: a star for favorite, a refresh arrow for rescan, a folder for opening the folder, a trash can for removing a cover, and so on.

This needed the menus to be rebuilt by hand. GTK4 accepts an icon on a `Gio.MenuItem` and then never draws it — menus built from a menu model are text-only by design — so the rows are now assembled directly as buttons holding an icon and a label.

## A button for the menus

Right-clicking is not an obvious thing to try, and the actions behind those menus were effectively hidden from anyone who did not think to try it.

- **ROM covers** show a three-dot button in the top-right corner on hover.
- **Sidebar consoles** show the same button at the end of the row on hover.

Both open the same menu that right-click opens.

## The favorite star moved

The star marking a favorite game sat in the top-right corner of the cover, which is now where the menu button goes. The star moved to the **top-left** corner.

## Not changed

"All" and "Favorites" no longer have a context menu at all. They are views rather than folders on disk, so the entries either did not apply or acted on the whole library under a label suggesting otherwise.
