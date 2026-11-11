"""Dump the OpenAPI schema to stdout so the frontend can generate types without a running server.

Usage: uv run python -m coach.export_openapi > ../frontend/openapi.json
"""

import json

from coach.main import app

if __name__ == "__main__":
    print(json.dumps(app.openapi(), indent=2))
