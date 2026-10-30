"""normalize: month selection, near-duplicate clustering, press-release tags, entities."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

from . import store
from .config import load
from .util import kst_date, month_bounds, url_key


@dataclass
class Cluster:
    cid: str
    docs: list[dict] = field(default_factory=list)

    @property
    def rep(self) -> dict:
        """Representative: official/article grade with body, then earliest."""
        grade = {"official": 0, "article": 1, "headline": 2}
        return sorted(self.docs, key=lambda d: (grade.get(d.get("evidence_grade"), 3),
                                                not d.get("had_body"),
                                                d.get("published_at") or ""))[0]

    @property
    def sources(self) -> set[str]:
        return {d["source"] for d in self.docs}

    @property
    def press_release(self) -> bool:
        return any(d["extraction"].get("is_press_release") for d in self.docs)


def _grams(s: str) -> set[str]:
    s = re.sub(r"[\W_]+", "", s.lower())
    return {s[i:i + 2] for i in range(len(s) - 1)}


def similar(a: str, b: str, threshold: float = 0.5) -> bool:
    ga, gb = _grams(a), _grams(b)
    if not ga or not gb:
        return False
    return len(ga & gb) / len(ga | gb) >= threshold


def load_month(ym: str, relevant_only: bool = True) -> list[dict]:
    first, last = month_bounds(ym)
    out, seen = [], set()
    for p in sorted((store.data_dir() / "enriched").glob("*/*.json")):
        rec = store.read_json(p)
        d = kst_date(rec.get("published_at"))
        if d is None or not (first <= d <= last):
            continue
        if relevant_only and not rec["extraction"].get("relevant"):
            continue
        # the same article stored under two ids (http and https links, before collect compared
        # url_key) would count twice, e.g. pass the two-article rule for events on its own
        k = url_key(rec.get("url") or rec["doc_id"])
        if k in seen:
            continue
        seen.add(k)
        out.append(rec)
    return out


def cluster(docs: list[dict], days: int = 3) -> list[Cluster]:
    """Greedy single-pass clustering on title bigram Jaccard within ±days."""
    clusters: list[Cluster] = []
    for d in sorted(docs, key=lambda x: x.get("published_at") or ""):
        dd = kst_date(d.get("published_at"))
        for c in clusters:
            r = c.docs[0]
            rd = kst_date(r.get("published_at"))
            if dd and rd and abs(dd - rd) <= timedelta(days=days) and similar(d["title"], r["title"]):
                c.docs.append(d)
                break
        else:
            clusters.append(Cluster(f"c{len(clusters):04d}", [d]))
    return clusters


class Entities:
    def __init__(self):
        cfg = load("entities")
        self.alias: dict[str, str] = {}
        self.parent: dict[str, str] = {}
        for kind in ("brands", "companies"):
            for name, v in (cfg.get(kind) or {}).items():
                self.alias[self._key(name)] = name
                for a in v.get("aliases", []):
                    self.alias[self._key(a)] = name
                if v.get("parent"):
                    self.parent[name] = v["parent"]

    @staticmethod
    def _key(s: str) -> str:
        return re.sub(r"[\s·\-_.]+", "", s).lower()

    def canon(self, name: str) -> str:
        return self.alias.get(self._key(name), name.strip())

    def variants(self, name: str) -> set[str]:
        """All spellings of the entity behind `name` (Korean/English aliases)."""
        c = self.canon(name)
        cfg = load("entities")
        out = {name, c}
        for kind in ("brands", "companies"):
            v = (cfg.get(kind) or {}).get(c)
            if v:
                out.update(v.get("aliases", []))
        return {x for x in out if x}
