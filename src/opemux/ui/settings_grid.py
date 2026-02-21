import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango, GdkPixbuf

CARD_WIDTH = 200
CARD_HEIGHT = 200
ICON_SECTION_HEIGHT = int(CARD_HEIGHT * 0.8)   # 80%
TEXT_SECTION_HEIGHT = CARD_HEIGHT - ICON_SECTION_HEIGHT  # 20%

MAIN_CARD_WIDTH = 220
MAIN_CARD_HEIGHT = 220
MAIN_ICON_SECTION_HEIGHT = int(MAIN_CARD_HEIGHT * 0.8)
MAIN_TEXT_SECTION_HEIGHT = MAIN_CARD_HEIGHT - MAIN_ICON_SECTION_HEIGHT


class SettingsCard(Gtk.Button):
    def __init__(self, title, subtitle, icon_path=None, icon_name=None, on_click=None, layout_variant="default"):
        super().__init__()
        self.layout_variant = layout_variant
        is_main = self.layout_variant == "settings_main"
        card_width = MAIN_CARD_WIDTH if is_main else CARD_WIDTH
        card_height = MAIN_CARD_HEIGHT if is_main else CARD_HEIGHT
        icon_section_height = MAIN_ICON_SECTION_HEIGHT if is_main else ICON_SECTION_HEIGHT
        text_section_height = MAIN_TEXT_SECTION_HEIGHT if is_main else TEXT_SECTION_HEIGHT
        icon_size = 108 if is_main else 96

        # The button IS the card — fixed size, no expansion
        self.add_css_class("flat")
        self.add_css_class("settings-card")
        if is_main:
            self.add_css_class("settings-card-main")
        self.set_size_request(card_width, card_height)
        self.set_hexpand(False)
        self.set_vexpand(False)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        if on_click:
            self.connect("clicked", lambda _: on_click())

        # Root vertical box: fills the button
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.set_halign(Gtk.Align.FILL)
        content.set_valign(Gtk.Align.FILL)
        content.set_hexpand(True)
        content.set_vexpand(True)

        # Icon section — fixed height, icon centered inside
        icon_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        icon_section.set_size_request(card_width, icon_section_height)
        icon_section.set_hexpand(True)
        icon_section.set_vexpand(False)
        icon_section.set_halign(Gtk.Align.FILL)
        icon_section.set_valign(Gtk.Align.FILL)
        if is_main:
            icon_section.add_css_class("settings-card-main-icon-box")

        # Text section — fixed height, labels centered inside
        text_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text_section.set_size_request(card_width, text_section_height)
        text_section.set_hexpand(True)
        text_section.set_vexpand(False)
        text_section.set_halign(Gtk.Align.FILL)
        text_section.set_valign(Gtk.Align.FILL)
        if is_main:
            text_section.add_css_class("settings-card-main-text-box")

        # Icon widget — centered in icon_section via halign/valign
        icon_widget = None
        if icon_path:
            icon = Gtk.Picture()
            icon.set_size_request(icon_size, icon_size)
            icon.set_content_fit(Gtk.ContentFit.CONTAIN)
            icon.set_can_shrink(True)
            icon.set_halign(Gtk.Align.CENTER)
            icon.set_valign(Gtk.Align.CENTER)
            icon.set_hexpand(False)
            icon.set_vexpand(False)
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_path, icon_size, icon_size, True)
                icon.set_pixbuf(pixbuf)
                icon_widget = icon
            except Exception:
                icon_widget = None
        if icon_widget is None:
            icon = Gtk.Image.new_from_icon_name(icon_name or "applications-system-symbolic")
            icon.set_pixel_size(icon_size)
            icon.set_size_request(icon_size, icon_size)
            icon.set_halign(Gtk.Align.CENTER)
            icon.set_valign(Gtk.Align.CENTER)
            icon.set_hexpand(False)
            icon.set_vexpand(False)
            icon_widget = icon

        icon_widget.add_css_class("settings-card-icon")
        icon_section.append(icon_widget)

        # Labels container — centered vertically and horizontally in text_section
        text_center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_center.set_halign(Gtk.Align.CENTER)
        text_center.set_valign(Gtk.Align.CENTER)
        text_center.set_hexpand(True)
        text_center.set_vexpand(True)

        title_label = Gtk.Label(label=title)
        title_label.set_halign(Gtk.Align.CENTER)
        title_label.set_justify(Gtk.Justification.CENTER)
        title_label.set_xalign(0.5)
        title_label.add_css_class("settings-card-title")
        title_label.set_tooltip_text(title)
        if is_main:
            title_label.add_css_class("settings-card-main-title")
            title_label.set_lines(1)
            title_label.set_wrap(False)
            title_label.set_max_width_chars(22)
            title_label.set_ellipsize(Pango.EllipsizeMode.END)
        text_center.append(title_label)

        subtitle_label = Gtk.Label(label=subtitle or "")
        subtitle_label.set_halign(Gtk.Align.CENTER)
        subtitle_label.set_justify(Gtk.Justification.CENTER)
        subtitle_label.set_xalign(0.5)
        subtitle_label.set_max_width_chars(24)
        subtitle_label.set_wrap(False)
        subtitle_label.set_lines(1)
        subtitle_label.set_ellipsize(Pango.EllipsizeMode.END)
        subtitle_label.add_css_class("dim-label")
        if subtitle:
            subtitle_label.set_tooltip_text(subtitle)
        if is_main:
            subtitle_label.add_css_class("settings-card-main-subtitle")
        text_center.append(subtitle_label)

        tooltip = title if not subtitle else f"{title}\n{subtitle}"
        self.set_tooltip_text(tooltip)

        text_section.append(text_center)
        content.append(icon_section)
        content.append(text_section)
        self.set_child(content)


class SettingsGrid(Gtk.FlowBox):
    def __init__(self, layout_variant="default"):
        super().__init__()
        self.layout_variant = layout_variant
        self.set_valign(Gtk.Align.START)
        self.set_halign(Gtk.Align.FILL)
        self.set_hexpand(True)
        self.set_vexpand(False)
        self.set_max_children_per_line(100)
        self.set_min_children_per_line(1)
        self.set_row_spacing(24)
        self.set_column_spacing(24)
        self.set_selection_mode(Gtk.SelectionMode.NONE)
        self.set_margin_top(28)
        self.set_margin_bottom(28)
        self.set_margin_start(28)
        self.set_margin_end(28)
        self.set_homogeneous(True)

    def add_card(self, title, subtitle, icon_path=None, icon_name=None, on_click=None):
        is_main = self.layout_variant == "settings_main"
        card_width = MAIN_CARD_WIDTH if is_main else CARD_WIDTH
        card_height = MAIN_CARD_HEIGHT if is_main else CARD_HEIGHT
        card = SettingsCard(
            title=title,
            subtitle=subtitle,
            icon_path=icon_path,
            icon_name=icon_name,
            on_click=on_click,
            layout_variant=self.layout_variant,
        )
        self.append(card)
        flow_child = self.get_last_child()
        if flow_child is not None:
            flow_child.set_size_request(card_width, card_height)
            flow_child.set_hexpand(False)
            flow_child.set_vexpand(False)
