# BLE sniffing setup — iPhone + Mac

Method: **live USB capture** with PacketLogger. The Bluetooth diagnostic
profile is **required** even for live USB capture — without it, iOS's
Bluetooth stack doesn't emit the HCI log at all, and PacketLogger captures
zero packets even though it can see the phone. Download it on the Mac and
AirDrop it over (downloading it directly from Safari on the iPhone is less
reliable).

## 1. Install PacketLogger on the Mac (once)

1. https://developer.apple.com/download/all/ (needs a free Apple ID) →
   search for **"Additional Tools for Xcode"** (the version matching your
   Xcode/macOS).
2. Download the `.dmg`, open it → `Hardware/PacketLogger.app` → move it to
   Applications.

## 2. Install the Bluetooth diagnostic profile on the iPhone (once)

1. On the **Mac**, Safari → https://developer.apple.com/bug-reporting/profiles-and-logs/?name=bluetooth
   → download the **iOS** Bluetooth profile (not the macOS variant).
2. AirDrop the `.mobileconfig` file from the Mac to the iPhone.
3. On the iPhone, install the profile (Settings → "Profile Downloaded"
   banner at the top, or General → VPN & Device Management).
4. **Disconnect the USB cable if connected**, then reboot the iPhone
   (required — the profile isn't active until you reboot with the cable
   unplugged).
5. Once rebooted, reconnect the iPhone to the Mac via USB, unlock, "Trust
   This Computer".

## 3. Capture a session

Important: **one isolated action per capture**, noting the exact time —
otherwise working out which packet corresponds to which function becomes
nearly impossible. Use `re/captures/CAPTURE_LOG_TEMPLATE.md` to log actions.

1. Open **PacketLogger.app** → **File → New iOS Trace** → select the iPhone
   (it's not enough for it to show up in the device list: the trace has to
   be started from here).
2. Open the **JBL One** app on the phone, connect to the BandBox Trio.
3. Note the time (with seconds).
4. Perform **a single action** in the app (e.g. "change from preset A to
   preset B").
5. Right after the action, note: time + exact description in the log.
6. Repeat for every function of interest (preset change, looper start,
   looper stop, looper undo, volume, tone/EQ change, tap tempo, etc.), one
   action at a time.
7. Stop the capture in PacketLogger.

## 4. Decode on the Mac

1. In PacketLogger: File → Export → **btsnoop** (or a compatible format) →
   save to `re/captures/<action-name>.btsnoop` (e.g.
   `re/captures/preset_a_to_b.btsnoop`).
2. Decode with the ready-made script:

```bash
python3 re/probes/parse_btsnoop.py re/captures/preset_a_to_b.btsnoop
```

The script only keeps ATT packets (L2CAP channel 0x0004) and prints
timestamp, direction, GATT operation type and payload in hex — look for
**Write Request/Command** frames (commands sent from the app to the amp)
and **Notification** frames (status/responses sent from the amp to the app)
around the time noted in the log.

## If it still captures nothing

- Check that you installed the **iOS** profile, not the macOS one (Apple's
  page lists them separately — file names like `Bluetooth.mobileconfig` for
  iOS vs. `Bluetooth_macOS.mobileconfig`).
- Confirm the reboot happened **after** installing the profile and **with
  the cable unplugged**.
- Check that you used **File → New iOS Trace** in PacketLogger, not just
  selecting the device.
- Fallback independent of the phone: a BLE sniffer dongle (nRF52840 + nRF
  Sniffer for Bluetooth LE + Wireshark), capturing over the air.
