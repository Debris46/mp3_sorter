# sort_music

A CLI tool that organizes MP3 files into genre folders and normalizes filenames.

## Installation

```bash
pip install -r requirements.txt
```

**Optional (for fingerprint fallback):** Install [Chromaprint](https://acoustid.org/chromaprint) and add `fpcalc` to your PATH. Get a free AcoustID API key at <https://acoustid.org/login>.

**Optional (for Discogs genre lookup):** Get a free personal access token at <https://www.discogs.com/settings/developers>. Unauthenticated requests work but are rate-limited to 25/min.

## Usage

```
sort_music.py [-h] [--dry-run] [--copy] [--no-rename] [--acoustid-key KEY]
              [--discogs-token TOKEN] [--verify] source [destination]
```

| Argument | Default | Description |
|---|---|---|
| `source` | — | Source folder to scan recursively |
| `destination` | `./Sorted` | Root folder for sorted output |
| `--dry-run` | off | Print actions without touching files |
| `--copy` | off | Copy files instead of moving them |
| `--no-rename` | off | Skip filename normalization; only sort |
| `--verify` | off | Cross-check each ID3 genre against MusicBrainz; overrides on mismatch |
| `--acoustid-key KEY` | env var `ACOUSTID_API_KEY` | AcoustID key for audio fingerprint fallback |
| `--discogs-token TOKEN` | env var `DISCOGS_TOKEN` | Discogs token for genre lookup (optional; anonymous works at lower rate) |

**Examples:**

```bash
# Preview what would happen (safe, touches nothing)
python sort_music.py /music/unsorted --dry-run

# Sort into ./Sorted, normalizing filenames
python sort_music.py /music/unsorted

# Copy (leave originals in place) into a custom destination
python sort_music.py /music/unsorted /music/sorted --copy

# Sort without renaming, using fingerprinting for untagged files
python sort_music.py /music/unsorted --no-rename --acoustid-key YOUR_KEY

# Cross-check all ID3 genres against MusicBrainz and report mismatches
python sort_music.py /music/unsorted --dry-run --verify

# Use Discogs to resolve unknown genres and upgrade generic Electronic
python sort_music.py /music/unsorted --discogs-token YOUR_TOKEN

# Set keys via environment variables instead
export ACOUSTID_API_KEY=YOUR_KEY
export DISCOGS_TOKEN=YOUR_TOKEN
python sort_music.py /music/unsorted
```

## Output folder structure

```
Sorted/
  Techno/          Artist - Title [Remix].mp3
  House/           ...
  Trance/          ...
  Ambient/         ...
  Chill/           ...
  Drum and Bass/   ...
  Downtempo/       ...
  Electronic/      (catch-all for unrecognized electronic subgenres)
  Rock/
  Pop/
  ...
  _Unknown/        (no tag + fingerprint failed or returned no match)
```

## Filename format

```
Artist - Song Title [Version].mp3
```

Examples:
- `Bicep - Glue [Bicep Remix].mp3`
- `The Prodigy - Firestarter.mp3`
- `DJ Shadow vs MC Solaar - Track.mp3`

## How genre detection works

1. Read the ID3 `TCON` genre tag with mutagen
2. Normalize: strip whitespace, resolve Winamp numeric codes like `(18)` → "Techno"
3. Match against **`GENRE_RULES`** (ordered list, first match wins)
4. If no match, try **`STANDARD_GENRES`** (Rock, Pop, Jazz, etc.)
5. If still unresolved, query **MusicBrainz by artist + title** (no API key needed):
   - Tries recording-level tags first, falls back to artist-level tags
   - Outputs `[WEB] filename: genre 'deep house' -> 'House'` when a match is found
6. Query **Discogs by artist + title** for files still unresolved OR sorted into generic `Electronic/`:
   - Discogs `style` field gives specific subgenres (e.g. `Deep House`) that MusicBrainz often lacks
   - Outputs `[DISCOGS] filename: genre 'Deep House' -> 'House'`
   - Works anonymously; provide `--discogs-token` for a higher rate limit (60 vs 25 req/min)
7. If still unresolved and an AcoustID key is provided, fingerprint the audio via pyacoustid + MusicBrainz
8. Unresolved files go into `_Unknown/`

### `--verify` mode

When `--verify` is passed, every file whose genre was resolved from its **ID3 tag** is also looked up on MusicBrainz. On a mismatch, the web genre **overrides** the ID3 genre for sorting:

```
[VERIFY OK]  file.mp3: 'Pop' confirmed by MusicBrainz
[CORRECTED]  file.mp3: 'Electronic' (ID3:'Dance') -> 'House' (web:'afro house')
[VERIFY]     file.mp3: 'House' (MusicBrainz returned no genre)
```

### Electronic subgenre preference

Whenever MusicBrainz or Discogs is queried, the tool prefers a **specific subgenre** over the generic `Electronic` catch-all. For example, if Discogs styles include `Deep House`, the file is sorted into `House/` rather than `Electronic/`. Files already sorted into `Electronic/` via their ID3 tag are also re-checked against Discogs and upgraded if a specific subgenre is found.

## Extending the genre map

### Add a new electronic subgenre

Open `sort_music.py` and add a tuple to `GENRE_RULES` **before** the `Electronic` catch-all:

```python
GENRE_RULES: list[tuple[re.Pattern, str]] = [
    ...
    (re.compile(r"hardstyle|hardcore", re.I), "Hardstyle"),   # ← new rule
    (re.compile(r"electr(?:onic|o)|synth|edm|\bdance\b", re.I), "Electronic"),
]
```

Order matters — more specific patterns go higher in the list.

### Add a new standard genre

Add an entry to `STANDARD_GENRES`:

```python
STANDARD_GENRES: dict[str, str] = {
    ...
    r"bossa\s*nova": "Bossa Nova",   # ← new rule
}
```

The key is a regex pattern matched case-insensitively against the normalized tag.

## Extending filename rename rules

### Add a new version keyword

Extend `_VERSION_RE` in `sort_music.py` to add a new fixed string:

```python
_VERSION_RE = re.compile(
    r"\("
    r"("
    r"...(existing pattern)..."
    r"|Acappella"         # ← add new keyword here
    r")"
    r"\)",
    re.IGNORECASE,
)
```

Or, if it follows the `(Artist Keyword)` pattern, it's already covered by:

```
(?:[\w][^()]*?\s+(?:Remix|Edit|Rework|Bootleg|Mashup|Mix|VIP))
```

### Preserve a new uppercase acronym

Add to `PRESERVE_UPPER` in `sort_music.py`:

```python
PRESERVE_UPPER: frozenset[str] = frozenset({"DJ", "MC", "UK", ..., "NYC"})
```

## Requirements

- Python 3.10+
- `mutagen` — required for tag reading/writing
- `pyacoustid` + `musicbrainzngs` — optional, for fingerprinting untagged files
- `fpcalc` — optional binary (Chromaprint), required for fingerprinting
