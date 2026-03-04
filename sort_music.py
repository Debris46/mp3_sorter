#!/usr/bin/env python3
"""sort_music.py — Organize MP3 files into genre folders with filename normalization."""

import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional dependencies
# ---------------------------------------------------------------------------
# musicbrainzngs — text-based web lookup (no fpcalc required)
try:
    import musicbrainzngs

    musicbrainzngs.set_useragent("sort_music", "1.0", "https://github.com/user/sort_music")
    _MB_AVAILABLE = True
except ImportError:
    _MB_AVAILABLE = False

# acoustid — audio fingerprinting (requires fpcalc binary in PATH)
try:
    import acoustid

    _ACOUSTID_AVAILABLE = True
except ImportError:
    _ACOUSTID_AVAILABLE = False

# ---------------------------------------------------------------------------
# GENRE_RULES — ordered list of (compiled_regex, folder_name).
# First match wins. Add new rules here; place more specific rules above general ones.
# ---------------------------------------------------------------------------
GENRE_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"techno", re.I), "Techno"),
    (re.compile(r"trance", re.I), "Trance"),
    (re.compile(r"ambient", re.I), "Ambient"),
    (re.compile(r"chill(?:out|step)?", re.I), "Chill"),
    (re.compile(r"\bhouse\b", re.I), "House"),
    (re.compile(r"drum\s*.*(and|&|n)\s*.*bass|dnb", re.I), "Drum and Bass"),
    (re.compile(r"downtempo|trip[-\s]hop", re.I), "Downtempo"),
    (re.compile(r"electr(?:onic|o)|synth|edm|\bdance\b|eurodance|rave", re.I), "Electronic"),
]

# STANDARD_GENRES — fallback dict for non-electronic genres.
# Keys are regex patterns (compiled with re.I); values are folder names.
STANDARD_GENRES: dict[str, str] = {
    r"rock":                     "Rock",
    r"pop":                      "Pop",
    r"jazz":                     "Jazz",
    r"blues":                    "Blues",
    r"classical|orchestra":      "Classical",
    r"country":                  "Country",
    r"folk":                     "Folk",
    r"hip.?hop|rap|grime":       "Hip-Hop",
    r"r&b|rnb|r\s*n\s*b|soul":  "R&B",
    r"metal":                    "Metal",
    r"punk":                     "Punk",
    r"reggae":                   "Reggae",
    r"funk":                     "Funk",
    r"latin":                    "Latin",
    r"ska":                      "Ska",
    r"indie":                    "Indie",
    r"alternative":              "Alternative",
    r"gospel":                   "Gospel",
    r"new\s*age":                "New Age",
    r"world":                    "World",
    r"industrial":               "Industrial",
}

