"""Deterministic template-based answer generation.

Used when no LLM key is configured (offline demo), when the LLM call fails, and
as a reference answer during evaluation. Every sentence is built only from the
retrieved records, so it is grounded by construction.
"""
from __future__ import annotations


def join(items, limit=12):
    items = [str(i) for i in items if i]
    if not items:
        return ""
    extra = len(items) - limit
    items = items[:limit]
    s = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
    return s + (f" (+{extra} more)" if extra > 0 else "")


def roles(r):
    return "/".join(r) if r else "an uncredited role"


REL_VERB = {"ACTED_IN": "acted in", "DIRECTED": "directed", "WROTE": "wrote", "PRODUCED": "produced"}


def template_answer(plan, rows: list[dict]) -> str:
    i, p = plan.intent, plan.params
    if i == "greet":
        return "Hello! I'm CineGraph. Ask me about movies, actors, directors, roles, reviews or recommendations from the Neo4j Movies graph."
    if i == "thanks":
        return "You're welcome. Ask me anything else about the movie graph."
    if i == "bye":
        return "Goodbye! Enjoy your next movie."
    if i == "help":
        return ("Try: \"Who directed The Matrix?\", \"Which movies did Tom Hanks act in?\", "
                "\"Who played Neo?\", \"Recommend movies like Top Gun\", "
                "\"How is Kevin Bacon connected to Keanu Reeves?\" or \"Movies released in the 1990s\".")
    if i == "unknown":
        return "I couldn't map that to the movie graph. Try naming a movie or person, e.g. \"Who acted in Apollo 13?\""
    if not rows:
        what = p.get("title") or p.get("name") or p.get("role") or p.get("q") or "that"
        return f"I couldn't find anything about {what} for that question in the movie graph."

    if i == "movie_info":
        r = rows[0]
        s = f"{r['title']} was released in {r['released']}."
        if r.get("tagline"):
            s += f" Tagline: \"{r['tagline']}\"."
        if r.get("directors"):
            s += f" Directed by {join(r['directors'])}."
        if r.get("cast"):
            s += f" Cast: {join([c['name'] for c in r['cast']], 6)}."
        return s
    if i == "movie_cast":
        body = join([f"{r['actor']} ({roles(r['roles'])})" for r in rows], 15)
        return f"The cast of {p['title']} includes {body}."
    if i in ("movie_directors", "movie_writers", "movie_producers", "movie_crew"):
        verb = {"movie_directors": "directed", "movie_writers": "written",
                "movie_producers": "produced"}.get(i)
        if verb:
            return f"{p['title']} was {verb} by {join([r['person'] for r in rows])}."
        return f"Crew of {p['title']}: " + "; ".join(f"{r['person']} ({REL_VERB[r['relation']]})" for r in rows) + "."
    if i in ("person_movies", "person_directed", "person_wrote", "person_produced"):
        verb = REL_VERB[p["rel_types"][0]]
        items = [f"{r['title']} ({r['released']})" + (f" as {roles(r['roles'])}" if r.get("roles") else "")
                 for r in rows]
        return f"{p['name']} {verb} {len(rows)} movie{'s' if len(rows) != 1 else ''} in the graph: {join(items, 15)}."
    if i == "person_info":
        r = rows[0]
        s = f"{r['name']} was born in {r['born']}." if r.get("born") else f"The graph has no birth year for {r['name']}."
        for key, verb in (("acted_in", "Acted in"), ("directed", "Directed"), ("wrote", "Wrote"), ("produced", "Produced")):
            if r.get(key):
                s += f" {verb}: {join(r[key], 8)}."
        return s
    if i == "co_actors":
        top = [f"{r['coactor']} ({r['shared']})" for r in rows[:10]]
        return f"{p['name']} has acted with {len(rows)} people in the graph. Most frequent co-stars (shared movies): {join(top, 10)}."
    if i == "who_played_role":
        return " ".join(f"{r['actor']} played {roles(r['roles'])} in {r['title']}." for r in rows[:8])
    if i == "person_role_in_movie":
        r = rows[0]
        return f"{r['actor']} played {roles(r['roles'])} in {r['title']}."
    if i == "movies_by_year":
        rng = str(p["year_from"]) if p["year_from"] == p["year_to"] else f"{p['year_from']}-{p['year_to']}"
        if p["year_to"] >= 2100:
            rng = f"after {p['year_from'] - 1}"
        if p["year_from"] <= 1800:
            rng = f"before {p['year_to'] + 1}"
        return f"{len(rows)} movie{'s' if len(rows) != 1 else ''} released {('in ' if rng[0].isdigit() else '')}{rng}: " + \
            join([f"{r['title']} ({r['released']})" for r in rows], 20) + "."
    if i == "people_born":
        return f"{len(rows)} people born in that period: " + join([f"{r['name']} ({r['born']})" for r in rows], 20) + "."
    if i == "reviews":
        avg = sum(r["rating"] for r in rows) / len(rows)
        body = "; ".join(f"{r['reviewer']} rated it {r['rating']} - \"{r['summary']}\"" for r in rows)
        return f"{p['title']} has {len(rows)} review{'s' if len(rows) != 1 else ''} (average {avg:.1f}/100): {body}."
    if i == "top_rated":
        prefix = (plan.note + " ") if plan.note else ""
        return prefix + "Top rated movies by average review: " + \
            join([f"{r['title']} ({r['avg_rating']:.0f}/100, {r['reviews']} review{'s' if r['reviews'] != 1 else ''})" for r in rows], 10) + "."
    if i == "recommend":
        seed = p.get("title") or p.get("name")
        items = [f"{r['title']} ({r['released']}) - shares {join(r['via'], 3)}" for r in rows]
        return f"If you like {seed}, try: " + "; ".join(items) + "."
    if i == "connection":
        r = rows[0]
        steps = [r["chain"][0]]
        for k, rel in enumerate(r["rels"]):
            steps.append(f"-[{rel}]- {r['chain'][k + 1]}")
        return f"{p['a']} and {p['b']} are {r['hops']} hops apart: " + " ".join(steps) + "."
    if i == "shared_movies":
        items = [f"{r['title']} ({r['released']})" for r in rows]
        return f"{p['a']} and {p['b']} worked together on {join(items)}."
    if i == "keyword_search":
        return f"Movies matching \"{p['q']}\": " + join([f"{r['title']} ({r['released']})" for r in rows]) + "."
    if i == "text2cypher":
        return f"Found {len(rows)} record(s): " + "; ".join(", ".join(f"{k}: {v}" for k, v in r.items()) for r in rows[:8])
    return str(rows[:5])
