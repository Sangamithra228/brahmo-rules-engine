"""Shared fixture: an in-memory-ish seeded repository for tests."""
import os, tempfile
from backend.repository.sqlite_repo import SQLiteRepository
from backend.pipeline.engine import RulesEngine

_cache = {}

def fresh_repo() -> SQLiteRepository:
    path = os.path.join(tempfile.gettempdir(), "brahmo_test.db")
    if os.path.exists(path):
        os.remove(path)
    repo = SQLiteRepository(path)
    repo.initialise()
    repo.seed()
    return repo

def engine():
    if "e" not in _cache:
        repo = fresh_repo()
        _cache["e"] = (repo, RulesEngine(repo))
    return _cache["e"]