# WINAMP_GENRES — ID3v1 numeric genre code table (codes 0–125).
WINAMP_GENRES: dict[int, str] = {
    0: "Blues",            1: "Classic Rock",      2: "Country",
    3: "Dance",            4: "Disco",              5: "Funk",
    6: "Grunge",           7: "Hip-Hop",            8: "Jazz",
    9: "Metal",           10: "New Age",            11: "Oldies",
    12: "Other",          13: "Pop",               14: "R&B",
    15: "Rap",            16: "Reggae",             17: "Rock",
    18: "Techno",         19: "Industrial",         20: "Alternative",
    21: "Ska",            22: "Death Metal",        23: "Pranks",
    24: "Soundtrack",     25: "Euro-Techno",        26: "Ambient",
    27: "Trip-Hop",       28: "Vocal",              29: "Jazz+Funk",
    30: "Fusion",         31: "Trance",             32: "Classical",
    33: "Instrumental",   34: "Acid",               35: "House",
    36: "Game",           37: "Sound Clip",         38: "Gospel",
    39: "Noise",          40: "Alternative Rock",   41: "Bass",
    42: "Soul",           43: "Punk",               44: "Space",
    45: "Meditative",     46: "Instrumental Pop",   47: "Instrumental Rock",
    48: "Ethnic",         49: "Gothic",             50: "Darkwave",
    51: "Techno-Industrial", 52: "Electronic",      53: "Pop-Folk",
    54: "Eurodance",      55: "Dream",              56: "Southern Rock",
    57: "Comedy",         58: "Cult",               59: "Gangsta Rap",
    60: "Top 40",         61: "Christian Rap",      62: "Pop/Funk",
    63: "Jungle",         64: "Native American",    65: "Cabaret",
    66: "New Wave",       67: "Psychedelic",        68: "Rave",
    69: "Showtunes",      70: "Trailer",            71: "Lo-Fi",
    72: "Tribal",         73: "Acid Punk",          74: "Acid Jazz",
    75: "Polka",          76: "Retro",              77: "Musical",
    78: "Rock & Roll",    79: "Hard Rock",          80: "Folk",
    81: "Folk-Rock",      82: "National Folk",      83: "Swing",
    84: "Fast Fusion",    85: "Bebop",              86: "Latin",
    87: "Revival",        88: "Celtic",             89: "Bluegrass",
    90: "Avantgarde",     91: "Gothic Rock",        92: "Progressive Rock",
    93: "Psychedelic Rock", 94: "Symphonic Rock",   95: "Slow Rock",
    96: "Big Band",       97: "Chorus",             98: "Easy Listening",
    99: "Acoustic",      100: "Humour",            101: "Speech",
    102: "Chanson",      103: "Opera",             104: "Chamber Music",
    105: "Sonata",       106: "Symphony",          107: "Booty Bass",
    108: "Primus",       109: "Porn Groove",       110: "Satire",
    111: "Slow Jam",     112: "Club",              113: "Tango",
    114: "Samba",        115: "Folklore",          116: "Ballad",
    117: "Power Ballad", 118: "Rhythmic Soul",     119: "Freestyle",
    120: "Duet",         121: "Punk Rock",         122: "Drum Solo",
    123: "A Capella",    124: "Euro-House",        125: "Dance Hall",
}

# ---------------------------------------------------------------------------
# Compiled regexes (defined once for performance)
# ---------------------------------------------------------------------------
_WINAMP_CODE_RE = re.compile(r"^\((\d+)\)$")       # exact: "(18)"
_WINAMP_PREFIX_RE = re.compile(r"^\((\d+)\)\s*")   # prefix: "(18) Techno"
_TRACK_NUM_RE = re.compile(r"^\d+[\s._-]+")
_ILLEGAL_CHARS_RE = re.compile(r'[/\\:*?"<>|]')
_MULTI_SPACE_RE = re.compile(r" {2,}")
_ARTIST_SPLIT_RE = re.compile(r"[/,]")

# Version/remix pattern — matches parenthesized version tags in track titles.
# Add new version keywords to the alternation group inside the non-capturing group.
_VERSION_RE = re.compile(
    r"\("
    r"("
    r"(?:[\w][^()]*?\s+(?:Remix|Edit|Rework|Bootleg|Mashup|Mix|VIP))"
    r"|Original Mix"
    r"|Extended Mix"
    r"|Radio Edit"
    r"|VIP"
    r"|Club Mix"
    r"|Dub Mix"
    r"|Instrumental"
    r")"
    r"\)",
    re.IGNORECASE,
)

# Title-case word sets. Add acronyms or lowercase connectors here.
PRESERVE_UPPER: frozenset[str] = frozenset({"DJ", "MC", "UK", "ID", "EDM", "EP", "LP", "II", "III", "IV", "VS"})
PRESERVE_LOWER: frozenset[str] = frozenset({"vs", "feat", "ft", "the", "a", "an", "and", "or", "of", "in", "on"})

SCORE_THRESHOLD = 0.6  # minimum AcoustID confidence to accept a fingerprint match
DISCOGS_SEARCH_URL = "https://api.discogs.com/database/search"

# ---------------------------------------------------------------------------
# Warn-once helper (suppresses repeated warnings for the same issue)
# ---------------------------------------------------------------------------
_WARN_FLAGS: dict[str, bool] = {}


def _warn_once(key: str, message: str) -> None:
    if not _WARN_FLAGS.get(key):
        print(f"WARNING: {message}", file=sys.stderr)
        _WARN_FLAGS[key] = True


# ---------------------------------------------------------------------------
# Genre normalization
# ---------------------------------------------------------------------------

