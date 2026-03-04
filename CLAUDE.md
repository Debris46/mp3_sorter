# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the tool

```bash
# Dry run (safe preview, no files moved)
python sort_music.py <source> [destination] --dry-run

# Sort with filename normalization (default: moves files)
python sort_music.py <source> [destination]

# Copy instead of move, skip rename, cross-check genres
python sort_music.py <source> [destination] --copy --no-rename --verify
```

## Installing dependencies

```bash
pip install -r requirements.txt
# Optional: install Chromaprint (fpcalc) for audio fingerprinting
# https://acoustid.org/chromaprint
```

## Architecture

Single-file script (`sort_music.py`). Processing pipeline per file inside `process_file()`:

1. **Tag read** — `get_id3_metadata()` via mutagen (TCON, TPE1, TIT2)
2. **Genre detection** — `normalize_genre()` → `detect_genre()` → matches `GENRE_RULES` then `STANDARD_GENRES`
3. **`--verify`** — `lookup_by_metadata()` cross-checks ID3 genre against MusicBrainz; warns on folder mismatch
4. **Web lookup** (auto, when genre still unknown) — `lookup_by_metadata()`: MusicBrainz text search → recording tags → artist tags fallback
5. **Audio fingerprint** (optional, needs `fpcalc` + AcoustID key) — `fingerprint_file()` via pyacoustid + MusicBrainz
6. **Rename** — `parse_filename()` → `extract_version()` → `build_normalized_filename()` → format: `Artist - Title [Version].mp3`
7. **Move/copy** — `shutil.move` / `shutil.copy2` into `<destination>/<Genre>/`
8. **Tag write-back** — `write_id3_metadata()` writes normalized TPE1/TIT2

## Extending genre rules

**Electronic subgenres** — edit `GENRE_RULES` (top of file, ordered list; first match wins):
```python
GENRE_RULES = [
    (re.compile(r"hardstyle", re.I), "Hardstyle"),  # add before Electronic catch-all
    ...
]
```

**Standard genres** — edit `STANDARD_GENRES` dict (regex pattern → folder name).

**Version/remix keywords** — extend `_VERSION_RE` alternation group.

**Title-case acronyms** — add to `PRESERVE_UPPER` frozenset (e.g. `"NYC"`).

## Key constants (all at top of file)

| Name | Purpose |
|---|---|
| `GENRE_RULES` | Ordered list of `(compiled_regex, folder)` for electronic genres |
| `STANDARD_GENRES` | Dict of `{regex_pattern: folder}` for Rock, Pop, Jazz, etc. |
| `WINAMP_GENRES` | ID3v1 numeric code table (0–125) for resolving tags like `(18)` → "Techno" |
| `_VERSION_RE` | Regex for extracting remix/version tags from titles |
| `PRESERVE_UPPER` | Frozenset of acronyms to keep uppercase (DJ, MC, UK…) |
| `PRESERVE_LOWER` | Frozenset of connector words to keep lowercase (vs, feat, ft…) |

## Optional dependencies

- `mutagen` — **required**; hard exit if missing
- `musicbrainzngs` — optional (`_MB_AVAILABLE`); enables web genre lookup and fingerprint MusicBrainz calls; no fpcalc needed
- `acoustid` — optional (`_ACOUSTID_AVAILABLE`); enables audio fingerprinting; requires `fpcalc` binary in PATH and an AcoustID API key (`--acoustid-key` or `ACOUSTID_API_KEY` env var)
