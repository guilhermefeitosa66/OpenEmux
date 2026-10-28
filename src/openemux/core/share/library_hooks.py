"""The library side of a received transfer, over the real managers (#589).

``receive.IncomingTransfer`` reaches favorites and the per-game overrides only
through a :class:`receive.LibraryHooks`; this is the one the app passes in.
"""

from openemux.core.share.receive import LibraryHooks


class ManagerLibraryHooks(LibraryHooks):
    def __init__(self, playlists, config):
        self.playlists = playlists
        self.config = config

    def set_favorite(self, rom_path):
        # Adds only: a game the receiver already has and did not favorite
        # gains the star, and one it favorited keeps it.
        if not self.playlists.is_favorite(rom_path):
            self.playlists.toggle_favorite({"path": str(rom_path)})

    def set_cartridge_color(self, rom_path, console, color_id):
        self.config.set_rom_cartridge_color(str(rom_path), console, color_id)

    def set_core(self, rom_path, core_filename):
        self.config.set_rom_core(str(rom_path), core_filename)

    def set_shader(self, rom_path, console, shader_id):
        self.config.set_rom_shader(str(rom_path), console, shader_id)