def normalize_winamp_code(raw: str) -> str:
    """Resolve Winamp numeric genre codes like '(18)' or '(18) Techno' to a text name."""
    # Exact match: entire string is "(N)"
    m = _WINAMP_CODE_RE.match(raw.strip())
    if m:
        code = int(m.group(1))
        return WINAMP_GENRES.get(code, raw)
    # Prefix match: "(N) Some Text"
    m = _WINAMP_PREFIX_RE.match(raw.strip())
    if m:
        code = int(m.group(1))
        rest = raw.strip()[m.end():].strip()
        resolved = WINAMP_GENRES.get(code, "")
        return (resolved + " " + rest).strip() if resolved else (rest or raw)
    return raw


def normalize_genre(raw: str) -> str:
    """Normalize a raw ID3 genre tag: strip, resolve Winamp codes, lowercase."""
    cleaned = normalize_winamp_code(raw.strip())
    return cleaned.lower()


def detect_genre(normalized: str) -> str | None:
    """Map a normalized (lowercased) genre string to a target folder name.

    Returns the folder name string, or None if no match found.
    """
    # 1. Electronic subgenres (ordered list, first match wins)
    for pattern, folder in GENRE_RULES:
        if pattern.search(normalized):
            return folder
    # 2. Standard genres (dict, unordered)
    for pat_str, folder in STANDARD_GENRES.items():
        if re.search(pat_str, normalized, re.I):
            return folder
    return None


# ---------------------------------------------------------------------------
# Filename normalization
# ---------------------------------------------------------------------------

def parse_filename(stem: str) -> tuple[str, str]:
    """Extract (artist, title) from a filename stem (no extension).

    Handles patterns: 'Artist - Title', 'Artist_-_Title', 'Artist_Title',
    '01 Artist - Title'. Falls back to ('Unknown', stem).
    """
    # Strip leading track numbers like "01 ", "103_", "07."
    stem = _TRACK_NUM_RE.sub("", stem).strip()

    if " - " in stem:
        artist, _, title = stem.partition(" - ")
        return artist.strip(), title.strip()

    if "_-_" in stem:
        parts = stem.split("_-_", 1)
        return parts[0].replace("_", " ").strip(), parts[1].replace("_", " ").strip()

    if "_" in stem:
        parts = stem.split("_", 1)
        return parts[0].replace("_", " ").strip(), parts[1].replace("_", " ").strip()

    return "Unknown", stem


def extract_version(title: str) -> tuple[str, str | None]:
    """Extract a version/remix tag from a title string.

    Returns (clean_title, version_string) or (title, None) if no match.
    Example: 'Track (Extended Mix)' → ('Track', 'Extended Mix')
    """
    m = _VERSION_RE.search(title)
    if not m:
        return title, None
    version = m.group(1)
    clean = title[: m.start()] + title[m.end():]
    # Tidy up residual trailing dashes/spaces
    clean = clean.strip().rstrip("-").rstrip()
    return clean, version


def normalize_artists(raw: str) -> str:
    """Split multi-artist strings on '/' or ',' and rejoin with ' & '."""
    parts = [p.strip() for p in _ARTIST_SPLIT_RE.split(raw) if p.strip()]
    return " & ".join(parts)


def smart_title_case(s: str) -> str:
    """Apply title case while preserving known acronyms and lowercase connectors.

    Preserves: DJ, MC, UK, ID, etc. (uppercase)
    Lowercases: vs, feat, ft, and, or, of, in, on, the, a, an (unless first word)
    """
    words = s.split()
    result = []
    for i, word in enumerate(words):
        # Strip trailing punctuation for lookup, reattach after
        suffix = ""
        core = word
        while core and core[-1] in ".,;:!?":
            suffix = core[-1] + suffix
            core = core[:-1]

        upper_core = core.upper()
        lower_core = core.lower()

        if upper_core in PRESERVE_UPPER:
            result.append(upper_core + suffix)
        elif lower_core in PRESERVE_LOWER and i > 0:
            # Connector words stay lowercase unless they're the first word
            result.append(lower_core + suffix)
        else:
            result.append(core.capitalize() + suffix)

    return " ".join(result)


def sanitize(s: str) -> str:
    """Remove characters illegal in filenames, collapse multiple spaces, strip."""
    s = _ILLEGAL_CHARS_RE.sub("", s)
    s = _MULTI_SPACE_RE.sub(" ", s)
    return s.strip()


