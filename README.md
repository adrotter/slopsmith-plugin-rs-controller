# Slopsmith Rocksmith Sync

Slopsmith Rocksmith Sync uses **Rocksmith 2014 as the clock and song selector**
while **Slopsmith Desktop supplies the backing audio**. It is intended for
playing Rocksmith's note highway with Slopsmith's audio engine and signal
chain.

## Behavior

- Rocksmith is authoritative for song selection, play/pause, and position.
- Slopsmith selects a same-key `.sloppak` package when available.
- For `.sloppak` files produced by Slopsmith's converter, Rocksmith Sync also
  reads the source PSARC's `DLCKey`, so CDLC can match even when its filename
  does not resemble Rocksmith's internal song key.
- Slopsmith uses a `.psarc` package only when no matching `.sloppak` exists.
- A global offset is available in milliseconds:
  - positive values make Slopsmith play ahead of Rocksmith;
  - negative values make Slopsmith play behind Rocksmith.
- Slopsmith continuously corrects drift outside the configurable threshold.
- Slopsmith waits briefly for Rocksmith's highlighted song to remain stable
  before loading it, avoiding repeated loads while browsing the song list.
- Slopsmith waits for the selected backing audio, including all decoded
  `.sloppak` stems, before it starts playback. A short repeating synthesized
  cue indicates loading; a different cue sounds when playback can begin.
- Set Rocksmith **Song Volume** to **0** once so Slopsmith is the only
  backing-audio source, and turn **Audio Exclusivity** off so Slopsmith can
  use the audio device while Rocksmith is running.

## Components

The plugin includes a Windows read-only Rocksmith process reader. It follows
the song key, timer, and menu pointer chains documented by RSMods, but it does
not require an RSMods modification or write anything into Rocksmith.

```text
Rocksmith2014.exe (read-only state) -> Slopsmith plugin -> Slopsmith audio engine
```

RSMods can remain installed for its other features; Rocksmith Sync does not
depend on a companion RSMods DLL.

## Install

1. Install Slopsmith Desktop. Native Audio Engine routing is optional; Rocksmith
   Sync does not turn it on automatically.
2. Place this directory at:

   ```text
   %APPDATA%\slopsmith-desktop\plugins\slopsmith-rocksmith-sync
   ```

3. In Rocksmith's mixer settings, set **Song Volume** to **0**.
4. In Rocksmith's audio settings, turn **Audio Exclusivity** off.
5. Restart Slopsmith Desktop and open **Rocksmith Sync**.
6. Start Rocksmith and select a song. The plugin selects the matching
   Slopsmith package and follows Rocksmith gameplay time.

## Song Matching

Most CDLC files match automatically because Rocksmith song key `foo` commonly
uses `foo_p.psarc` or `foo_p.sloppak`. Matching ignores punctuation and usual
arrangement suffixes.

When a package has a different filename, open **Rocksmith Sync** and add a
manual mapping:

```text
Rocksmith song key: somekey
Relative DLC path: custom-folder/my-package.sloppak
```

Mappings are stored in Slopsmith's config directory and survive restarts.
Matching still prefers an automatic or manual `.sloppak` over any `.psarc`.

## Configuration

| Setting | Default | Meaning |
| --- | ---: | --- |
| Enabled | On | Follow Rocksmith song selection and playback. |
| Global offset | `0 ms` | Signed Slopsmith lead/lag relative to Rocksmith. |
| Correction threshold | `70 ms` | Seek-resync only when Slopsmith is ahead or behind Rocksmith by more than this amount. |
| Song selection delay | `750 ms` | Wait for a stable Rocksmith selection before loading it. |
| Show sync controls in player | On | Show the player checkbox and offset field. |
| Play tone when drift correction occurs | Off | Sound a short cue when active playback is seek-corrected. |

The Slopsmith player controls expose the `Rocksmith Sync` checkbox and global
offset field. Uncheck sync to relinquish playback control to Slopsmith, or
adjust the signed millisecond offset during a song without leaving the player
screen. The player controls can be hidden from plugin settings.

## Compatibility

- Windows and Slopsmith Desktop are required.
- Rocksmith Sync currently supports the Rocksmith builds represented in the
  bundled RSMods source: Remastered September 2022 and Learn & Play December
  2024.
- Unknown executable checksums are rejected with an unsupported-build status
  rather than reading unknown memory offsets.

## Development

Run tests from this directory:

```powershell
py -3 -B -m unittest discover -s tests -v
node --check screen.js
```

The plugin has no additional Python package dependencies beyond Slopsmith's
FastAPI runtime.

## License

AGPL-3.0-only. This matches Slopsmith Desktop, whose server/browser runtime
loads the plugin.
