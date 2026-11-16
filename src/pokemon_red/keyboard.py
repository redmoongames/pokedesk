"""Layout-independent key identities for the bundled macOS Tk 9 runtime.

Tk Aqua packs the native virtual keycode into bits 24..31 of event.keycode;
bits 0..21 contain layout-dependent Unicode and bits 22..23 Shift/Option.
Read only the physical byte, and keep familiar US key names in settings.json.

References: Tk core-9-0-4/macosx/tkMacOSXPrivate.h (keycode_v), and Apple's
HIToolbox/Events.h virtual keycodes. No global keyboard hook is required.
"""

COMMAND_MASK = 1 << 3  # Tk Aqua maps NSEventModifierFlagCommand to Mod1Mask.

MAC_KEYS = {
    0x00: "a", 0x01: "s", 0x02: "d", 0x03: "f", 0x04: "h", 0x05: "g",
    0x06: "z", 0x07: "x", 0x08: "c", 0x09: "v", 0x0A: "section", 0x0B: "b",
    0x0C: "q", 0x0D: "w", 0x0E: "e", 0x0F: "r", 0x10: "y", 0x11: "t",
    0x12: "1", 0x13: "2", 0x14: "3", 0x15: "4", 0x16: "6", 0x17: "5",
    0x18: "equal", 0x19: "9", 0x1A: "7", 0x1B: "minus", 0x1C: "8", 0x1D: "0",
    0x1E: "bracketright", 0x1F: "o", 0x20: "u", 0x21: "bracketleft", 0x22: "i",
    0x23: "p", 0x24: "Return", 0x25: "l", 0x26: "j", 0x27: "apostrophe",
    0x28: "k", 0x29: "semicolon", 0x2A: "backslash", 0x2B: "comma", 0x2C: "slash",
    0x2D: "n", 0x2E: "m", 0x2F: "period", 0x30: "Tab", 0x31: "space",
    0x32: "grave", 0x33: "BackSpace", 0x35: "Escape", 0x36: "Super_R",
    0x37: "Super_L", 0x38: "Shift_L", 0x39: "Caps_Lock", 0x3A: "Alt_L",
    0x3B: "Control_L", 0x3C: "Shift_R", 0x3D: "Alt_R", 0x3E: "Control_R",
    0x3F: "Fn", 0x40: "F17", 0x41: "KP_Decimal", 0x43: "KP_Multiply",
    0x45: "KP_Add", 0x47: "Clear", 0x48: "XF86AudioRaiseVolume",
    0x49: "XF86AudioLowerVolume", 0x4A: "XF86AudioMute", 0x4B: "KP_Divide",
    0x4C: "KP_Enter", 0x4E: "KP_Subtract", 0x4F: "F18", 0x50: "F19",
    0x51: "KP_Equal", 0x52: "KP_0", 0x53: "KP_1", 0x54: "KP_2", 0x55: "KP_3",
    0x56: "KP_4", 0x57: "KP_5", 0x58: "KP_6", 0x59: "KP_7", 0x5A: "F20",
    0x5B: "KP_8", 0x5C: "KP_9", 0x5D: "yen", 0x5E: "underscore", 0x5F: "KP_Separator",
    0x60: "F5", 0x61: "F6", 0x62: "F7", 0x63: "F3", 0x64: "F8", 0x65: "F9",
    0x66: "Eisu_toggle", 0x67: "F11", 0x68: "Hiragana_Katakana", 0x69: "F13",
    0x6A: "F16", 0x6B: "F14", 0x6D: "F10", 0x6E: "Menu", 0x6F: "F12",
    0x71: "F15", 0x72: "Help", 0x73: "Home", 0x74: "Prior", 0x75: "Delete",
    0x76: "F4", 0x77: "End", 0x78: "F2", 0x79: "Next", 0x7A: "F1",
    0x7B: "Left", 0x7C: "Right", 0x7D: "Down", 0x7E: "Up",
}


def event_key(event) -> str | None:
    """Stable across layouts, Shift/Caps Lock and press/release character changes.

    IME/text-only synthetic events have no physical key and must not move the
    player. The native runtime is macOS-only; other Tk keycode formats differ.
    """
    virtual = (int(event.keycode) >> 24) & 0xFF
    if virtual >= 128:
        return None
    return MAC_KEYS.get(virtual, f"MacKey_{virtual:02X}")