def build_normalized_filename(artist: str, title: str, version: str | None) -> str:
    """Construct the normalized filename: 'Artist - Title [Version].mp3'."""
    artist = sanitize(smart_title_case(normalize_artists(artist)))
    title = sanitize(smart_title_case(title))

    if version:
        version_str = sanitize(smart_title_case(version))
        return f"{artist} - {title} [{version_str}].mp3"
    return f"{artist} - {title}.mp3"


# ---------------------------------------------------------------------------
# ID3 tag I/O
# ---------------------------------------------------------------------------

def get_id3_metadata(filepath: Path) -> dict:
    """Read ID3 genre, artist, and title from an MP3 file.

    Returns dict with keys 'genre', 'artist', 'title' (all str | None).
    """
    try:
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3NoHeaderError
    except ImportError:
        print("ERROR: mutagen is required. Install it with: pip install mutagen", file=sys.stderr)
        sys.exit(1)

    result = {"genre": None, "artist": None, "title": None}
    try:
        audio = MP3(filepath)
        if not audio.tags:
            return result
        tags = audio.tags
        if "TCON" in tags and tags["TCON"].text:
            result["genre"] = tags["TCON"].text[0].strip() or None
        if "TPE1" in tags and tags["TPE1"].text:
            result["artist"] = tags["TPE1"].text[0].strip() or None
        if "TIT2" in tags and tags["TIT2"].text:
            result["title"] = tags["TIT2"].text[0].strip() or None
    except Exception as e:  # ID3NoHeaderError, MutagenError, etc.
        name = getattr(e, "__class__", type(e)).__name__
        if "NoHeader" not in name:
            print(f"WARNING: cannot read tags for {filepath.name}: {e}", file=sys.stderr)
    return result


