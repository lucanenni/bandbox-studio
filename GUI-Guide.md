# Using BandBox Studio

After [setup](README.md#setup), open **BandBox Studio.app** or run:

```sh
.venv/bin/python gui_launch.py
```

The launcher opens [the local panel](http://127.0.0.1:8765). It starts the server on demand. Closing the browser leaves that server available for reopening; nothing is added to your login items.

## Read and load a sound

1. Power on your BandBox Trio and keep it near the Mac.
2. Press **Read the amp** at the upper right. This reads the preset library and selected sound without changing settings.
3. Choose a preset in the library.
4. Press **Load saved sound** to play its saved settings and enable editing.

Loading a preset replaces the current unsaved sound. The panel asks before clearing its known changes or unapplied drafts. It cannot see every unsaved change made with JBL One or the amp's physical controls.

The library numbers follow the amp's inventory order. These displayed numbers can differ from internal preset IDs returned by MCP tools. New presets receive their number from the amp.

## Shape and save a sound

1. Select **GAT**, **COM**, **WAH**, **AMP**, **CAB**, **MOD**, **DLY**, or **RVB** in **Tone studio**.
2. Adjust a parameter and press its **Apply** button. Moving a slider alone changes only a draft on the page.
3. To change the model, choose one and press **Apply model**. The **Active / Bypassed** switch takes effect immediately.
4. Press **Save changes** to keep applied edits in the loaded user preset. Saving replaces that user preset's previous saved sound.

For a factory preset, use **••• → Save as a new preset** to keep your applied edits as a separate sound. Factory presets cannot be overwritten here.

**Create a preset** and **Create a copy** copy the source preset's *saved* settings, then load the new copy. **Save as a new preset** copies the current applied sound. Unapplied slider or model drafts are never included in a save. Use **Rename preset** to rename a user preset.

## Mixer and practice tools

In **Mixer**, press **Read level**, adjust a level, then **Apply**. Mixer values are raw steps from **0 to 32**. They are separate from the AMP block's **Volume** parameter.

In **Practice tools**, select drums, metronome, tuner, or looper. Press **Read** for the setting, choose a value, then **Apply**. Tuner controls configure the tuner; use the amp's display for tuning measurements.

**Start new recording** requires an empty, stopped looper with drums and metronome off. **Stop recording** keeps the recording. Bar changes require an empty loop and a running backing preview. Existing-loop overdubbing and loop deletion are not exposed. Recording controls are implemented but have not been independently exercised on hardware; see [validation status](README.md#validation-status).

## Switching between the GUI, MCP, and JBL One

The GUI and MCP coordinate their local edit state through a shared runtime directory. A write from one invalidates the other's old preview. Restart both after updating the software so they run the same version.

While editing, leave JBL One and the amp's tone controls unchanged. If you use either, read the amp again and load the desired saved sound before continuing. Saved-detail reads cannot reconstruct all unsaved knob changes. Preserve any sound you want to keep on the amp before reloading.

An uncertain response disables further edits and is never automatically retried. Check the amp's display before deciding what to do next.

## Connection problems

- Keep the amp on and nearby. If it cannot be found, press its **Bluetooth** button once, wait for the blue light to pulse, then press **Read the amp**.
- Allow Bluetooth access when macOS asks. If access was denied, check **System Settings → Privacy & Security → Bluetooth** for the app or terminal you used.
- If JBL One is open, close it and try another read. A timeout alone does not establish that the phone caused it.
- If another app occupies port 8765, the launcher reports that instead of stopping the other app.
- The local page requires its Mac server to be running. It is not a hosted website and cannot control an amp from a different computer.
