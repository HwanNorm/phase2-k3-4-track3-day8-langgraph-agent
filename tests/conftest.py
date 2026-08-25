"""Pytest bootstrap.

Loads .env before test collection so module-level skip checks (e.g. the
API-key check in test_graph_smoke.py) see the same environment the graph
and LLM factory will use at runtime.
"""

from dotenv import load_dotenv

load_dotenv()
