import pytest

from wavify.matching import match, parse_version
from wavify.providers import licenses
from wavify.providers.base import Candidate, TrackQuery
from wavify.spotify import LinkError, parse_link

ID = "4uLU6hMCjMI75M1A2tKUQC"


@pytest.mark.parametrize("text", [
    f"https://open.spotify.com/track/{ID}",
    f"https://open.spotify.com/track/{ID}?si=abc123&context=x",
    f"https://open.spotify.com/intl-es/track/{ID}",
    f"https://open.spotify.com/intl-pt-BR/track/{ID}",
    f"open.spotify.com/track/{ID}",
    f"  spotify:track:{ID}  ",
    f"https://open.spotify.com/embed/track/{ID}",
])
def test_valid_track_links(text):
    link = parse_link(text)
    assert link.kind == "track" and link.id == ID


def test_short_link_detected():
    link = parse_link("https://spotify.link/abc123")
    assert link.needs_resolution and link.short_url == "https://spotify.link/abc123"


@pytest.mark.parametrize("text,fragment", [
    ("", "Pega un enlace"),
    ("hola que tal", "Solo se admiten enlaces de Spotify"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "Solo se admiten"),
    (f"https://open.spotify.com.evil.com/track/{ID}", "Solo se admiten"),
    (f"https://open.spotify.com/album/{ID}", "un álbum"),
    (f"https://open.spotify.com/playlist/{ID}", "una playlist"),
    (f"spotify:episode:{ID}", "episodio"),
    ("https://open.spotify.com/track/123", "No se reconoce"),
    ("https://open.spotify.com/track/" + "a" * 600, "demasiado largo"),
])
def test_invalid_links(text, fragment):
    with pytest.raises(LinkError) as e:
        parse_link(text)
    assert fragment in str(e.value)


# ---------------------------------------------------------------------------
def q(title="Luz de Mañana", artists=("Aurora Libre",), album="Cielos Abiertos", duration=200.0, isrc=""):
    return TrackQuery(title=title, artists=list(artists), album=album, duration=duration, isrc=isrc)


def c(title="Luz de Mañana", artist="Aurora Libre", album="Cielos Abiertos", duration=200.5, isrc=""):
    return Candidate(provider="x", id="1", title=title, artist=artist, album=album, duration=duration, isrc=isrc)


def test_exact_match():
    m = match(q(), c())
    assert m.verified and m.score >= 0.95


def test_accents_case_and_feat_are_tolerated():
    assert match(q(title="Luz de Mañana (feat. Otro)"), c(title="LUZ DE MANANA", artist="aurora libre")).verified
    assert match(q(artists=("Aurora Libre", "Otro")), c(artist="Aurora Libre & Otro")).verified


@pytest.mark.parametrize("cand_title,label", [
    ("Luz de Mañana (Live)", "directo"), ("Luz de Mañana - Remastered 2020", "Remasterización"),
    ("Luz de Mañana (Club Remix)", "Remix"), ("Luz de Mañana (Instrumental)", "Instrumental"),
    ("Luz de Mañana (Acoustic Version)", "Otra versión"), ("Luz de Mañana (Karaoke Version)", "Cover"),
])
def test_other_versions_are_rejected(cand_title, label):
    m = match(q(), c(title=cand_title))
    assert not m.verified and any(label.lower() in r.lower() for r in m.reasons), m.reasons


def test_remaster_requested_matches_remaster():
    assert match(q(title="Luz - 2011 Remaster"), c(title="Luz (Remastered 2011)")).verified


def test_cover_by_other_artist_rejected():
    m = match(q(), c(artist="Banda Tributo"))
    assert not m.verified and "Otro artista o intérprete" in m.reasons


def test_similar_title_only_is_not_enough():
    assert not match(q(), c(title="Luz de Medianoche")).verified
    assert not match(q(title="Love"), c(title="Lover", artist="Aurora Libre")).verified


def test_duration_rules():
    assert not match(q(), c(duration=215)).verified          # 15 s off
    assert match(q(), c(duration=202.5)).verified             # within 3 s
    m = match(q(), c(duration=None))
    assert not m.verified and "duración" in m.reasons[0]


def test_isrc_is_decisive():
    assert match(q(isrc="ESA012300001"), c(title="Totally different", isrc="esa012300001")).verified
    m = match(q(isrc="ESA012300001"), c(isrc="USX000000001"))
    assert not m.verified and "ISRC distinto" in m.reasons[0]


def test_parse_version_neutral_descriptors():
    assert parse_version("Song - Original Mix") == ("song", "original")
    assert parse_version("Song (Single Version)") == ("song", "original")
    assert parse_version("Canción (En Directo)")[1] == "live"


# ---------------------------------------------------------------------------
def test_licenses():
    by = licenses.from_url("http://creativecommons.org/licenses/by-nc-nd/3.0/")
    assert by.allows_download and by.allows_conversion and by.requires_attribution and "no comercial" in by.notes
    assert by.url.startswith("https://") and by.name == "CC BY-NC-ND 3.0"
    assert licenses.from_url("https://creativecommons.org/publicdomain/zero/1.0/").allows_download
    assert licenses.from_url("http://creativecommons.org/publicdomain/mark/1.0/").allows_download
    assert not licenses.from_url("").allows_download
    assert not licenses.from_url("https://example.com/all-rights-reserved").allows_download