def write_id3_metadata(filepath: Path, artist: str, title: str) -> None:
    """Write normalized artist and title back to the file's ID3 tags."""
    try:
        from mutagen.id3 import ID3, TPE1, TIT2, ID3NoHeaderError
        try:
            tags = ID3(filepath)
        except ID3NoHeaderError:
            tags = ID3()
        tags["TPE1"] = TPE1(encoding=3, text=artist)
        tags["TIT2"] = TIT2(encoding=3, text=title)
        tags.save(filepath, v2_version=3)
    except Exception as e:
        print(f"WARNING: could not write tags to {filepath.name}: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# MusicBrainz helpers (text search + fingerprint fallback)
# ---------------------------------------------------------------------------

def _best_genre_from_tags(tag_list: list[dict]) -> str | None:
    """Pick the most informative genre name from a MusicBrainz tag list.

    Prefers specific electronic subgenres (House, Techno, Trance, etc.) over
    the generic 'Electronic' catch-all. Among candidates of equal specificity,
    the one with the highest vote count wins.
    """
    if not tag_list:
        return None

    sorted_tags = sorted(tag_list, key=lambda t: int(t.get("count", 0)), reverse=True)

    # First pass: prefer any tag that maps to a specific (non-Electronic) folder
    for tag in sorted_tags:
        folder = detect_genre(normalize_genre(tag["name"]))
        if folder and folder != "Electronic":
            return tag["name"]

    # Second pass: accept the top tag even if it maps to Electronic or nothing
    return sorted_tags[0]["name"]


def _extract_mb_recording(
    recording: dict,
    mb_title: str | None = None,
    mb_artist: str | None = None,
) -> dict:
    """Extract genre, artist, and title from a MusicBrainz recording dict."""
    tag_list = recording.get("tag-list", [])
    genre_str = _best_genre_from_tags(tag_list)

    credits = recording.get("artist-credit", [])
    if credits and isinstance(credits[0], dict):
        mb_artist = credits[0].get("artist", {}).get("name", mb_artist)

    title_out = recording.get("title") or mb_title
    return {"genre": genre_str, "artist": mb_artist, "title": title_out}


def lookup_by_metadata(artist: str, title: str, filename: str = "") -> dict:
    """Search MusicBrainz by artist name + track title. Returns {genre, artist, title}.

    Uses a text search — no fpcalc required. Falls back gracefully if unavailable.
    Genre resolution order:
      1. Recording-level tags (precise but often absent)
      2. Artist-level tags (broader but much better coverage)
    """
    empty: dict = {"genre": None, "artist": None, "title": None}

    if not _MB_AVAILABLE:
        _warn_once(
            "mb_missing",
            "musicbrainzngs not installed — web lookup disabled. "
            "Install with: pip install musicbrainzngs",
        )
        return empty

    try:
        result = musicbrainzngs.search_recordings(
            recording=title, artistname=artist, limit=5
        )
        recordings = result.get("recording-list", [])
        if not recordings:
            return empty

        best = recordings[0]

        # Extract artist MBID and seed metadata from the search result
        seed_artist: str | None = None
        seed_title: str | None = best.get("title")
        artist_mbid: str | None = None
        ac = best.get("artist-credit", [])
        if ac and isinstance(ac[0], dict):
            seed_artist = ac[0].get("artist", {}).get("name")
            artist_mbid = ac[0].get("artist", {}).get("id")

        # 1. Try recording-level tags
        rec_full = musicbrainzngs.get_recording_by_id(
            best["id"], includes=["tags", "artist-credits"]
        )
        recording = rec_full.get("recording", {})
        tag_list = recording.get("tag-list", [])

        # 2. Fall back to artist-level tags when recording has none
        if not tag_list and artist_mbid:
            artist_data = musicbrainzngs.get_artist_by_id(artist_mbid, includes=["tags"])
            tag_list = artist_data.get("artist", {}).get("tag-list", [])

        genre_str = _best_genre_from_tags(tag_list)

        return {
            "genre": genre_str,
            "artist": seed_artist or artist,
            "title": seed_title or title,
        }

    except Exception as e:
        label = f" for {filename}" if filename else ""
        print(f"WARNING: MusicBrainz text lookup failed{label}: {e}", file=sys.stderr)
        return empty


def lookup_by_discogs(
    artist: str, title: str, token: str | None = None, filename: str = ""
) -> dict:
    """Search Discogs by artist + track title. Returns {genre, artist, title}.

    Uses only stdlib (urllib + json). The ``style`` field gives specific subgenres
    (e.g. 'Deep House') that MusicBrainz tags often lack.

    Unauthenticated requests are rate-limited to 25/min; provide a token for 60/min.
    Get a free token at https://www.discogs.com/settings/developers
    """
    empty: dict = {"genre": None, "artist": None, "title": None}

    params = {
        "type": "release",
        "artist": artist,
        "track": title,
        "per_page": "5",
        "page": "1",
    }
    url = DISCOGS_SEARCH_URL + "?" + urllib.parse.urlencode(params)
    headers = {"User-Agent": "sort_music/1.0 +https://github.com/sort_music"}
    if token:
        headers["Authorization"] = f"Discogs token={token}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            _warn_once(
                "discogs_rate",
                "Discogs rate limit reached — slow down or use --discogs-token for a higher limit.",
            )
        else:
            label = f" for {filename}" if filename else ""
            print(f"WARNING: Discogs request failed{label}: HTTP {e.code}", file=sys.stderr)
        return empty
    except Exception as e:
        label = f" for {filename}" if filename else ""
        print(f"WARNING: Discogs lookup failed{label}: {e}", file=sys.stderr)
        return empty

    results = data.get("results", [])
    if not results:
        return empty

    # Aggregate tags across the top results; styles are weighted 3x over genres
    # because Discogs styles are more specific (e.g. 'Deep House' vs 'Electronic')
    tag_counter: dict[str, int] = {}
    for r in results[:3]:
        for s in r.get("style", []):
            tag_counter[s] = tag_counter.get(s, 0) + 3
        for g in r.get("genre", []):
            tag_counter[g] = tag_counter.get(g, 0) + 1

    if not tag_counter:
        return empty

    tag_list = [{"name": k, "count": str(v)} for k, v in tag_counter.items()]
    genre_str = _best_genre_from_tags(tag_list)

    return {"genre": genre_str, "artist": None, "title": None}


