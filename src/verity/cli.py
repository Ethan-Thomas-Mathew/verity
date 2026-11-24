"""Command line: `uv run verity <command>`. Run `uv run verity --help` for the list."""

import argparse
import logging
import sys
from pathlib import Path

import uvicorn
from sqlalchemy.orm import sessionmaker

from verity.config import Settings
from verity.db.database import make_engine, transaction
from verity.evaluation import evaluate, save, to_markdown
from verity.llm.factory import build_llm
from verity.rag.store import index_directory
from verity.runs import build_embedder, create_run, execute_run
from verity.stories import load_stories


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verity", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("stories", help="list user stories")
    commands.add_parser("index", help="index the requirement documents for retrieval")
    run = commands.add_parser("run", help="plan, run and report on one story")
    run.add_argument("story", help="story key, for example SHELF-3")
    run.add_argument("--no-browser", action="store_true", help="skip UI tests")
    serve = commands.add_parser("serve", help="start the REST API")
    serve.add_argument("--port", type=int, default=8000)
    ev = commands.add_parser("eval", help="measure bug-finding against Shelf's planted bugs")
    ev.add_argument("--shelf-database-url", required=True)
    ev.add_argument("--story", action="append", help="limit to these stories")
    ev.add_argument("--no-browser", action="store_true")
    ev.add_argument("--out", type=Path, default=Path("eval/results"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings()

    if args.command == "serve":
        from verity.api.app import create_app

        # 127.0.0.1 only: the API has no login, so it must not be reachable from the network.
        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port)
        return 0

    stories = load_stories(settings.requirements_dir)
    if args.command == "stories":
        for story in stories.values():
            print(f"{story.key}  {story.summary}  ({', '.join(story.requirements)})")
        return 0

    factory = sessionmaker(make_engine(settings.database_url), expire_on_commit=False)
    embedder = build_embedder(settings)
    if args.command == "index":
        with transaction(factory) as session:
            count = index_directory(session, embedder, settings.requirements_dir)
        print(f"indexed {count} sections with {embedder.name}")
        return 0

    llm = build_llm(settings)
    if args.command == "run":
        chosen = stories.get(args.story)
        if chosen is None:
            print(f"unknown story {args.story}; try `verity stories`", file=sys.stderr)
            return 2
        run_id = create_run(factory, chosen, settings.target_url, llm.name)
        execute_run(
            run_id, chosen, settings, factory, llm, embedder, False if args.no_browser else None
        )
        print(f"run {run_id} finished; details at GET /runs/{run_id}")
        return 0

    report = evaluate(
        settings,
        factory,
        llm,
        embedder,
        args.shelf_database_url,
        Path("eval/ground_truth.json"),
        args.story,
        not args.no_browser,
    )
    path = save(report, args.out)
    print(to_markdown(report))
    print(f"saved {path} and {path.with_suffix('.json').name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
