PokéDesk icon

Legacy portable-app icon source:
  tools/design/build_brand_icon.swift — standalone AppKit raster builder

The current public Mac builder generates its own pixel P icon in
  tools/build_macos.py
No external SVG or private artwork pack is needed to build either icon.

Generate PNG sizes with the macOS SDK:
  swift tools/design/build_brand_icon.swift /tmp/pokedesk-icon-png

The builder emits 16, 32, 64, 128, 256, 512, 1024 px PNGs. Assemble a standard .iconset
with icon_16x16.png through icon_512x512@2x.png and run iconutil -c icns. The installed
bundle uses Pokemon.app/Contents/Resources/PokeDesk.icns; CFBundleIconFile is PokeDesk.icns.
After updating bundle resources, re-sign with codesign --force --sign - Pokemon.app.
No compiler or icon-generation dependencies are required at application runtime.
