# OpenEmux 1.7.0

Four features that move the same choices out of config files and into the interface: which shader a game runs, which core runs it, how each console's shelf is laid out, and how the library is grouped. Every one of them still has a sensible default, so an untouched install looks and behaves exactly as it did — the new controls are there when you want to diverge, and invisible when you don't.

## A shader per game

Shaders have been per console for a while — a CRT mask for the 16-bit machines, an LCD look for the handhelds — which is the right granularity most of the time. It is the wrong one for the odd game that renders at a different resolution than the rest of its console, or the FMV-heavy title that wants no shader at all.

Right-click a game and there is now a **Shader** submenu:

- The same list Preferences offers for that console, honouring the **Show all shaders** switch.
- **Use console setting (…)** is the default and shows, in parentheses, what it currently resolves to — so you know what you are changing away from.
- **Disabled** is a distinct choice: "no shader for this one game" is exactly what this is for.

The choice is remembered, follows a rename, and is dropped when you delete the game. Changing a console's shader in Preferences never disturbs a game that carries its own.

## A core per console, and per game

Until now the only way to influence which libretro core ran a game was to hand-edit `config.yaml`. Both levels are in the interface now.

**Per console** — a new **Cores** page in Preferences, one row per console, listing the cores you actually have installed plus an **Automatic** entry at the top. Automatic is the default and stores nothing; the row's subtitle tells you which core it resolves to, and a console with no core installed says so rather than offering an empty list. The picker reads each core's `.info` file, so you pick *Snes9x*, not `snes9x_libretro.so`.

**Per game** — a **Core** submenu on the ROM context menu, listing only the cores that can run that system. **Automatic** clears the override and returns the game to the console decision.

Choose a core that needs a BIOS you do not have and OpenEmux warns you. A per-game override whose core is later uninstalled quietly falls back to the console — or automatic — choice instead of failing the launch.

## A layout per console, per view

View mode, sort order and zoom were one global setting for the whole library. But the right presentation differs by console: cartridges for the systems whose shelf art is good, covers for the ones where it is poor or missing; a large zoom for a short Favorites page, a tight one for a 400-game console.

They are now a **global default that any page can override**. The header layout menu names the page you are on — *Layout for: SFC* — and a **Use the global layout** toggle switches between following the global default and giving that page its own. Following global, the controls change the global default, so it can still be set from anywhere; overridden, they change only that page. No control in the menu is ever a switch that appears to do nothing.

The sidebar's console context menu gained a **Layout ▸** shortcut with the same options, the fast route when setting several consoles in a row.

Existing configurations keep exactly the layout they have today — every page follows global until you deliberately break consistency.

## Custom collections

The sidebar could group games two ways: **All**, and one row per console. Favorites was the only grouping you defined, and it was a single unnamed bucket.

Now you can make as many named collections as you like — **Fighting** spanning SNES, Mega Drive and PlayStation; **Racing**; **To finish**; **Kids** — each mixing consoles the way All does.

- Create one from the **New collection** button at the bottom of the sidebar, or by right-clicking empty sidebar space.
- **Add to collection** on a game's context menu lists every collection, with **New collection…** to create one and add the game in a single step. It works on a whole multi-game selection at once, and shows a check for collections a game is already in.
- **Remove from this collection** while viewing one — this never touches the file on disk, unlike Delete.
- Rename and delete a collection from its own sidebar menu; deleting asks first and makes clear the games themselves survive.

Collections persist across restarts, follow renamed or moved games, drop deleted ones, and are reachable by keyboard and gamepad like everything else in the sidebar.

## Upgrading

Nothing to do. Every new setting defaults to the behaviour you already had: shaders and cores stay on **Automatic** / the console setting, every page follows the **global** layout, and you have no collections until you make one.
