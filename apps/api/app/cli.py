import argparse
import json

from .db import init_db
from .ingest import ingest_all
from .tagging import enrich_articles_without_tags


def main() -> None:
    parser = argparse.ArgumentParser(description="Stock News Aggregator CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Run RSS ingestion")
    ingest_parser.add_argument("--force-all", action="store_true", help="Ignore per-source polling interval")
    ingest_parser.add_argument("--source-id", type=int, default=None, help="Run only one source id")
    ingest_parser.add_argument(
        "--trigger-type",
        type=str,
        default="scheduled",
        choices=["manual", "scheduled"],
        help="Trigger type to persist in run logs",
    )

    enrich_parser = subparsers.add_parser("enrich", help="Backfill article tags")
    enrich_parser.add_argument("--limit", type=int, default=50, help="Max articles to process")
    enrich_parser.add_argument("--force", action="store_true", help="Retag articles even if tags exist")

    args = parser.parse_args()
    init_db()

    if args.command == "ingest":
        result = ingest_all(
            trigger_type=args.trigger_type,
            force_all=args.force_all,
            source_id=args.source_id,
        )
        print(json.dumps(result, indent=2))
        return

    if args.command == "enrich":
        result = enrich_articles_without_tags(limit=args.limit, force=args.force)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
