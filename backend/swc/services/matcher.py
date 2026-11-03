"""Match local library tracks with Spotify tracks (title/artist similarity + duration)."""
from __future__ import annotations

from difflib import SequenceMatcher

from ..db import Database
from ..oplog import OpLog
from .library import normalize

THRESHOLD = 0.78


def _sim(a: str, b: str) -> float:
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    jacc = len(ta & tb) / len(ta | tb)
    contained = 0.9 if (a in b or b in a) else 0.0
    return max(ratio, jacc, contained)


def _artist_sim(local: str, spotify_artists: str) -> float:
    if not local:
        return 0.5  # unknown artist: neutral
    candidates = [x.strip() for x in spotify_artists.split(",") if x.strip()] + [spotify_artists]
    return max(_sim(local, c) for c in candidates)


def score(local: dict, sp: dict) -> float:
    title = _sim(local.get("title", ""), sp.get("name", ""))
    artist = _artist_sim(local.get("artist", ""), sp.get("artists", ""))
    s = 0.6 * title + 0.4 * artist
    ld, sd = float(local.get("duration") or 0), (sp.get("duration_ms") or 0) / 1000
    if ld and sd:
        diff = abs(ld - sd)
        if diff <= 3:
            s += 0.05
        elif diff > 15:
            s -= min(0.3, diff / 200)
    return round(max(0.0, min(1.0, s)), 3)


class Matcher:
    def __init__(self, db: Database, log: OpLog):
        self.db, self.log = db, log

    def candidates_for_spotify(self, spotify_id: str, limit: int = 5) -> list[dict]:
        sp = self.db.query_one("SELECT * FROM spotify_tracks WHERE id=?", (spotify_id,))
        if not sp:
            return []
        scored = [{**t, "score": score(t, sp)} for t in self.db.query("SELECT * FROM tracks")]
        scored.sort(key=lambda t: t["score"], reverse=True)
        return [t for t in scored[:limit] if t["score"] > 0.3]

    def auto_match(self, threshold: float = THRESHOLD) -> dict:
        """Link each unlinked work-list Spotify track with its best local candidate (1:1)."""
        sp_tracks = self.db.query(
            "SELECT * FROM spotify_tracks s WHERE in_worklist=1 AND NOT EXISTS "
            "(SELECT 1 FROM tracks t WHERE t.spotify_id=s.id)")
        local = self.db.query("SELECT * FROM tracks WHERE spotify_id IS NULL")
        pairs = []
        for sp in sp_tracks:
            for t in local:
                sc = score(t, sp)
                if sc >= threshold:
                    pairs.append((sc, sp["id"], t["id"]))
        pairs.sort(reverse=True)
        used_sp, used_local, linked = set(), set(), []
        for sc, sid, tid in pairs:
            if sid in used_sp or tid in used_local:
                continue
            used_sp.add(sid)
            used_local.add(tid)
            self.db.execute("UPDATE tracks SET spotify_id=?, match_score=? WHERE id=?", (sid, sc, tid))
            linked.append({"spotify_id": sid, "track_id": tid, "score": sc})
        self.log.info("match", f"Asociación automática: {len(linked)} coincidencias",
                      {"pendientes": len(sp_tracks) - len(linked)})
        return {"linked": linked, "unmatched": len(sp_tracks) - len(linked)}