def fingerprint_file(filepath: Path, api_key: str) -> dict:
    """Identify an MP3 via audio fingerprint. Returns {genre, artist, title} or empty dict.

    Requires: pyacoustid, musicbrainzngs, and the fpcalc binary in PATH.
    """
    empty: dict = {"genre": None, "artist": None, "title": None}

    if not _ACOUSTID_AVAILABLE:
        _warn_once(
            "acoustid",
            "pyacoustid not installed — fingerprinting disabled. "
            "Install with: pip install pyacoustid",
        )
        return empty

    if not _MB_AVAILABLE:
        _warn_once("mb_missing", "musicbrainzngs not installed — fingerprinting disabled.")
        return empty

    if not shutil.which("fpcalc"):
        _warn_once(
            "fpcalc",
            "fpcalc not found in PATH — fingerprinting disabled. "
            "Install Chromaprint: https://acoustid.org/chromaprint",
        )
        return empty

    try:
        results = list(acoustid.match_file(api_key, str(filepath)))
    except acoustid.WebServiceError as e:
        print(f"WARNING: AcoustID API error for {filepath.name}: {e}", file=sys.stderr)
        return empty
    except Exception as e:
        print(f"WARNING: fingerprint failed for {filepath.name}: {e}", file=sys.stderr)
        return empty

    candidates = [
        (score, rid, title, artist)
        for score, rid, title, artist in results
        if score >= SCORE_THRESHOLD
    ]
    if not candidates:
        return empty

    score, recording_id, mb_title, mb_artist = candidates[0]

    try:
        rec = musicbrainzngs.get_recording_by_id(
            recording_id, includes=["tags", "artist-credits"]
        )
        return _extract_mb_recording(rec.get("recording", {}), mb_title, mb_artist)
    except Exception as e:
        print(f"WARNING: MusicBrainz lookup failed for {filepath.name}: {e}", file=sys.stderr)
        return {"genre": None, "artist": mb_artist, "title": mb_title}


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------

def is_already_sorted(filepath: Path, folder_name: str, destination: Path) -> bool:
    """Return True if filepath is already inside destination/folder_name."""
    try:
        return filepath.parent.resolve() == (destination / folder_name).resolve()
    except OSError:
        return False


