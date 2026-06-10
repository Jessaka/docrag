"""Run ingestion for all configured providers in sequence."""

from __future__ import annotations

import json
import logging

from src.ingestion.ingest import run_ingestion


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = run_ingestion()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
