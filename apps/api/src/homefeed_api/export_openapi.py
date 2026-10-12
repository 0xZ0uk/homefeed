"""Write the OpenAPI schema to `apps/api/openapi.json`."""

import json
from pathlib import Path

from homefeed_api.main import app

OUTPUT = Path(__file__).resolve().parents[2] / "openapi.json"


def main() -> None:
    OUTPUT.write_text(json.dumps(app.openapi(), indent=2) + "\n")


if __name__ == "__main__":
    main()
