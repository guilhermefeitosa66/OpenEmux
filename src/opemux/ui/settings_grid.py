import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango


class SettingsCard(Gtk.Box):
    def __init__(self, title, subtitle, icon_path=None, icon_name=None, on_click=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("settings-card")

        button = Gtk.Button()
        button.add_css_class("flat")
        button.add_css_class("settings-card-button")
        if on_click:
            button.connect("clicked", lambda _: on_click())

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        if icon_path:
            icon = Gtk.Picture.new_for_filename(icon_path)
            icon.set_size_request(48, 48)
            icon.add_css_class("settings-card-icon")
            content.append(icon)
        else:
            icon = Gtk.Image.new_from_icon_name(icon_name or "applications-system-symbolic")
            icon.set_pixel_size(32)
            icon.add_css_class("settings-card-icon")
            content.append(icon)

        title_label = Gtk.Label(label=title)
        title_label.set_halign(Gtk.Align.START)
        title_label.add_css_class("settings-card-title")
        content.append(title_label)

        if subtitle:
            subtitle_label = Gtk.Label(label=subtitle)
            subtitle_label.set_halign(Gtk.Align.START)
            subtitle_label.set_max_width_chars(32)
            subtitle_label.set_wrap(True)
            subtitle_label.set_ellipsize(Pango.EllipsizeMode.END)
            subtitle_label.add_css_class("dim-label")
            content.append(subtitle_label)

        button.set_child(content)
        self.append(button)


class SettingsGrid(Gtk.FlowBox):
    def __init__(self):
        super().__init__()
        self.set_valign(Gtk.Align.START)
        self.set_max_children_per_line(5)
        self.set_min_children_per_line(2)
        self.set_row_spacing(24)
        self.set_column_spacing(24)
        self.set_selection_mode(Gtk.SelectionMode.NONE)
        self.set_margin_top(28)
        self.set_margin_bottom(28)
        self.set_margin_start(28)
        self.set_margin_end(28)
        self.set_homogeneous(True)

    def add_card(self, title, subtitle, icon_path=None, icon_name=None, on_click=None):
        self.append(
            SettingsCard(
                title=title,
                subtitle=subtitle,
                icon_path=icon_path,
                icon_name=icon_name,
                on_click=on_click,
            )
        )
