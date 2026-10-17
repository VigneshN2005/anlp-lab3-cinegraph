"""Question understanding: entity linking + intent classification -> query plan.

Step 1  Entity linking   - find movie titles and person names in the question
                           (exact, article-insensitive, first/last-name and
                           fuzzy n-gram matching), longest match wins.
Step 2  Coreference      - "it", "that movie", "he", "she" resolve to the movie /
                           person discussed in the previous turn (dialogue state).
Step 3  Intent rules     - keyword patterns + the types of linked entities select
                           one Cypher template and fill its parameters.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

ARTICLES = re.compile(r"^(the|a|an)\s+")


def norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("&", "and")
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Entity:
    kind: str      # "movie" | "person"
    value: str     # canonical title / name in the graph
    span: str      # text matched in the question
    start: int
    method: str    # exact | partial-name | fuzzy | context


@dataclass
class Plan:
    intent: str
    template: str | None
    params: dict = field(default_factory=dict)
    entities: list = field(default_factory=list)
    note: str = ""


class EntityLinker:
    def __init__(self, movies: list[str], people: list[str]):
        self.movies, self.people = movies, people
        self.surface = []  # (normalised surface form, kind, canonical, method)
        for t in movies:
            n = norm(t)
            self.surface.append((n, "movie", t, "exact"))
            stripped = ARTICLES.sub("", n)
            if stripped != n and len(stripped) > 3:
                self.surface.append((stripped, "movie", t, "exact"))
        first, last = {}, {}
        for p in people:
            n = norm(p)
            self.surface.append((n, "person", p, "exact"))
            parts = n.split()
            if len(parts) >= 2:
                first.setdefault(parts[0], []).append(p)
                last.setdefault(parts[-1], []).append(p)
        # A first or last name alone is accepted only when it is unambiguous
        common = {"will", "bill", "james", "tom", "john", "mark", "paul", "jim", "rob"}
        for table in (first, last):
            for k, v in table.items():
                if len(v) == 1 and len(k) > 3 and k not in common:
                    self.surface.append((k, "person", v[0], "partial-name"))
        self.surface.sort(key=lambda x: -len(x[0]))
        self.fuzzy_pool = {s: (k, c) for s, k, c, m in self.surface if m == "exact" and len(s) > 5}

    def link(self, question: str) -> list[Entity]:
        q = " " + norm(question) + " "
        taken = [False] * len(q)
        found: list[Entity] = []
        for s, kind, canon, method in self.surface:
            for m in re.finditer(r"(?<= )" + re.escape(s) + r"(?=[ '])", q):
                a, b = m.start(), m.end()
                if any(taken[a:b]):
                    continue
                for i in range(a, b):
                    taken[i] = True
                if not any(e.value == canon for e in found):
                    found.append(Entity(kind, canon, s, a, method))
        # Fuzzy pass on remaining n-grams (handles typos such as "Keanu Reves")
        words = [(m.group(), m.start()) for m in re.finditer(r"[a-z0-9']+", q)]
        for n in (4, 3, 2):
            for i in range(len(words) - n + 1):
                a, b = words[i][1], words[i + n - 1][1] + len(words[i + n - 1][0])
                if any(taken[a:b]):
                    continue
                gram = q[a:b]
                hit = difflib.get_close_matches(gram, self.fuzzy_pool, n=1, cutoff=0.86)
                if hit:
                    kind, canon = self.fuzzy_pool[hit[0]]
                    if not any(e.value == canon for e in found):
                        found.append(Entity(kind, canon, gram, a, "fuzzy"))
                        for j in range(a, b):
                            taken[j] = True
        return sorted(found, key=lambda e: e.start)

    def mentions(self, text: str) -> set[str]:
        """All graph entities mentioned in a text (used for groundedness checks)."""
        return {e.value for e in self.link(text) if e.method != "fuzzy"}


# --------------------------------------------------------------------- intents
def has(q, pattern):
    return re.search(pattern, q) is not None


SMALL_TALK = [
    (r"^(hi|hello|hey|good (morning|evening|afternoon)|namaste)\b", "greet"),
    (r"\b(thank|thanks|thx)\b", "thanks"),
    (r"^(bye|goodbye|see you)\b", "bye"),
    (r"\b(help|what can you do|how do i use|examples?)\b", "help"),
]


def year_range(q: str):
    m = re.search(r"\b(19|20)(\d)0'?s\b", q)
    if m:
        y = int(m.group(1) + m.group(2) + "0")
        return y, y + 9
    years = [int(y) for y in re.findall(r"\b(19\d\d|20\d\d)\b", q)]
    if len(years) >= 2:
        return min(years), max(years)
    if len(years) == 1:
        y = years[0]
        if has(q, r"\b(after|since|later than)\b"):
            return y + (0 if "since" in q else 1), 2100
        if has(q, r"\b(before|earlier than|prior to)\b"):
            return 1800, y - 1
        return y, y
    return None


def plan_question(question: str, linker: EntityLinker, context: dict | None = None) -> Plan:
    context = context or {}
    q = norm(question)
    ents = linker.link(question)

    # Coreference with the dialogue state
    if not any(e.kind == "movie" for e in ents) and context.get("movie") and \
            has(q, r"\b(it|that movie|this movie|the movie|that film|this film|the film|its)\b"):
        ents.append(Entity("movie", context["movie"], "it", 999, "context"))
    if not any(e.kind == "person" for e in ents) and context.get("person") and \
            has(q, r"\b(he|she|him|her|his|they|them|that actor|this actor|that person)\b"):
        ents.append(Entity("person", context["person"], "pronoun", 999, "context"))

    movies = [e.value for e in ents if e.kind == "movie"]
    people = [e.value for e in ents if e.kind == "person"]
    P = lambda intent, tpl, note="", **params: Plan(intent, tpl, params, ents, note)

    if not ents:
        for pat, intent in SMALL_TALK:
            if has(q, pat):
                return P(intent, None)

    # --- two-entity questions
    nodes = movies + people
    if len(nodes) >= 2 and has(q, r"\b(connect|connected|connection|path|degrees?|separation|link|linked|related|bacon number)\b"):
        return P("connection", "shortest_path", a=nodes[0], b=nodes[1])
    if len(people) >= 2:
        return P("shared_movies", "shared_movies", a=people[0], b=people[1])

    # --- role questions
    m = re.search(r"\bwho (played|plays|portrayed|was|is) (the character |the role of )?([a-z' .]+?)(?: in .*)?$", q)
    if m and not people and not (movies and m.group(3).strip() in [norm(x) for x in movies]):
        role = m.group(3).strip()
        if role and not has(role, r"^(in|the director|director|the cast)\b") and \
                not has(q, r"\b(cast|acted|directed|direct|wrote|produced|starred)\b"):
            return P("who_played_role", "who_played_role", role=role, title=movies[0] if movies else None)
    if people and movies and has(q, r"\b(role|play|played|character|portray)"):
        return P("person_role_in_movie", "person_role_in_movie", name=people[0], title=movies[0])

    # --- recommendations and ratings
    if has(q, r"\b(recommend|suggest|similar|should i watch|what to watch|like)\b") or \
            has(q, r"\bfan\b"):
        if movies:
            return P("recommend", "recommend_similar", title=movies[0])
        if people:
            return P("recommend", "recommend_for_person", name=people[0])
        return P("recommend", "top_rated", note="No seed movie given, recommending top rated.")
    if has(q, r"\b(review|reviews|reviewed|rating|ratings|rated|critic)"):
        if movies:
            return P("reviews", "movie_reviews", title=movies[0])
        return P("top_rated", "top_rated")
    if has(q, r"\b(best|top|highest|greatest)\b") and not ents:
        return P("top_rated", "top_rated")

    # --- movie-centric
    if movies:
        t = movies[0]
        if has(q, r"\b(direct|directed|director|directors)\b"):
            return P("movie_directors", "movie_crew", title=t, rel_types=["DIRECTED"])
        if has(q, r"\b(wrote|writer|writers|written|screenplay|script)\b"):
            return P("movie_writers", "movie_crew", title=t, rel_types=["WROTE"])
        if has(q, r"\b(produce|produced|producer|producers)\b"):
            return P("movie_producers", "movie_crew", title=t, rel_types=["PRODUCED"])
        if has(q, r"\b(crew|made|behind)\b"):
            return P("movie_crew", "movie_crew", title=t, rel_types=["DIRECTED", "WROTE", "PRODUCED"])
        if has(q, r"\b(cast|acted|actors?|actress(es)?|star|stars|starred|starring|appear|appeared|who (was|were|is|are) in|played in|in it)\b"):
            return P("movie_cast", "movie_cast", title=t)
        return P("movie_info", "movie_info", title=t)

    # --- person-centric
    if people:
        n = people[0]
        if has(q, r"\b(with|alongside|co ?stars?|co ?actors?|together)\b"):
            return P("co_actors", "co_actors", name=n)
        if has(q, r"\b(direct|directed|director)\b"):
            return P("person_directed", "person_filmography", name=n, rel_types=["DIRECTED"])
        if has(q, r"\b(wrote|write|written|writer)\b"):
            return P("person_wrote", "person_filmography", name=n, rel_types=["WROTE"])
        if has(q, r"\b(produce|produced|producer)\b"):
            return P("person_produced", "person_filmography", name=n, rel_types=["PRODUCED"])
        if has(q, r"\b(born|birth|age|old|birthday)\b"):
            return P("person_info", "person_info", name=n)
        if has(q, r"\b(act|acted|acting|movies?|films?|star|starred|appear|appeared|role|roles|filmography|how many)\b"):
            return P("person_movies", "person_filmography", name=n, rel_types=["ACTED_IN"])
        return P("person_info", "person_info", name=n)

    # --- no entity: year / born filters
    yr = year_range(q)
    if yr and has(q, r"\b(born|birth)\b"):
        return P("people_born", "people_born", year_from=yr[0], year_to=yr[1])
    if yr:
        return P("movies_by_year", "movies_by_year", year_from=yr[0], year_to=yr[1])

    # --- fallback: keyword search on a content word
    words = [w for w in q.split() if len(w) > 3 and w not in STOP]
    if words:
        return P("keyword_search", "keyword_search", q=max(words, key=len),
                 note="No template matched; falling back to keyword search.")
    return P("unknown", None)


STOP = set("""what which where when about movie movies film films with from that this there their
them they have show tell give list find does were your please some like know want would could
should into than then also just more most many much very""".split())
