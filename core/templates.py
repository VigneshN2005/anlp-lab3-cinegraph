"""Cypher query templates (deliverable: "Set of Cypher query templates").

Every template is parameterised (no string concatenation of user input, so no
Cypher injection) and read-only. The `columns` list documents what each query
returns; the local replica in graph.py returns exactly the same columns.
"""

CREW_TYPES = {"ACTED_IN", "DIRECTED", "PRODUCED", "WROTE"}

TEMPLATES = {
    "movie_info": {
        "description": "Full profile of a movie: year, tagline, cast with roles and crew.",
        "example": "Tell me about The Matrix",
        "cypher": """MATCH (m:Movie {title: $title})
RETURN m.title AS title, m.released AS released, m.tagline AS tagline,
       [(d:Person)-[:DIRECTED]->(m) | d.name] AS directors,
       [(w:Person)-[:WROTE]->(m)    | w.name] AS writers,
       [(p:Person)-[:PRODUCED]->(m) | p.name] AS producers,
       [(a:Person)-[r:ACTED_IN]->(m) | {name: a.name, roles: r.roles}] AS cast""",
    },
    "movie_cast": {
        "description": "Actors of a movie with the characters they played.",
        "example": "Who acted in Top Gun?",
        "cypher": """MATCH (a:Person)-[r:ACTED_IN]->(m:Movie {title: $title})
RETURN a.name AS actor, r.roles AS roles, a.born AS born
ORDER BY actor""",
    },
    "movie_crew": {
        "description": "Directors, writers or producers of a movie.",
        "example": "Who directed Cloud Atlas?",
        "cypher": """MATCH (p:Person)-[r]->(m:Movie {title: $title})
WHERE type(r) IN $rel_types
RETURN p.name AS person, type(r) AS relation
ORDER BY relation, person""",
    },
    "person_filmography": {
        "description": "Movies a person acted in / directed / wrote / produced.",
        "example": "Which movies did Tom Hanks act in?",
        "cypher": """MATCH (p:Person {name: $name})-[r]->(m:Movie)
WHERE type(r) IN $rel_types
RETURN m.title AS title, m.released AS released, type(r) AS relation, r.roles AS roles
ORDER BY released, title""",
    },
    "person_info": {
        "description": "Birth year and complete body of work of a person.",
        "example": "When was Keanu Reeves born?",
        "cypher": """MATCH (p:Person {name: $name})
RETURN p.name AS name, p.born AS born,
       [(p)-[:ACTED_IN]->(m) | m.title] AS acted_in,
       [(p)-[:DIRECTED]->(m) | m.title] AS directed,
       [(p)-[:WROTE]->(m)    | m.title] AS wrote,
       [(p)-[:PRODUCED]->(m) | m.title] AS produced""",
    },
    "co_actors": {
        "description": "People who acted alongside a person, ranked by shared movies.",
        "example": "Who has acted with Meg Ryan?",
        "cypher": """MATCH (p:Person {name: $name})-[:ACTED_IN]->(m:Movie)<-[:ACTED_IN]-(c:Person)
RETURN c.name AS coactor, collect(m.title) AS movies, count(m) AS shared
ORDER BY shared DESC, coactor
LIMIT 25""",
    },
    "who_played_role": {
        "description": "Which actor played a given character (optionally in one movie).",
        "example": "Who played Neo?",
        "cypher": """MATCH (a:Person)-[r:ACTED_IN]->(m:Movie)
WHERE any(role IN r.roles WHERE toLower(role) CONTAINS toLower($role))
  AND ($title IS NULL OR m.title = $title)
RETURN a.name AS actor, r.roles AS roles, m.title AS title""",
    },
    "person_role_in_movie": {
        "description": "The character a person played in a particular movie.",
        "example": "What role did Tom Cruise play in A Few Good Men?",
        "cypher": """MATCH (a:Person {name: $name})-[r:ACTED_IN]->(m:Movie {title: $title})
RETURN a.name AS actor, m.title AS title, r.roles AS roles""",
    },
    "movies_by_year": {
        "description": "Movies released in a year or year range.",
        "example": "Which movies were released in the 1990s?",
        "cypher": """MATCH (m:Movie)
WHERE m.released >= $year_from AND m.released <= $year_to
RETURN m.title AS title, m.released AS released, m.tagline AS tagline
ORDER BY released, title""",
    },
    "movie_reviews": {
        "description": "User reviews (rating + summary) for a movie.",
        "example": "What are the reviews for The Replacements?",
        "cypher": """MATCH (u:Person)-[r:REVIEWED]->(m:Movie {title: $title})
RETURN u.name AS reviewer, r.rating AS rating, r.summary AS summary
ORDER BY rating DESC""",
    },
    "top_rated": {
        "description": "Highest rated movies by average review score.",
        "example": "What are the top rated movies?",
        "cypher": """MATCH (:Person)-[r:REVIEWED]->(m:Movie)
RETURN m.title AS title, avg(r.rating) AS avg_rating, count(r) AS reviews
ORDER BY avg_rating DESC, title
LIMIT 10""",
    },
    "recommend_similar": {
        "description": "Recommendation: movies sharing the most cast/crew with a given movie.",
        "example": "Recommend movies similar to The Matrix",
        "cypher": """MATCH (m:Movie {title: $title})<-[:ACTED_IN|DIRECTED|WROTE|PRODUCED]-(p:Person)
      -[:ACTED_IN|DIRECTED|WROTE|PRODUCED]->(rec:Movie)
WHERE rec <> m
RETURN rec.title AS title, rec.released AS released,
       count(DISTINCT p) AS score, collect(DISTINCT p.name) AS via
ORDER BY score DESC, released DESC
LIMIT 5""",
    },
    "recommend_for_person": {
        "description": "Recommendation: movies of a person's co-actors they have not been in.",
        "example": "Suggest movies for a Tom Hanks fan",
        "cypher": """MATCH (p:Person {name: $name})-[:ACTED_IN]->(:Movie)<-[:ACTED_IN]-(c:Person)
      -[:ACTED_IN]->(rec:Movie)
WHERE c <> p AND NOT (p)-[:ACTED_IN]->(rec)
RETURN rec.title AS title, rec.released AS released,
       count(DISTINCT c) AS score, collect(DISTINCT c.name) AS via
ORDER BY score DESC, released DESC
LIMIT 5""",
    },
    "shortest_path": {
        "description": "Shortest connection between two people or movies (\"degrees of separation\").",
        "example": "How is Kevin Bacon connected to Keanu Reeves?",
        "cypher": """MATCH (a) WHERE a.name = $a OR a.title = $a
MATCH (b) WHERE b.name = $b OR b.title = $b
MATCH path = shortestPath((a)-[:ACTED_IN|DIRECTED|PRODUCED|WROTE*..12]-(b))
RETURN [n IN nodes(path) | coalesce(n.name, n.title)] AS chain,
       [r IN relationships(path) | type(r)] AS rels,
       length(path) AS hops""",
    },
    "shared_movies": {
        "description": "Movies two people worked on together.",
        "example": "Which movies have Tom Hanks and Meg Ryan done together?",
        "cypher": """MATCH (a:Person {name: $a})-[r1]->(m:Movie)<-[r2]-(b:Person {name: $b})
WHERE type(r1) IN ['ACTED_IN','DIRECTED','PRODUCED','WROTE']
  AND type(r2) IN ['ACTED_IN','DIRECTED','PRODUCED','WROTE']
RETURN m.title AS title, m.released AS released,
       type(r1) AS a_relation, type(r2) AS b_relation
ORDER BY released""",
    },
    "people_born": {
        "description": "People born in a year or range.",
        "example": "Which actors were born in 1964?",
        "cypher": """MATCH (p:Person)
WHERE p.born >= $year_from AND p.born <= $year_to
RETURN p.name AS name, p.born AS born
ORDER BY born, name""",
    },
    "keyword_search": {
        "description": "Fallback: keyword search over movie titles and taglines.",
        "example": "Movies with 'love' in the tagline",
        "cypher": """MATCH (m:Movie)
WHERE toLower(m.title) CONTAINS toLower($q) OR toLower(m.tagline) CONTAINS toLower($q)
RETURN m.title AS title, m.released AS released, m.tagline AS tagline
LIMIT 10""",
    },
}
