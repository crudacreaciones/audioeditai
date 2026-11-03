"""Tag reading/writing via mutagen, with ffprobe tags as fallback."""
from __future__ import annotations

import os
import re
from pathlib import Path

try:
    import mutagen
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3NoHeaderError
except ImportError:  # pragma: no cover - mutagen is a hard requirement but keep import errors readable
    mutagen = None

EDITABLE_FIELDS = ("title", "artist", "album", "album_artist", "genre", "year", "track_no")

# app field -> (mutagen easy key, ffprobe tag keys)
_FIELD_MAP = {
    "title": ("title", ("title",)),
    "artist": ("artist", ("artist", "author")),
    "album": ("album", ("album",)),
    "album_artist": ("albumartist", ("album_artist", "albumartist", "album artist")),
    "genre": ("genre", ("genre",)),
    "year": ("date", ("date", "year", "icrd")),
    "track_no": ("tracknumber", ("track", "tracknumber")),
}


def _first(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ""
    return str(v).strip()


def guess_from_filename(path: str | os.PathLike) -> dict:
    """'Artist - Title.mp3' or '01 - Title.mp3' fallbacks."""
    stem = Path(path).stem
    stem = re.sub(r"[_]+", " ", stem).strip()
    out = {}
    m = re.match(r"^(\d{1,3})[\s.\-]+(.+)$", stem)
    if m:
        out["track_no"] = m.group(1)
        stem = m.group(2).strip()
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        out["artist"], out["title"] = artist.strip(), title.strip()
    else:
        out["title"] = stem
    return out


def read_tags(path: str | os.PathLike, ffprobe_tags: dict | None = None) -> dict:
    tags = {f: "" for f in EDITABLE_FIELDS}
    if mutagen is not None:
        try:
            mf = mutagen.File(str(path), easy=True)
            if mf is not None and mf.tags is not None:
                for field, (easy_key, _) in _FIELD_MAP.items():
                    try:
                        tags[field] = _first(mf.tags.get(easy_key))
                    except (KeyError, ValueError):
                        pass
        except Exception:  # corrupt tag blocks must not abort the import
            pass
    if ffprobe_tags:
        for field, (_, keys) in _FIELD_MAP.items():
            if not tags[field]:
                for k in keys:
                    if ffprobe_tags.get(k):
                        tags[field] = str(ffprobe_tags[k]).strip()
                        break
    if not tags["title"] or not tags["artist"]:
        guess = guess_from_filename(path)
        for k, v in guess.items():
            if not tags.get(k):
                tags[k] = v
    tags["track_no"] = tags["track_no"].split("/")[0].strip()
    tags["year"] = tags["year"][:4] if re.match(r"^\d{4}", tags["year"]) else tags["year"]
    return tags


def write_tags(path: str | os.PathLike, values: dict) -> None:
    """Write editable fields into the audio file's own tags."""
    if mutagen is None:
        raise RuntimeError("mutagen no está instalado")
    path = str(path)
    ext = Path(path).suffix.lower()
    if ext == ".mp3":
        try:
            audio = EasyID3(path)
        except ID3NoHeaderError:
            audio = mutagen.File(path, easy=True)
            audio.add_tags()
            audio = EasyID3(path)
    elif ext == ".wav":
        from mutagen.wave import WAVE
        audio = WAVE(path)
        if audio.tags is None:
            audio.add_tags()
        from mutagen.id3 import TIT2, TPE1, TALB, TPE2, TCON, TDRC, TRCK
        frames = {"title": TIT2, "artist": TPE1, "album": TALB, "album_artist": TPE2,
                  "genre": TCON, "year": TDRC, "track_no": TRCK}
        for field, cls in frames.items():
            if field in values:
                audio.tags.delall(cls.__name__)
                if values[field]:
                    audio.tags.add(cls(encoding=3, text=str(values[field])))
        audio.save()
        return
    else:
        audio = mutagen.File(path, easy=True)
        if audio is None:
            raise RuntimeError("Formato no soportado para escribir etiquetas")
        if audio.tags is None:
            audio.add_tags()
    for field, (easy_key, _) in _FIELD_MAP.items():
        if field not in values:
            continue
        val = str(values[field] or "")
        try:
            if val:
                audio[easy_key] = [val]
            elif easy_key in audio:
                del audio[easy_key]
        except (KeyError, ValueError):
            # Some containers (e.g. MP4) lack a mapping for certain keys
            continue
    audio.save()
