"""Graph access layer.

Two interchangeable stores expose the same `run(template_id, params)` call:

* Neo4jStore      - executes the Cypher template against a live Neo4j
                    (AuraDB / Desktop) instance through the official driver.
* LocalGraphStore - an in-memory replica of the Neo4j Movies graph built from
                    data/movies.json. Each Cypher template has a Python twin
                    that returns rows with exactly the same columns, so the
                    rest of the pipeline cannot tell the two apart.

`get_store()` picks Neo4j when NEO4J_URI/NEO4J_USERNAME/NEO4J_PASSWORD are set
and reachable, otherwise it falls back to the local replica.
"""
from __future__ import annotations

import json
import os
import pathlib
from collections import defaultdict, deque

from .templates import TEMPLATES, CREW_TYPES

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "movies.json"


class LocalGraphStore:
    backend = "local"
    label = "In-memory Movies graph (offline replica)"

    def __init__(self, path: pathlib.Path = DATA):
        d = json.loads(path.read_text(encoding="utf-8"))
        self.movies = {m["title"]: m for m in d["movies"]}
        self.people = {p["name"]: p for p in d["people"]}
        self.rels = d["relationships"]
        self.out = defaultdict(list)   # src -> [rel]
        self.inc = defaultdict(list)   # dst -> [rel]
        for r in self.rels:
            self.out[r["src"]].append(r)
            self.inc[r["dst"]].append(r)

    # ------------------------------------------------------------- helpers
    def schema(self):
        counts = defaultdict(int)
        for r in self.rels:
            counts[r["type"]] += 1
        return {"nodes": {"Movie": len(self.movies), "Person": len(self.people)},
                "relationships": dict(counts)}

    def entity_names(self):
        return list(self.movies), list(self.people)

    def _in(self, title, types):
        return [r for r in self.inc.get(title, []) if r["type"] in types]

    def _out(self, name, types):
        return [r for r in self.out.get(name, []) if r["type"] in types]

    def close(self):
        pass

    # ------------------------------------------------------------- templates
    def run(self, tid: str, p: dict) -> list[dict]:
        return getattr(self, "t_" + tid)(**p)

    def t_movie_info(self, title):
        m = self.movies.get(title)
        if not m:
            return []
        names = lambda t: sorted(r["src"] for r in self._in(title, {t}))
        return [{
            "title": m["title"], "released": m.get("released"), "tagline": m.get("tagline"),
            "directors": names("DIRECTED"), "writers": names("WROTE"), "producers": names("PRODUCED"),
            "cast": [{"name": r["src"], "roles": r["props"].get("roles", [])}
                     for r in self._in(title, {"ACTED_IN"})],
        }]

    def t_movie_cast(self, title):
        rows = [{"actor": r["src"], "roles": r["props"].get("roles", []),
                 "born": self.people[r["src"]].get("born")}
                for r in self._in(title, {"ACTED_IN"})]
        return sorted(rows, key=lambda x: x["actor"])

    def t_movie_crew(self, title, rel_types):
        rows = [{"person": r["src"], "relation": r["type"]} for r in self._in(title, set(rel_types))]
        return sorted(rows, key=lambda x: (x["relation"], x["person"]))

    def t_person_filmography(self, name, rel_types):
        rows = [{"title": r["dst"], "released": self.movies[r["dst"]].get("released"),
                 "relation": r["type"], "roles": r["props"].get("roles")}
                for r in self._out(name, set(rel_types)) if r["dst_label"] == "Movie"]
        return sorted(rows, key=lambda x: (x["released"] or 0, x["title"]))

    def t_person_info(self, name):
        p = self.people.get(name)
        if not p:
            return []
        titles = lambda t: [r["dst"] for r in self._out(name, {t})]
        return [{"name": name, "born": p.get("born"), "acted_in": titles("ACTED_IN"),
                 "directed": titles("DIRECTED"), "wrote": titles("WROTE"),
                 "produced": titles("PRODUCED")}]

    def t_co_actors(self, name):
        shared = defaultdict(list)
        for r in self._out(name, {"ACTED_IN"}):
            for r2 in self._in(r["dst"], {"ACTED_IN"}):
                if r2["src"] != name:
                    shared[r2["src"]].append(r["dst"])
        rows = [{"coactor": c, "movies": ms, "shared": len(ms)} for c, ms in shared.items()]
        return sorted(rows, key=lambda x: (-x["shared"], x["coactor"]))[:25]

    def t_who_played_role(self, role, title=None):
        role_l = role.lower()
        rows = []
        for r in self.rels:
            if r["type"] != "ACTED_IN" or (title and r["dst"] != title):
                continue
            if any(role_l in x.lower() for x in r["props"].get("roles", [])):
                rows.append({"actor": r["src"], "roles": r["props"]["roles"], "title": r["dst"]})
        return rows

    def t_person_role_in_movie(self, name, title):
        return [{"actor": name, "title": title, "roles": r["props"].get("roles", [])}
                for r in self._out(name, {"ACTED_IN"}) if r["dst"] == title]

    def t_movies_by_year(self, year_from, year_to):
        rows = [{"title": m["title"], "released": m.get("released"), "tagline": m.get("tagline")}
                for m in self.movies.values() if year_from <= (m.get("released") or 0) <= year_to]
        return sorted(rows, key=lambda x: (x["released"], x["title"]))

    def t_movie_reviews(self, title):
        rows = [{"reviewer": r["src"], "rating": r["props"].get("rating"), "summary": r["props"].get("summary")}
                for r in self._in(title, {"REVIEWED"})]
        return sorted(rows, key=lambda x: -(x["rating"] or 0))

    def t_top_rated(self):
        agg = defaultdict(list)
        for r in self.rels:
            if r["type"] == "REVIEWED":
                agg[r["dst"]].append(r["props"]["rating"])
        rows = [{"title": t, "avg_rating": sum(v) / len(v), "reviews": len(v)} for t, v in agg.items()]
        return sorted(rows, key=lambda x: (-x["avg_rating"], x["title"]))[:10]

    def t_recommend_similar(self, title):
        score = defaultdict(set)
        for r in self._in(title, CREW_TYPES):
            for r2 in self._out(r["src"], CREW_TYPES):
                if r2["dst"] != title:
                    score[r2["dst"]].add(r["src"])
        rows = [{"title": t, "released": self.movies[t].get("released"), "score": len(v), "via": sorted(v)}
                for t, v in score.items()]
        return sorted(rows, key=lambda x: (-x["score"], -(x["released"] or 0)))[:5]

    def t_recommend_for_person(self, name):
        seen = {r["dst"] for r in self._out(name, {"ACTED_IN"})}
        score = defaultdict(set)
        for r in self._out(name, {"ACTED_IN"}):
            for r2 in self._in(r["dst"], {"ACTED_IN"}):
                c = r2["src"]
                if c == name:
                    continue
                for r3 in self._out(c, {"ACTED_IN"}):
                    if r3["dst"] not in seen:
                        score[r3["dst"]].add(c)
        rows = [{"title": t, "released": self.movies[t].get("released"), "score": len(v), "via": sorted(v)}
                for t, v in score.items()]
        return sorted(rows, key=lambda x: (-x["score"], -(x["released"] or 0)))[:5]

    def t_shortest_path(self, a, b):
        # Undirected BFS over ACTED_IN|DIRECTED|PRODUCED|WROTE, like shortestPath()
        adj = defaultdict(list)
        for r in self.rels:
            if r["type"] in CREW_TYPES:
                adj[r["src"]].append((r["dst"], r["type"]))
                adj[r["dst"]].append((r["src"], r["type"]))
        if a not in adj or b not in adj:
            return []
        prev = {a: None}
        q = deque([a])
        while q:
            n = q.popleft()
            if n == b:
                break
            for m, t in adj[n]:
                if m not in prev:
                    prev[m] = (n, t)
                    q.append(m)
        if b not in prev:
            return []
        chain, rels, cur = [b], [], b
        while prev[cur]:
            cur, t = prev[cur]
            chain.append(cur)
            rels.append(t)
        chain.reverse(); rels.reverse()
        return [{"chain": chain, "rels": rels, "hops": len(rels)}]

    def t_shared_movies(self, a, b):
        bm = {r["dst"]: r["type"] for r in self._out(b, CREW_TYPES)}
        rows = [{"title": r["dst"], "released": self.movies[r["dst"]].get("released"),
                 "a_relation": r["type"], "b_relation": bm[r["dst"]]}
                for r in self._out(a, CREW_TYPES) if r["dst"] in bm]
        return sorted(rows, key=lambda x: x["released"] or 0)

    def t_people_born(self, year_from, year_to):
        rows = [{"name": p["name"], "born": p["born"]} for p in self.people.values()
                if p.get("born") and year_from <= p["born"] <= year_to]
        return sorted(rows, key=lambda x: (x["born"], x["name"]))

    def t_keyword_search(self, q):
        ql = q.lower()
        rows = [{"title": m["title"], "released": m.get("released"), "tagline": m.get("tagline")}
                for m in self.movies.values()
                if ql in m["title"].lower() or ql in (m.get("tagline") or "").lower()]
        return rows[:10]


