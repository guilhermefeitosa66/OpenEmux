# OpenEmux Share Protocol v1

The wire protocol of **Share nearby**: how two OpenEmux devices on the same
local network find each other, open a secure session, agree on a verification
code and offer games to each other. It is the single reference for every
implementation; the desktop one lives in `src/openemux/core/share/`, the
Android one in the `open-emux-mobile` repository. Nothing here requires reading
either.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are to be read as in
RFC 2119.

## Contents

1. [Overview and roles](#1-overview-and-roles)
2. [Versioning](#2-versioning)
3. [Identity](#3-identity)
4. [mDNS / DNS-SD](#4-mdns--dns-sd)
5. [UDP beacon](#5-udp-beacon)
6. [The peer list](#6-the-peer-list)
7. [TLS](#7-tls)
8. [Endpoints](#8-endpoints)
9. [Verification code](#9-verification-code)
10. [Manifest schema](#10-manifest-schema)
11. [Errors](#11-errors)
12. [Privacy and security notes](#12-privacy-and-security-notes)
13. [Constants](#13-constants)

## 1. Overview and roles

- The **receiver** runs an HTTPS server. The **sender** is its client.
- A device is discoverable, and its server listens, **only while its share
  screen is open** (plus a short grace period the application chooses). A
  device that is not sharing sends nothing and listens on nothing.
- A transfer goes: discover → `GET /info` → `POST /offer` (with a commitment)
  → `POST /offer/<id>/reveal` → both screens show the same six-digit code →
  the receiver's user accepts or declines → the sender polls the answer →
  `PUT /file/...` for every accepted item.
- All payloads are JSON (UTF-8), except file bodies.

## 2. Versioning

- The protocol version is an integer. This document is version **1**.
- Every device advertises `v`, the highest version it speaks, and `vmin`, the
  lowest. Two devices are **compatible** when the ranges overlap; they then use
  the highest version both speak.
- Every request and every response MUST carry the header
  `OpenEmux-Share-Version: <n>`, the version the request is written in.
- A server that receives a request (other than `GET /info`) with the header
  missing, not a decimal integer, or a version it does not speak MUST answer
  `400` with error `incompatible_version` and these extra fields:

  ```json
  {"error": "incompatible_version", "message": "version 1 vs 2",
   "supported": {"min": 1, "max": 1}, "peer": {"min": 2, "max": 2}}
  ```

  `peer` is `null`-valued (`{"min": null, "max": null}`) when the header was
  missing or unreadable.
- `GET /info` MUST be answered whatever the version header says, so a client
  can always tell the user "version X vs Y".
- A device discovered with an unknown or unreadable version MUST still be
  listed, flagged incompatible. It MUST NOT be silently dropped.

## 3. Identity

Each device has, generated once and kept until the user resets the app's data:

| Field | Format |
| --- | --- |
| `id` | 32 lowercase hex characters (128 random bits). |
| `name` | UTF-8, at most 64 characters, user-editable. Defaults to the host name (desktop) or the device model (Android). |
| `pf` (platform) | `desktop`, `phone` or `tablet`. A receiver MUST show any other value as `desktop`. |
| certificate | X.509 v3, self-signed. ECDSA P-256 with SHA-256 is RECOMMENDED; any key TLS 1.3 accepts is valid. Subject and issuer CN `OpenEmux Share <id>`. Validity 20 years. |
| `fp` (fingerprint) | Lowercase hex of the SHA-256 of the **DER** certificate: 64 characters. Shown to users in groups of four (`ab12 cd34 …`). |

On receipt, a `name` MUST have its control characters (Unicode categories Cc and
Cf) removed, be trimmed, and be cut to 64 characters. An empty result is shown
as the first six characters of the `id`.

The private key MUST be stored readable by the app only (desktop: mode `0600`
in a `0700` directory). If the stored identity is unreadable or inconsistent
(the certificate's CN names another id, or the key does not match the
certificate), the device generates a new id, key and certificate together.

## 4. mDNS / DNS-SD

- Service type: `_openemux._tcp.local.`
- Instance name: `<name> (<first 6 characters of id>)`, cut to 63 bytes of UTF-8
  (without splitting a character).
- Port: the SRV record carries the port the HTTPS server actually listens on.
- TXT record keys (all values are strings):

  | Key | Value |
  | --- | --- |
  | `id` | device id |
  | `name` | device name |
  | `pf` | platform |
  | `v` | highest protocol version, decimal |
  | `vmin` | lowest protocol version, decimal |
  | `fp` | certificate fingerprint |

- Unknown TXT keys MUST be ignored.
- A record without a valid `id` (32 hex) or `fp` (64 hex) MUST be ignored.
- A record whose `v` is missing or not a number is listed with version 0
  (incompatible). If `vmin` is missing, or greater than `v`, it is taken as `v`.
- A device MUST ignore records carrying its own `id`.
- A peer found by mDNS is removed when its service is removed.

## 5. UDP beacon

mDNS is blocked or unreliable on many networks and phones, so every device
also runs a plain multicast beacon, in parallel.

- Group `239.255.77.77`, UDP port `53318`, multicast TTL **1** (never routed
  beyond the local network).
- While discoverable, a device sends a `hello` every **2 seconds** on each of
  its IPv4 interfaces, and a `bye` when it stops.
- Payload: one UTF-8 JSON object, at most **1024 bytes**:

  ```json
  {"p": "openemux-share", "t": "hello", "id": "…", "name": "Den PC",
   "pf": "desktop", "v": 1, "vmin": 1, "port": 53319, "fp": "…"}
  ```

  `t` is `hello` or `bye`; `port` is the HTTPS server's port; `v`/`vmin` are
  numbers.
- The peer's address is the datagram's **source address**, never a field of
  the payload.
- A datagram MUST be dropped silently when it is over 1024 bytes, not JSON, not
  an object, has `p` other than `openemux-share`, `t` other than
  `hello`/`bye`, or lacks a valid `id`, `fp` or `port` (1–65535). Unknown keys
  MUST be ignored. Version handling is the same as in mDNS.
- A peer seen only by the beacon expires **7 seconds** after its last `hello`.
  A `bye` removes it at once.
- The beacon is IPv4 only in v1.
- **Android:** hold a `WifiManager.MulticastLock` while listening, or multicast
  datagrams are filtered out.

## 6. The peer list

- Peers are keyed by the pair **(`id`, `fp`)**. A device seen by mDNS and by
  the beacon is one entry; a beacon reusing a known `id` with a different
  certificate is a **second** entry, never a replacement of the first.
- Each entry carries: the paths that found it (any of `mdns`, `beacon`,
  `manual`), its addresses (IPv4 first, then IPv6), port, version range and a
  compatible flag.
- Each path lives and dies on its own (§4, §5; a `manual` entry stays until the
  user removes it). An entry disappears when its last path is gone.
- **Manual address and QR code.** When discovery cannot see a device, the user
  types its address or scans its QR code:

  ```
  openemux-share://<host>:<port>#<fp>
  ```

  `host` is an IPv4 address, a host name, or an IPv6 literal in brackets
  (`[fe80::1]`). The scheme, the port (default `53319`) and the fingerprint are
  optional when typed: `192.168.0.5`, `192.168.0.5:53319` and
  `[fe80::1]:53319` are all valid. A fingerprint, when present, is 64 hex
  characters; spaces and colons in it are ignored and it is case-insensitive.
  The QR code always carries all three parts. The client fetches `GET /info`
  from the address to fill in the entry.

## 7. TLS

- **TLS 1.3 only.** Servers and clients MUST refuse anything older.
- The server presents its self-signed certificate. There is **no CA and no host
  name check**: the client **pins** the fingerprint instead. Right after the
  handshake, before sending a single byte of HTTP, the client computes the
  SHA-256 of the DER certificate it was shown and compares it, in constant
  time, with the `fp` it expects. On mismatch it MUST close the connection and
  report `fingerprint_mismatch`.
- A manual address without a fingerprint is accepted on first contact
  (trust on first use): the client uses the fingerprint it observes, and the
  verification code (§9) is what protects that contact.
- There is no client certificate. The sender's fingerprint travels in the
  offer body and is bound into the verification code, so a forged one changes
  the code.
- Timeouts: 10 s to connect and complete the handshake, 30 s idle.
- Clients MAY open one connection per request.

## 8. Endpoints

HTTP/1.1 over the TLS session. Request and response bodies are JSON with
`Content-Type: application/json` unless stated. Request bodies MUST NOT exceed
**1 MiB** (`413 too_large`), except `PUT /file`. Unknown fields MUST be ignored
everywhere. Any other path answers `404 not_found`.

### `GET /info`

No body. Always answered (§2).

```json
{"id": "…", "name": "Den PC", "pf": "desktop", "v": 1, "vmin": 1}
```

### `POST /offer`

```json
{"sender": {"id": "…", "name": "Phone", "pf": "phone", "fp": "…"},
 "commit": "<64 hex>",
 "manifest": { … §10 … }}
```

- `sender.fp` is the sender's own certificate fingerprint; `commit` is defined
  in §9.
- The receiver holds **one pending incoming offer** at a time: while one is
  waiting (posted or revealed, and not yet answered or expired), another gets
  `409 busy`.
- A malformed body or manifest gets `400 bad_request`.
- Answer `201`:

  ```json
  {"offer_id": "<22 chars>", "nonce_r": "<64 hex>", "expires_in": 60}
  ```

  `offer_id` is 128 random bits in URL-safe base64 without padding. It is a
  **capability**: only the sender learns it, inside TLS, and every later
  request about the offer is authorized by knowing it.
- The offer **expires 60 seconds** after it was posted unless answered.

### `POST /offer/<offer_id>/reveal`

```json
{"nonce_s": "<64 hex>"}
```

- `404 not_found` for an unknown offer, `410 expired` for an expired one,
  `400 bad_request` if it was already revealed or `nonce_s` is not 64 hex.
- If `commit` does not match `nonce_s` (§9) the receiver answers
  `403 bad_commit` and **discards the offer**.
- Otherwise the receiver computes the code and only now shows the offer to its
  user, with the code. Answer `200 {"code": "123456"}`. The field is for
  debugging: each side MUST compute and show its own code, never the other's.

### `GET /offer/<offer_id>`

The sender polls this every second until the status is final.

```json
{"status": "accepted",
 "items": [{"id": "i1", "action": "send"},
           {"id": "i2", "action": "skip", "reason": "exists_skip"}]}
```

- `status` is one of `pending`, `accepted`, `declined`, `expired`,
  `cancelled`. Only `pending` is not final.
- `items` is present only when `accepted`: one entry per manifest item the
  receiver answered, with `action` `send` or `skip` and, for `skip`, a
  `reason`: `incompatible_state`, `exists_skip`, `unsupported_console`,
  `user_unchecked` or `invalid_item` (an item the receiver will not write: an
  unknown kind, a name it refuses, a suffix the console does not load). An
  item missing from the list is not to be sent. Senders MUST accept reasons
  they do not know and treat them as a skip.
- A finished offer is kept for at least 5 minutes so the last poll can read
  it; afterwards `404 not_found`.

### `PUT /file/<offer_id>/<item_id>`

- Body: the raw bytes of the file (`Content-Type: application/octet-stream`).
  `Content-Length` MUST equal the item's `size` in the manifest.
- Allowed only for items the receiver answered with `action: send`, each once.
  Otherwise `400 bad_request`.
- `410 cancelled`, `410 declined` or `410 expired` when the offer is in that
  state. A receiver that cancels while an upload is in progress also closes
  that connection.
- Success: `204`, no body.
- When the item carries a `sha256` and the body does not match it, or the body
  is shorter than `Content-Length`, the receiver answers `400 bad_request`
  and **aborts the whole offer**: everything received so far is discarded and
  the offer becomes `cancelled`.
- A receiver whose disk fills up while writing answers `507 no_space` and
  aborts the offer the same way.
- A receiver MAY stage the files it receives (write each one under a
  temporary name) and make them all appear only when the last one has
  arrived, so a cancelled or broken transfer leaves nothing behind. The
  desktop app does; the sender cannot tell the difference.
- Writing, verifying and placing the files is specified with the manifest
  (§10); a build that cannot receive files yet answers `501 not_implemented`.

### `POST /cancel/<offer_id>`

No body. Either the sender cancels (any state), answered `204`, or
`404 not_found` for an unknown offer. A cancel by the **receiver's** user is
learned by the sender as `status: cancelled` on its next poll, or
`410 cancelled` on its next `PUT /file`.

## 9. Verification code

Both screens show a six-digit code; the users compare them before the receiver
accepts. It is built so that a man in the middle on the LAN cannot choose its
values until the two codes collide.

- `nonce_s` (sender) and `nonce_r` (receiver): 32 random bytes each, sent as
  64 lowercase hex characters. They enter both hashes below as their **32 raw
  bytes** (decoded from hex), never as the hex text.
- `commit = hex(SHA-256("openemux-share-v1/commit" ‖ nonce_s))`, where the
  label is its ASCII bytes and `‖` is concatenation.
- `digest = SHA-256("openemux-share-v1/code" ‖ fp_sender ‖ fp_receiver ‖ nonce_s ‖ nonce_r)`,
  with each fingerprint as its **32 raw bytes** (not hex).
- `code = (first 8 bytes of digest as a big-endian unsigned 64-bit integer) mod 1 000 000`,
  zero-padded to six digits, shown as two groups: `093 444`.
- The **sender** uses as `fp_receiver` the fingerprint it observed in TLS. The
  **receiver** uses its own fingerprint, and as `fp_sender` the `sender.fp` of
  the offer.

**Why commit-reveal.** If the code were built only from the two fingerprints
and a value the receiver picks, an attacker relaying the session could try
receiver values offline until its two forged sessions gave the same code. Here
the sender is bound to `nonce_s` (through `commit`) before it learns `nonce_r`,
and the receiver picks `nonce_r` before it learns `nonce_s`. An attacker in the
middle must commit to its values on each side before seeing the other side's,
so it gets exactly one blind guess per offer: a 1-in-1 000 000 chance.

**Test vectors.** Implementations MUST reproduce these. All four are in
`tests/data/share_vectors.json`, which both apps' tests read.

| | Vector "simple" | Vector "hashed" |
| --- | --- | --- |
| `fp_sender` | `00` × 32 | `fa4651aaaa97d42e7025a83d02c8972daa23594476058bd9a945a6114e4f424c` |
| `fp_receiver` | `ff` × 32 | `3a8053a4b308d46f987514cd0a8b815564a332613ae233096eb8bc45bde816ff` |
| `nonce_s` | `11` × 32 | `69cf40308468a862a39603c13b4b3986f5668e839c2573c00fabe22bd7e4e850` |
| `nonce_r` | `22` × 32 | `8d32b8eec0d5fa7c5eccd23fcccf2256f096769e923870286c9cfe0e671eaf14` |
| `commit` | `e231904286b3293a3c8609b59297c24518d292c9a285fcb9f5f3ad892da475b6` | `8f404d2baa1389a52e1f7ddec7da235ba6a19572ca7531e735b5c9fd02040d74` |
| `code` | `435613` | `286433` |

The file also has a vector whose code starts with `0` (`093444`, to check the
padding) and the "hashed" vector with the fingerprints swapped (`163722`, to
check their order).

## 10. Manifest schema

The manifest describes everything an offer would send. This section defines
it in full; what the receiver does with it (placement, conflicts, writing)
builds on these rules.

```json
{
  "games": [
    {
      "id": "g1",
      "console": "SFC",
      "title": "Super Example",
      "metadata": {"favorite": true, "cartridge_color": "black",
                   "core": "snes9x", "shader": "crt-easymode", "playtime_seconds": 5400},
      "items": [
        {"id": "i1", "kind": "rom", "name": "Super Example (USA).sfc",
         "size": 1048576, "mtime": 1700000000, "sha256": "…"},
        {"id": "i2", "kind": "battery_save", "name": "Super Example (USA).srm",
         "size": 8192, "mtime": 1700000500},
        {"id": "i3", "kind": "state", "name": "Super Example (USA).state1",
         "size": 300000, "mtime": 1700000600,
         "state": {"core": "snes9x", "core_version": "1.62.3", "slot": 1}}
      ]
    }
  ],
  "total_size": 1356768,
  "file_count": 3
}
```

**Manifest:** `games` (array, required), `total_size` and `file_count`
(non-negative integers, required).

**Game:**

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string, required | Unique within the manifest. |
| `console` | string, required | The canonical console id, from the table below. |
| `title` | string, required | Display only. |
| `items` | array, required | The game's files. |
| `metadata` | object, optional | `favorite` (bool), `cartridge_color` (string), `core` (string), `shader` (string), `playtime_seconds` (integer). Every key optional. |

**Item:**

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string, required | Unique within the manifest; used in `/file`. |
| `kind` | string, required | `rom`, `battery_save`, `state`, `cover` or `label`. An unknown kind MUST be answered `skip`. |
| `name` | string, required | A **bare file name**, at most 255 bytes of UTF-8. |
| `size` | integer, required | Bytes, non-negative. |
| `mtime` | number, required | Unix seconds. |
| `sha256` | string, optional | Hex SHA-256 of the content; when present the receiver MUST verify it. |
| `part` | object, optional | Groups the files of a multi-file unit: `{"unit": "<string>", "role": "cue" \| "bin" \| "m3u" \| "disc" \| "main"}`. |
| `state` | object, optional | For `kind: state`: `{"core", "core_version", "slot"}`, `slot` being `"auto"` or 0–9. |

**Limits and rules.**

- At most **2000 items** in a manifest. More is `400 bad_request`.
- `name` is **never a path**. The receiver MUST reject (`400 bad_request`) a
  name that is empty, `.` or `..`, or contains `/`, `\`, `..` or NUL, and MUST
  compute every destination path itself; the name is used for display and as a
  suffix only. Beyond that, a receiver answers `skip` / `invalid_item` for an
  item it will not write -- the desktop app does so for a name starting with
  `.`, a `rom` whose suffix the console does not load (a unit's `bin` and
  `disc` parts excepted), a `battery_save` whose name does not start with the
  unit's main stem and a dot, and a `cover` or `label` that is not a PNG, JPEG
  or WebP.
- Unknown fields MUST be ignored.
- `tests/data/share_vectors.json` holds a `manifest_sample` (one multi-file
  game, a battery save, a state and a cover) that both apps' tests parse.

**Console ids:**

| Id | Console | Id | Console |
| --- | --- | --- | --- |
| `A2600` | Atari 2600 | `MCD` | Sega CD / Mega CD |
| `A5200` | Atari 5200 | `MD` | Sega Genesis / Mega Drive |
| `A7800` | Atari 7800 | `SMS` | Sega Master System |
| `LYNX` | Atari Lynx | `SATURN` | Sega Saturn |
| `CV` | ColecoVision | `PS` | Sony PlayStation |
| `FDS` | Famicom Disk System | `PSP` | Sony PSP |
| `FC` | Nintendo (NES) / Famicom | `SFC` | Super Nintendo (SNES) |
| `GB` | Game Boy | `PCE` | TurboGrafx-16 / PC Engine / SuperGrafx |
| `GBC` | Game Boy Color | `PCECD` | TurboGrafx-CD / PC Engine CD |
| `GBA` | Game Boy Advance | `VECTREX` | Vectrex |
| `GG` | Game Gear | `VB` | Virtual Boy |
| `INTV` | Intellivision | `WS` | WonderSwan |
| `NGP` | NeoGeo Pocket | `SG1000` | SG-1000 |
| `N64` | Nintendo 64 | `S32X` | Sega 32X |
| `NDS` | Nintendo DS | `O2` | Odyssey2 / Videopac+ |
| `GC` | Nintendo GameCube | | |

A receiver that does not support a console answers its items
`skip` / `unsupported_console`.

## 11. Errors

Every error answer has this body (extra fields per error, as in §2):

```json
{"error": "<code>", "message": "<English, for logs only>"}
```

| Code | HTTP | When |
| --- | --- | --- |
| `bad_request` | 400 | Malformed body, manifest, nonce or state transition. |
| `incompatible_version` | 400 | Version header missing or unsupported (§2). |
| `bad_commit` | 403 | `nonce_s` does not match `commit`. |
| `not_found` | 404 | Unknown path or offer. |
| `busy` | 409 | Another incoming offer is pending. |
| `expired` | 410 | The offer expired. |
| `cancelled` | 410 | The offer was cancelled. |
| `declined` | 410 | The offer was declined. |
| `too_large` | 413 | Request body over 1 MiB. |
| `no_space` | 507 | The receiver's disk filled up during `PUT /file`; the offer is aborted. |
| `not_implemented` | 501 | The endpoint is not available in this build. |
| `internal` | 500 | Anything else. |

Clients also report these locally (they never cross the wire):
`fingerprint_mismatch` (§7), `unreachable` (connection or TLS failure) and
`unavailable` (the feature cannot run on this install). Applications translate
codes into messages; `message` is never shown to users.

## 12. Privacy and security notes

- The beacon and the TXT record carry only the identity of §3: no library
  data. Game titles and file names travel only inside TLS, and only to a
  device the user chose.
- Every size limit is checked **before** parsing: 1024 bytes for a beacon,
  1 MiB for a request body.
- Comparisons of fingerprints and commitments are constant-time.
- Known limits:
  - Networks with **client/AP isolation** (common on guest Wi-Fi) block both
    discovery and the session. The manual address does not help there.
  - A **firewall** on the receiver must allow TCP on the advertised port and
    UDP 53318 (plus mDNS, UDP 5353).
  - A device **name is self-declared**: anyone on the network can call itself
    "Living room PC". The verification code, not the name, is what proves who
    is on the other end.
  - TLS hides content, not the fact that two devices are talking.

## 13. Constants

| Name | Value |
| --- | --- |
| Protocol version (`v` / `vmin`) | 1 / 1 |
| Version header | `OpenEmux-Share-Version` |
| mDNS service type | `_openemux._tcp.local.` |
| Beacon group / port / TTL | `239.255.77.77` / `53318` / 1 |
| Beacon interval / peer expiry | 2 s / 7 s |
| Beacon size limit | 1024 bytes |
| HTTPS port | `53319` preferred; any free port if taken, always the one advertised |
| Request body limit | 1 MiB |
| Offer lifetime | 60 s |
| TLS | 1.3 only; 10 s connect/handshake, 30 s idle |
| Manifest limits | 2000 items, names ≤ 255 bytes |
| Name limit | 64 characters |
| URI scheme | `openemux-share://` |