def resolve_conflict(dest_path: Path) -> Path:
    """Return dest_path if it doesn't exist, otherwise append _2, _3, etc."""
    if not dest_path.exists():
        return dest_path
    stem = dest_path.stem
    suffix = dest_path.suffix
    parent = dest_path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def process_file(
    filepath: Path,
    destination: Path,
    dry_run: bool,
    copy: bool,
    no_rename: bool,
    acoustid_key: str | None,
    verify: bool = False,
    discogs_token: str | None = None,
) -> tuple[str, str]:
    """Process a single MP3 file: detect genre, rename, move/copy.

    Returns (folder_name, action) where action is one of:
    'moved', 'copied', 'skipped', 'dry_run', 'error'
    """
    # --- Step 1: Read ID3 metadata ---
    meta = get_id3_metadata(filepath)
    raw_genre = meta["genre"]
    id3_artist = meta["artist"]
    id3_title = meta["title"]

    # --- Step 2: Detect genre from ID3 tag ---
    folder: str | None = None
    if raw_genre:
        normalized = normalize_genre(raw_genre)
        folder = detect_genre(normalized)

    # --- Step 2b: Verify ID3 genre against MusicBrainz (--verify) ---
    if verify and folder is not None and _MB_AVAILABLE:
        v_artist = id3_artist or parse_filename(filepath.stem)[0]
        v_title = id3_title or parse_filename(filepath.stem)[1]
        if v_artist and v_artist != "Unknown" and v_title:
            web = lookup_by_metadata(v_artist, v_title, filepath.name)
            web_folder = detect_genre(normalize_genre(web["genre"])) if web.get("genre") else None
            if web_folder and web_folder != folder:
                print(
                    f"[CORRECTED] {filepath.name}: "
                    f"{folder!r} (ID3:'{raw_genre}') -> {web_folder!r} (web:'{web['genre']}')"
                )
                folder = web_folder
            elif web_folder:
                print(f"[VERIFY OK] {filepath.name}: {folder!r} confirmed by MusicBrainz")
            else:
                print(f"[VERIFY] {filepath.name}: {folder!r} (MusicBrainz returned no genre)")

    # --- Step 3a: MusicBrainz text lookup for unknown genre ---
    fp_artist: str | None = None
    fp_title: str | None = None
    if folder is None and _MB_AVAILABLE:
        # Resolve artist+title for the search query
        lookup_artist = id3_artist
        lookup_title = id3_title
        if not lookup_artist or not lookup_title:
            pa, pt = parse_filename(filepath.stem)
            lookup_artist = lookup_artist or pa
            lookup_title = lookup_title or pt

        if lookup_artist and lookup_artist != "Unknown" and lookup_title:
            web_data = lookup_by_metadata(lookup_artist, lookup_title, filepath.name)
            if web_data.get("genre"):
                found = detect_genre(normalize_genre(web_data["genre"]))
                if found:
                    folder = found
                    print(f"[WEB] {filepath.name}: genre '{web_data['genre']}' -> {folder!r}")

    # --- Step 3b: Discogs lookup — fires for unknown genre OR generic Electronic ---
    # Discogs `style` field provides specific subgenres (e.g. 'Deep House') that
    # MusicBrainz tags often lack. Not used in --verify to avoid false positives
    # from remix releases.
    if folder is None or folder == "Electronic":
        disc_artist = id3_artist
        disc_title = id3_title
        if not disc_artist or not disc_title:
            pa, pt = parse_filename(filepath.stem)
            disc_artist = disc_artist or pa
            disc_title = disc_title or pt

        if disc_artist and disc_artist != "Unknown" and disc_title:
            disc_data = lookup_by_discogs(disc_artist, disc_title, discogs_token, filepath.name)
            if disc_data.get("genre"):
                found = detect_genre(normalize_genre(disc_data["genre"]))
                # Only upgrade if we get a more specific result (never downgrade to Electronic)
                if found and found != "Electronic" and found != folder:
                    print(f"[DISCOGS] {filepath.name}: genre '{disc_data['genre']}' -> {found!r}")
                    folder = found

    # --- Step 3d: Audio fingerprint fallback (needs fpcalc + AcoustID key) ---
    if folder is None and acoustid_key:
        fp_data = fingerprint_file(filepath, acoustid_key)
        if fp_data.get("genre"):
            folder = detect_genre(normalize_genre(fp_data["genre"]))
        fp_artist = fp_data.get("artist")
        fp_title = fp_data.get("title")

    # --- Step 4: Final folder ---
    if folder is None:
        folder = "_Unknown"

    # --- Step 5: Already-sorted check ---
    if is_already_sorted(filepath, folder, destination):
        return folder, "skipped"

    # --- Step 6: Determine target filename ---
    if no_rename:
        target_name = filepath.name
        final_artist: str | None = None
        final_title: str | None = None
    else:
        # Resolve artist and title
        artist = id3_artist or fp_artist
        title = id3_title or fp_title

        if not artist or not title:
            parsed_artist, parsed_title = parse_filename(filepath.stem)
            artist = artist or parsed_artist
            title = title or parsed_title

        # Extract version suffix from title before title-casing
        clean_title, version = extract_version(title)

        # Apply full normalization (used for both filename and tag write-back)
        final_artist = sanitize(smart_title_case(normalize_artists(artist)))
        final_title = sanitize(smart_title_case(clean_title))
        target_name = build_normalized_filename(artist, clean_title, version)

    # --- Step 7: Destination path ---
    genre_dir = destination / folder
    dest_path = resolve_conflict(genre_dir / target_name)

    # --- Step 8: Dry run ---
    if dry_run:
        verb = "COPY" if copy else "MOVE"
        print(f"[DRY RUN] {verb}: {filepath.name!r}  ->  {dest_path.relative_to(destination)}")
        return folder, "dry_run"

    # --- Step 9: Execute file operation ---
    try:
        genre_dir.mkdir(parents=True, exist_ok=True)
        if copy:
            shutil.copy2(filepath, dest_path)
        else:
            shutil.move(str(filepath), dest_path)
    except OSError as e:
        print(f"ERROR: could not {'copy' if copy else 'move'} {filepath.name}: {e}", file=sys.stderr)
        return "_Error", "error"

    # --- Step 10: Write back normalized tags ---
    if not no_rename and final_artist and final_title:
        write_id3_metadata(dest_path, final_artist, final_title)

    return folder, "copied" if copy else "moved"


# ---------------------------------------------------------------------------
# Scanning and summary
# ---------------------------------------------------------------------------

def scan_files(source: Path) -> list[Path]:
    """Recursively find all MP3 files under source (case-insensitive suffix)."""
    return sorted(p for p in source.rglob("*") if p.suffix.lower() == ".mp3" and p.is_file())