class Neo4jStore:
    backend = "neo4j"

    def __init__(self, uri, user, password, database=None):
        from neo4j import GraphDatabase  # imported lazily so offline mode needs no driver
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.driver.verify_connectivity()
        self.database = database or None
        self.label = f"Neo4j ({uri.split('://')[-1].split('/')[0]})"

    def query(self, cypher, params=None):
        from neo4j import RoutingControl
        records, _, _ = self.driver.execute_query(
            cypher, params or {}, database_=self.database, routing_=RoutingControl.READ)
        return [r.data() for r in records]

    def run(self, tid, params):
        return self.query(TEMPLATES[tid]["cypher"], params)

    def schema(self):
        nodes = {r["label"]: r["n"] for r in self.query(
            "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS n")}
        rels = {r["type"]: r["n"] for r in self.query(
            "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n")}
        return {"nodes": nodes, "relationships": rels}

    def entity_names(self):
        movies = [r["t"] for r in self.query("MATCH (m:Movie) RETURN m.title AS t")]
        people = [r["n"] for r in self.query("MATCH (p:Person) RETURN p.name AS n")]
        return movies, people

    def close(self):
        self.driver.close()


_STORE = None
_STORE_ERROR = None


def get_store():
    """Return a cached store: Neo4j if configured and reachable, else local."""
    global _STORE, _STORE_ERROR
    if _STORE is not None:
        return _STORE
    uri, user, pwd = (os.getenv("NEO4J_URI"), os.getenv("NEO4J_USERNAME", "neo4j"),
                      os.getenv("NEO4J_PASSWORD"))
    if uri and pwd:
        try:
            _STORE = Neo4jStore(uri, user, pwd, os.getenv("NEO4J_DATABASE"))
            return _STORE
        except Exception as e:  # unreachable, bad credentials, driver missing...
            _STORE_ERROR = f"{type(e).__name__}: {e}"
    _STORE = LocalGraphStore()
    return _STORE


def store_error():
    return _STORE_ERROR
