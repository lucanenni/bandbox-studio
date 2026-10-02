#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ "$(uname -s)" != Darwin ]; then
  echo "The Bluetooth helper requires macOS and Xcode Command Line Tools." >&2
  exit 1
fi
mkdir -p bin .build
cat DriveRoundTrip.swift ControlRequest.swift BandBoxProbe.swift > .build/CombinedProbe.swift
xcrun swiftc .build/CombinedProbe.swift -o .build/bandbox-probe \
  -framework CoreBluetooth -framework IOBluetooth \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker Info.plist
codesign --force --sign - .build/bandbox-probe
mv .build/bandbox-probe bin/bandbox-probe
