"""Convert the official Neo4j Movies Cypher script (data/movies.cypher) into
data/movies.json, so the app can run an in-memory replica of the same graph
when no Neo4j instance is configured.

Run from the project root:  python scripts/cypher_to_json.py
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "data" / "movies.cypher").read_text(encoding="utf-8")

# A Cypher string literal in single or double quotes, allowing \' escapes
STR = r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""
VALUE = rf"\[[^\]]*\]|{STR}|-?\d+"


def unquote(lit: str) -> str:
    return lit[1:-1].replace("\\'", "'").replace('\\"', '"')


def parse_value(v: str):
    if v.startswith("["):
        return [unquote(x) for x in re.findall(STR, v)]
    if v[0] in "'\"":
        return unquote(v)
    return int(v)


def parse_map(body: str) -> dict:
    return {k: parse_value(v) for k, v in re.findall(rf"(\w+)\s*:\s*({VALUE})", body)}


NODE = re.compile(rf"MERGE \((\w+):(Movie|Person) \{{((?:{STR}|[^}}])*)\}}\)(?: ON CREATE SET ([^\n]*))?")
REL = re.compile(rf"MERGE \((\w+)\)-\[:(\w+)(?: \{{((?:{STR}|[^}}])*)\}})?\]->\((\w+)\)")
SETS = re.compile(rf"\w+\.(\w+)\s*=\s*({VALUE})")

# Variable names are unique across the script, and the final review block
# refers to movies defined in earlier statements, so keep one global map.
movies, people, rels, var = {}, {}, [], {}
for stmt in SRC.split(";\n"):
    for v, label, body, sets in NODE.findall(stmt):
        props = parse_map(body)
        props.update({k: parse_value(x) for k, x in SETS.findall(sets or "")})
        key = props["title"] if label == "Movie" else props["name"]
        var[v] = (label, key)
        (movies if label == "Movie" else people).setdefault(key, {}).update(props)
    for a, typ, body, b in REL.findall(stmt):
        rels.append({
            "type": typ,
            "src": var[a][1], "src_label": var[a][0],
            "dst": var[b][1], "dst_label": var[b][0],
            "props": parse_map(body) if body else {},
        })

out = {
    "source": "https://github.com/neo4j-graph-examples/movies (scripts/movies.cypher)",
    "movies": sorted(movies.values(), key=lambda m: m["title"]),
    "people": sorted(people.values(), key=lambda p: p["name"]),
    "relationships": rels,
}
(ROOT / "data" / "movies.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"{len(out['movies'])} movies, {len(out['people'])} people, {len(rels)} relationships")
