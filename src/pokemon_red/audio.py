"""Native AudioQueue output and an App Nap activity for the running game."""
import ctypes
import audioop


class Playback:
    def __init__(self, library):
        self.lib = library
        self.handle = self.activity = None
        self.rate = None
        self.input_rate = None
        self.resampler = None
        self.failed_rate = None
        self.error = None
        pointer = ctypes.c_void_p
        for name, args, result in (
            ("output_open", [ctypes.c_uint], pointer),
            ("output_close", [pointer], None),
            ("output_push", [pointer, pointer, ctypes.c_uint], None),
            ("output_volume", [pointer, ctypes.c_float], None),
            ("output_played", [pointer], ctypes.c_uint64),
            ("activity_begin", [], pointer), ("activity_end", [pointer], None),
        ):
            function = getattr(library, "pokemon_" + name)
            function.argtypes, function.restype = args, result

    def configure(self, *, active, rate, speed, enabled, volume, prevent_app_nap=True):
        if active and prevent_app_nap and not self.activity:
            self.activity = self.lib.pokemon_activity_begin()
        elif (not active or not prevent_app_nap) and self.activity:
            self.lib.pokemon_activity_end(self.activity)
            self.activity = None
        # Audio APIs require integer sample rates, including fractional pacing.
        source = max(1,round(min(speed,2147483647/max(1,rate))*rate)) if active and enabled and volume else None
        target = 48000 if source else None
        if self.rate != target:
            self.stop_audio()
            self.rate = target
            self.input_rate = source
            self.resampler = None
            self.failed_rate = None
            self.error = None
        if self.input_rate != source:
            # Keep the output device alive across pacing changes. Only the
            # software resampler changes its ratio, never the AudioQueue.
            self.input_rate = source
            self.resampler = None
        if target and not self.handle and target != self.failed_rate:
            self.handle = self.lib.pokemon_output_open(target)
            self.failed_rate = target if not self.handle else None
            self.error = "Не удалось открыть звуковой выход macOS" if not self.handle else None
        if self.handle:
            self.lib.pokemon_output_volume(self.handle, volume / 100)

    def write(self, pcm: bytes):
        if self.handle and pcm:
            if self.input_rate != self.rate:
                pcm, self.resampler = audioop.ratecv(pcm, 2, 2, self.input_rate, self.rate, self.resampler)
            buffer = ctypes.create_string_buffer(pcm)
            self.lib.pokemon_output_push(self.handle, buffer, len(pcm) // 4)

    @property
    def played_frames(self):
        return self.lib.pokemon_output_played(self.handle) if self.handle else 0

    def stop_audio(self):
        if self.handle:
            self.lib.pokemon_output_close(self.handle)
            self.handle = None

    def close(self):
        self.stop_audio()
        self.rate = self.failed_rate = None
        self.input_rate = self.resampler = None
        if self.activity:
            self.lib.pokemon_activity_end(self.activity)
            self.activity = None
