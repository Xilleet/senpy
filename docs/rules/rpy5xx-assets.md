---
title: RPY5xx — Assets & Media Rules
description: RPY5xx rules cover Ren'Py assets and media — missing audio files (RPY501), unresolved sprites/transforms (RPY502), unused media assets (RPY503), duplicate image declarations (RPY504), and unregistered audio channels (RPY505).
tags:
  - rules
  - assets
  - audio
  - rpy5xx
---

# RPY5xx — Assets & Media Rules

The RPY5xx family covers **asset references and media files** —
audio files, image sprites, transforms, and audio channel
registrations. These rules catch the "the game launches but crashes
the moment a sprite appears or a song starts" class of bug.

Senpy scans the project's `game/` directory, `.rpa` archives, and
`image` / `define audio.X` declarations to build a complete asset
inventory. Rules check that every reference in your scripts points
to a real asset on disk or in an archive.

---

## Rules in this family

### `RPY501` — Missing audio file

**Severity:** `ERROR`

Audio file referenced in `play` or `queue` was not found on disk, in
`audio/`, or inside `.rpa` archives.

```renpy
# Bad — bgm/non_existent_track.ogg doesn't exist
play music "bgm/non_existent_track.ogg"

# Good
play music "bgm/existing_track.ogg"
```

Senpy searches:

- The `audio/` directory relative to the project root
- Every `.rpa` archive in `game/`
- Any `define audio.X = "..."` aliases

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy501)

---

### `RPY502` — Missing or mistyped sprite / background

**Severity:** `WARNING` | **Auto-fix:** ✅ (QuickFix suggests closest match)

Sprite attribute or background shown via `show` or `scene` does not
exist in asset folders, `layeredimage` definitions, or `image`
declarations.

```renpy
# Bad — 99z_crazy_pose doesn't exist anywhere
show sayori 99z_crazy_pose

# Good
show sayori 1a
```

QuickFix (`Ctrl+.` in VS Code) suggests the closest matching sprite
or attribute name (case-insensitive: `show Sayori` → suggests
`sayori`).

Senpy resolves:

- `image` declarations (`image bg room = "..."`)
- `layeredimage` definitions (`layeredimage sayori: ...`)
- Files in `game/images/`, `game/sprites/`, etc. (any directory
  scanned for `MEDIA_EXTENSIONS`)

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy502)

---

### `RPY503` — Unused media asset on disk

**Severity:** `WARNING`

Image or audio files located in the project directory are never
referenced in any script. Inflates build distribution size.

```renpy
# Bad: game/images/unused_background.png exists on disk but is never shown

# Good: Show the asset in script or remove the unused file
```

Senpy excludes:

- `.rpy`, `.rpym`, `.rpyc`, `.rpa` files — they're code, not media
- Files explicitly referenced via `define audio.X = "..."` aliases
- Files referenced in `image` declarations

For large projects with hundreds of cut-content assets, this rule
helps you identify what to delete before building a distribution.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy503)

---

### `RPY504` — Duplicate image declaration

**Severity:** `WARNING` for overrides (second declaration shadows the first);
`INFO` for exact duplicates (same tag + same path — likely a copy-paste error).

Declaring the same image tag twice (via `image name = ...` or
`image name:`) silently overrides the previous definition,
potentially masking bugs.

```renpy
# Bad — second image silently overrides first
image bg room = "day.png"
image bg room = "night.png"

# Good — give them distinct names
image bg room_day = "day.png"
image bg room_night = "night.png"
```

If the override is intentional (e.g. a mod that overrides a base
image), you can suppress this rule per-line:

```renpy
image bg room = "modded.png"   # noqa: RPY504
```

Or project-wide in `senpy.toml`:

```toml
[tool.senpy]
allow_image_overrides = true   # suppress all RPY504 reports
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy504)

---

### `RPY505` — Unregistered audio channel or voice loop

**Severity:** `ERROR` (unregistered channel) / `WARNING` (voice loop)

Playing audio on a custom channel not registered via
`renpy.music.register_channel()` causes a runtime `Exception`.
Looping the `voice` channel causes audio overlap glitches during
dialogue progression.

```renpy
# Bad — 'ambient' was never registered, voice shouldn't loop
play ambient "rain.ogg"
play voice "clip.ogg" loop

# Good — register channel first, voice doesn't loop
init python:
    renpy.music.register_channel("ambient", mixer="sfx", loop=True)

play ambient "rain.ogg"
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy505)

---

## Common patterns caught

### "Audio file exists but path is wrong"

`RPY501` catches both:

- The file doesn't exist anywhere (`bgm/missing_track.ogg`).
- The file exists in `game/audio/` but the script says
  `play music "audio/missing_track.ogg"` (wrong path).

### "Sprite works in dev, crashes for players"

`RPY502` catches sprites that:

- Don't exist as files (`show sayori 99z_crazy_pose` — there's no
  file or layeredimage with that attribute)
- Are case-mismatched (`show Sayori` when the file is `sayori.png` —
  works on case-insensitive filesystems like Windows/macOS, fails
  on Linux)
- Are typo'd in a way that the closest match is obvious (`show sayori
  hapy` → QuickFix suggests `happy`)

### "Build is 500 MB, should be 200 MB"

`RPY503` lists every image/audio file on disk that's never
referenced. After a major content cut, run Senpy and delete the
unused assets — it directly reduces build size and download time.

### "Mod overrides an image silently"

`RPY504` is mostly a warning about *intent*. If you're modding a
game and intentionally overriding an image, the rule is noise —
suppress with `# noqa: RPY504` or `allow_image_overrides = true` in
`senpy.toml`.

---

## Auto-fix summary

| Rule | Auto-fixable | How |
|---|---|---|
| `RPY502` | ✅ | QuickFix suggests the closest matching sprite/attribute name |

---

## Tags

| Rule | Tags |
|---|---|
| `RPY501`, `RPY505` | `audio`, `assets` |
| `RPY502`, `RPY503`, `RPY504` | `assets` |

```bash
senpy /path/to/game --tag audio   # only audio rules
senpy /path/to/game --tag assets   # only asset rules
```

---

## What's next?

- [RPY7xx — Dead Code](rpy7xx-deadcode.md) — unused `define`,
  `transform`, `screen` (related but for code, not media).
- [All 52 rules](index.md) — back to the navigator.
- [RULES.md in repo](https://github.com/Xilleet/senpy/blob/main/RULES.md)
  — canonical reference.
