"""Strict recording identification: is this candidate *the same recording* as the Spotify track?

A similar title is never enough. Automatic selection requires, without an ISRC match:
  same version type (original / remaster / live / remix / instrumental / cover / other),
  title similarity >= 0.92, main-artist similarity >= 0.85, a known duration within max(3 s, 2 %),
  and an overall score >= 0.85.
An equal ISRC is a definitive match; a different ISRC is a definitive rejection.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

VERSIONS = ("original", "remaster", "live", "remix", "instrumental", "cover", "other")
VERSION_LABELS = {
    "original": "Grabación original", "remaster": "Remasterización", "live": "Versión en directo",
    "remix": "Remix", "instrumental": "Instrumental", "cover": "Cover / otra interpretación", "other": "Otra versión",
}
# checked in priority order
_VERSION_PATTERNS = [
    ("cover", r"\bcover\b|\btribute\b|originally performed|in the style of|\bkaraoke\b"),
    ("live", r"\blive\b|\ben vivo\b|\ben directo\b|\bdirecto\b|\bunplugged\b|\bao vivo\b"),
    ("remix", r"\bremix(ed)?\b|\brmx\b|\brework\b|\bbootleg\b|\bdub\b|(?<!original )\bmix\b"),
    ("instrumental", r"\binstrumental\b"),
    ("other", r"\bacoustic\b|\bacustic[oa]\b|\bdemo\b|\bradio edit\b|\bextended\b|\bedit\b|\bsped up\b|\bslowed\b"
              r"|\breprise\b|\bmono\b|\bre-?recorded\b|\btaylor'?s version\b"),
    ("remaster", r"\bremaster(ed)?\b|\bremasterizad[oa]\b"),
]
_FEAT = re.compile(r"\b(feat\.?|ft\.?|featuring|with|con)\b", re.I)

THRESHOLD = 0.85
TITLE_MIN = 0.92
ARTIST_MIN = 0.85


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def parse_version(title: str) -> tuple[str, str]:
    """Return (base title without version/feat descriptors, version type)."""
    title = title or ""
    parts = re.findall(r"[\(\[]([^\)\]]*)[\)\]]", title)
    base = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", title)
    if " - " in base:
        base, *suffixes = base.split(" - ")
        parts += suffixes
    base = _FEAT.split(base)[0]
    descriptors = " | ".join(parts)
    descriptors = unicodedata.normalize("NFKD", descriptors).encode("ascii", "ignore").decode().lower()
    # neutral descriptors that do not denote a different recording
    descriptors = re.sub(r"\b(original|album|single|lp) (mix|version|edit)\b", " ", descriptors)
    for version, pattern in _VERSION_PATTERNS:
        if re.search(pattern, descriptors, re.I):
            return normalize(base), version
    return normalize(base), "original"


def _sim(a: str, b: str) -> float:
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _split_artists(s: str) -> list[str]:
    return [x.strip() for x in re.split(r",|;|/|&|\band\b|\by\b|\bx\b|\bfeat\.?|\bft\.?|\bfeaturing\b|\bwith\b",
                                        s or "", flags=re.I) if x.strip()]


def artist_similarity(candidate_artist: str, spotify_artists: list[str]) -> float:
    if not candidate_artist or not spotify_artists:
        return 0.0
    cand = [candidate_artist] + _split_artists(candidate_artist)
    main = spotify_artists[0]
    best_main = max(_sim(c, main) for c in cand)
    best_any = max(_sim(c, a) for c in cand for a in spotify_artists)
    # the main artist matters most; a featured artist alone is weaker evidence
    return max(best_main, 0.9 * best_any)


@dataclass
class MatchResult:
    score: float
    verified: bool
    reasons: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def match(track, cand) -> MatchResult:
    """`track`: TrackQuery-like (title, artists, album, duration, isrc). `cand`: Candidate-like."""
    t_base, t_ver = parse_version(track.title)
    c_base, c_ver = parse_version(cand.title)
    title_sim = 1.0 if t_base and t_base == c_base else _sim(t_base, c_base)
    art_sim = artist_similarity(cand.artist, track.artists)
    album_sim = _sim(track.album, cand.album) if (track.album and cand.album) else None
    diff = abs(track.duration - cand.duration) if (track.duration and cand.duration) else None
    details = {"title_similarity": round(title_sim, 3), "artist_similarity": round(art_sim, 3),
               "album_similarity": None if album_sim is None else round(album_sim, 3),
               "duration_diff": None if diff is None else round(diff, 2),
               "version_spotify": t_ver, "version_candidate": c_ver, "isrc_match": None}

    if track.isrc and cand.isrc:
        same = track.isrc.strip().upper() == cand.isrc.strip().upper()
        details["isrc_match"] = same
        if same:
            return MatchResult(1.0, True, ["ISRC idéntico"], details)
        return MatchResult(0.0, False, ["ISRC distinto: es otra grabación"], details)

    dur_score = 0.0 if diff is None else max(0.0, 1.0 - max(0.0, diff - 1.0) / 9.0)
    score = 0.40 * title_sim + 0.30 * art_sim + 0.20 * dur_score + 0.10 * (0.5 if album_sim is None else album_sim)
    if t_ver != c_ver:
        score *= 0.5
    score = round(min(1.0, score), 3)

    reasons = []
    if t_ver != c_ver:
        reasons.append(f"Versión distinta: {VERSION_LABELS[c_ver]} (se busca: {VERSION_LABELS[t_ver]})")
    if title_sim < TITLE_MIN:
        reasons.append("El título no coincide")
    if art_sim < ARTIST_MIN:
        reasons.append("Otro artista o intérprete" if title_sim >= TITLE_MIN else "El artista no coincide")
    if diff is None:
        reasons.append("La fuente no indica la duración: no se puede verificar la grabación")
    elif diff > max(3.0, 0.02 * track.duration):
        reasons.append(f"Duración distinta ({diff:.0f} s de diferencia)")
    if not reasons and score < THRESHOLD:
        reasons.append("Puntuación de coincidencia insuficiente")
    verified = not reasons
    return MatchResult(score, verified, reasons or ["Título, artista, versión y duración coinciden"], details)


def quality_rank(c) -> tuple:
    return (1 if c.lossless else 0, c.bitrate_kbps or 0)