def print_summary(results: dict[str, int]) -> None:
    """Print an aligned table of genre folder counts."""
    unknown = results.pop("_Unknown", 0)
    skipped = results.pop("_Skipped", 0)
    errored = results.pop("_Error", 0)
    total = sum(results.values()) + unknown

    col1, col2 = 26, 6
    sep = f"  {'-' * col1}  {'-' * col2}"

    print()
    print("  Sort Summary")
    print(sep)
    print(f"  {'Genre Folder':<{col1}}  {'Files':>{col2}}")
    print(sep)
    for folder in sorted(results):
        print(f"  {folder:<{col1}}  {results[folder]:>{col2}}")
    print(sep)
    if unknown:
        print(f"  {'_Unknown':<{col1}}  {unknown:>{col2}}")
    if skipped:
        print(f"  {'Skipped (already sorted)':<{col1}}  {skipped:>{col2}}")
    if errored:
        print(f"  {'Errors':<{col1}}  {errored:>{col2}}")
    print(sep)
    print(f"  {'TOTAL':<{col1}}  {total:>{col2}}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sort_music",
        description="Organize MP3 files into genre folders with filename normalization.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "The ACOUSTID_API_KEY environment variable can be used instead of --acoustid-key.\n"
            "The DISCOGS_TOKEN environment variable can be used instead of --discogs-token.\n"
            "Get a free Discogs token at: https://www.discogs.com/settings/developers\n\n"
            "Examples:\n"
            "  sort_music /music/unsorted /music/sorted\n"
            "  sort_music /music --dry-run\n"
            "  sort_music /music --copy --no-rename\n"
        ),
    )
    parser.add_argument("source", type=Path, help="Source folder to scan recursively for MP3s")
    parser.add_argument(
        "destination",
        type=Path,
        nargs="?",
        default=Path("./Sorted"),
        help="Destination root folder (default: ./Sorted)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without moving or renaming any files",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy files instead of moving them",
    )
    parser.add_argument(
        "--no-rename",
        action="store_true",
        help="Skip filename normalization; only sort into genre folders",
    )
    parser.add_argument(
        "--acoustid-key",
        metavar="KEY",
        default=None,
        help="AcoustID API key for fingerprint fallback (or set ACOUSTID_API_KEY env var)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help=(
            "Cross-check each file's ID3 genre against MusicBrainz and warn on mismatches. "
            "The ID3 genre is still used for sorting; this is informational only."
        ),
    )
    parser.add_argument(
        "--discogs-token",
        metavar="TOKEN",
        default=None,
        help=(
            "Discogs personal access token for genre lookup. "
            "Used to resolve unknown genres and upgrade generic 'Electronic' to a specific subgenre. "
            "Unauthenticated requests are allowed but rate-limited (25/min). "
            "Or set the DISCOGS_TOKEN environment variable."
        ),
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    # Validate source
    if not args.source.is_dir():
        print(f"ERROR: source '{args.source}' is not a directory or does not exist.", file=sys.stderr)
        sys.exit(1)

    # Verify mutagen is available early
    try:
        import mutagen  # noqa: F401
    except ImportError:
        print("ERROR: mutagen is required. Install it with: pip install mutagen", file=sys.stderr)
        sys.exit(1)

    # Resolve AcoustID key (only needed for audio fingerprinting, not for web text lookup)
    acoustid_key: str | None = args.acoustid_key or os.environ.get("ACOUSTID_API_KEY")

    # Resolve Discogs token (optional; unauthenticated requests are allowed but rate-limited)
    discogs_token: str | None = args.discogs_token or os.environ.get("DISCOGS_TOKEN")

    destination = args.destination.resolve()

    # Scan
    files = scan_files(args.source)
    if not files:
        print(f"No MP3 files found in '{args.source}'.")
        return

    verb = "Scanning" if args.dry_run else ("Copying" if args.copy else "Sorting")
    print(f"{verb} {len(files)} file(s) from '{args.source}'...")
    if args.dry_run:
        print("(dry run — no files will be moved)\n")

    # Process
    results: dict[str, int] = defaultdict(int)
    for filepath in files:
        folder, action = process_file(
            filepath,
            destination,
            dry_run=args.dry_run,
            copy=args.copy,
            no_rename=args.no_rename,
            acoustid_key=acoustid_key,
            verify=args.verify,
            discogs_token=discogs_token,
        )
        if action == "skipped":
            results["_Skipped"] += 1
        elif action == "error":
            results["_Error"] += 1
        else:
            results[folder] += 1

    print_summary(dict(results))


if __name__ == "__main__":
    main()
