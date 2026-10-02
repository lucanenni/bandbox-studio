# Security

BandBox Studio controls a nearby physical amplifier. The supported configuration is a trusted local Mac, a local stdio MCP client, and a browser connected to `127.0.0.1`.

The GUI binds only to loopback. Its API checks Host and Origin, requires a per-process request token for actions, limits request sizes, and exposes a fixed set of controls. The native helper also restricts accepted requests. These controls do not make it suitable for public hosting or access by untrusted local software. Do not expose the server through a public tunnel or change its binding to a network interface.

The software does not request a JBL account or cloud API key. Device discovery identifiers, local operation logs, and generated MCP configuration stay on the Mac and are excluded from the repository. Before sharing diagnostics, remove device identifiers, addresses, local paths, usernames, and any private preset names.

Firmware updates, factory resets, arbitrary raw commands, preset deletion, and loop discard are outside the exposed interface. Uncertain writes are not retried automatically. Saving a user preset intentionally replaces that preset's saved settings.

## Reporting a vulnerability

Use the repository's **Security → Report a vulnerability** option when available. Please report authentication/origin bypasses, unintended writes, unsafe request validation, and sensitive-data exposure privately. If private reporting is unavailable, open an issue asking for a private contact without including exploit details or private logs.

Include the commit, macOS/Python versions, relevant component, a minimal reproduction, and expected versus actual behavior. Use a simulated device for reproductions when possible. Do not publish real device identifiers or credentials.

The current development branch is the supported version. This is an experimental project; no response-time or maintenance guarantee is offered.
