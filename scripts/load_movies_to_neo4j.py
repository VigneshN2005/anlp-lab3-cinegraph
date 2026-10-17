"""Load the official Neo4j Movies dataset into your Neo4j instance (AuraDB Free
or Neo4j Desktop). Equivalent to running `:play movies` in Neo4j Browser.

Usage (from the project root):
    pip install -r requirements.txt
    set NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io      (Windows: set / macOS-Linux: export)
    set NEO4J_USERNAME=neo4j
    set NEO4J_PASSWORD=your-password
    python scripts/load_movies_to_neo4j.py
"""
import os
import pathlib
import sys

from neo4j import GraphDatabase

ROOT = pathlib.Path(__file__).resolve().parent.parent
script = (ROOT / "data" / "movies.cypher").read_text(encoding="utf-8")
statements = [s.strip() for s in script.split(";\n") if s.strip()]

uri = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USERNAME", "neo4j")
pwd = os.getenv("NEO4J_PASSWORD")
if not (uri and pwd):
    sys.exit("Set NEO4J_URI, NEO4J_USERNAME and NEO4J_PASSWORD first.")

with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
    driver.verify_connectivity()
    db = os.getenv("NEO4J_DATABASE") or None
    for i, stmt in enumerate(statements, 1):
        driver.execute_query(stmt, database_=db)
        print(f"[{i}/{len(statements)}] ok")
    records, _, _ = driver.execute_query(
        "MATCH (m:Movie) WITH count(m) AS movies MATCH (p:Person) "
        "WITH movies, count(p) AS people MATCH ()-[r]->() "
        "RETURN movies, people, count(r) AS relationships", database_=db)
    print("Loaded:", records[0].data())  # expected: 38 movies, 133 people, 253 relationships
