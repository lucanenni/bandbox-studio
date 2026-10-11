#!/usr/bin/env python3
"""Decode ATT/GATT frames from a btsnoop capture, via tshark.

Apple's PacketLogger btsnoop export uses the "unencapsulated HCI" datalink
type (no H4 transport byte, packet type inferred from the record flags
field) — hand-rolling that parser produced garbage (wrong CIDs, no ATT
frames found). tshark decodes it correctly out of the box, so we shell out
to it instead of re-implementing btsnoop/HCI/L2CAP/ATT framing.

By default, (opcode, value) pairs that repeat more than --noise-threshold
times in the whole capture are collapsed to one summary line — the BandBox
Trio sends a constant write/notify keepalive at rest, which otherwise floods
the output. This means you don't need to time a button press precisely:
capture continuously, do ONE action anywhere in the middle, and whatever
isn't collapsed is almost certainly that action. Use --all to disable this.

Usage:
    python3 parse_btsnoop.py <capture.btsnoop> [--handle 0xHANDLE] [--all]
                              [--noise-threshold N]

Requires Wireshark installed (looks for tshark in the usual macOS app
bundle path, falls back to $PATH).
"""
import collections
import os
import shutil
import subprocess
import sys

TSHARK_CANDIDATES = [
    "/Applications/Wireshark.app/Contents/MacOS/tshark",
    shutil.which("tshark"),
]

FIELDS = ["frame.number", "frame.time_relative", "btatt.opcode", "btatt.handle", "btatt.value"]


def find_tshark():
    for candidate in TSHARK_CANDIDATES:
        if candidate and os.path.exists(candidate):
            return candidate
    sys.exit("tshark not found — install Wireshark (provides tshark) from wireshark.org")


def run_tshark(tshark, capture_path):
    cmd = [tshark, "-r", capture_path, "-Y", "btatt", "-T", "fields"]
    for f in FIELDS:
        cmd += ["-e", f]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"tshark failed:\n{proc.stderr}")

    rows = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        while len(parts) < len(FIELDS):
            parts.append("")
        frame_no, ts, opcode, handle, value = parts[:5]
        rows.append((frame_no, float(ts), opcode, handle, value))
    return rows


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)

    handle_filter = None
    if "--handle" in args:
        i = args.index("--handle")
        handle_filter = args[i + 1].lower()
        if not handle_filter.startswith("0x"):
            handle_filter = f"0x{int(handle_filter, 0):04x}"
        del args[i:i + 2]

    show_all = "--all" in args
    if show_all:
        args.remove("--all")

    noise_threshold = 3
    if "--noise-threshold" in args:
        i = args.index("--noise-threshold")
        noise_threshold = int(args[i + 1])
        del args[i:i + 2]

    capture_path = args[0]
    tshark = find_tshark()
    rows = run_tshark(tshark, capture_path)

    if handle_filter:
        rows = [r for r in rows if r[3].lower() == handle_filter]

    # (opcode, value) frequency across the whole capture — repeats are keepalive/ack noise
    freq = collections.Counter((r[2], r[4]) for r in rows)

    printed = 0
    suppressed_summary = collections.Counter()

    for frame_no, ts, opcode, handle, value in rows:
        key = (opcode, value)
        is_noise = freq[key] > noise_threshold
        # a Write Response (0x13) with empty value is a pure ack, always noise
        is_bare_ack = opcode == "0x13" and value == ""

        if not show_all and (is_noise or is_bare_ack):
            suppressed_summary[key if not is_bare_ack else ("0x13", "<ack>")] += 1
            continue

        printed += 1
        print(f"[{frame_no:>5s}] t={ts:9.3f}s  opcode={opcode or '-':6s}  "
              f"handle={handle or '-':8s}  value={value}")

    if not show_all and suppressed_summary:
        print(f"\n--- suppressed {sum(suppressed_summary.values())} noisy/repeated frames "
              f"(--all to show everything) ---")
        for (opcode, value), n in suppressed_summary.most_common():
            shown = value if len(value) <= 40 else value[:40] + "..."
            print(f"  {n:4d}x  opcode={opcode:6s}  value={shown}")

    if printed == 0 and not suppressed_summary:
        print("no matching ATT frames — check the capture has a BandBox Trio "
              "session, or the --handle filter.", file=sys.stderr)


if __name__ == "__main__":
    main()
