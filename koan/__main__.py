# Entry point: `uv run koan` or `python -m koan`.
# Dispatches to subcommands: `koan run` and `koan memory ...`.

from __future__ import annotations

import argparse
import sys

from .logger import setup_logging
from .memory.types import MEMORY_TYPES
from .cli.memory import cmd_memory
from .cli.run import cmd_run

# Shared flags inherited by every subcommand.
_common = argparse.ArgumentParser(add_help=False)
_common.add_argument("--debug", action="store_true",
                     help="Enable debug logging")


def main() -> None:
    parser = argparse.ArgumentParser(prog="koan", parents=[_common])
    subs = parser.add_subparsers(dest="subcommand")

    # koan run
    run_parser = subs.add_parser("run", help="Start the koan web server",
                                 parents=[_common])
    run_parser.add_argument("--port", type=int, default=None,
                            help="Port to listen on (default: random free port)")
    run_parser.add_argument("--address", type=str, default="127.0.0.1",
                            help="Address to bind to (default: 127.0.0.1; "
                                 "use 0.0.0.0 to bind all IPv4 interfaces)")
    run_parser.add_argument("--log-level", type=str, default="INFO")
    run_parser.add_argument("--no-open", action="store_true",
                            help="Don't open browser on startup")
    run_parser.add_argument("--skip-build", action="store_true",
                            help="Skip frontend rebuild check")
    run_parser.add_argument("-p", "--prompt", type=str, default="",
                            help="Pre-fill the task description")
    run_parser.add_argument("--yolo", action="store_true",
                            help="Skip all agent permission prompts (dangerous)")
    run_parser.add_argument("--directed-phases", nargs="+", default=None,
                            help="Fixed phase sequence for eval runs (e.g. intake plan-spec done)")

    # koan memory
    mem_parser = subs.add_parser("memory", help="Manage project memory",
                                 parents=[_common])
    mem_subs = mem_parser.add_subparsers(dest="memory_command")

    mem_add = mem_subs.add_parser("memorize", help="Create or update a memory entry")
    mem_add.add_argument("--type", required=True, choices=list(MEMORY_TYPES))
    mem_add.add_argument("--title", required=True)
    mem_add.add_argument("--body", default=None,
                         help="Entry body (reads stdin if omitted)")
    mem_add.add_argument("--related", action="append", default=[])
    mem_add.add_argument("--entry-id", type=int, default=None, dest="entry_id")

    mem_rm = mem_subs.add_parser("forget", help="Delete a memory entry")
    mem_rm.add_argument("entry_id", type=int)
    mem_rm.add_argument("--type", default=None, choices=list(MEMORY_TYPES))

    mem_st = mem_subs.add_parser("status", help="Show summary and entry listing")
    mem_st.add_argument("--type", default=None, choices=list(MEMORY_TYPES))
    mem_st.add_argument("--json", action="store_true", dest="json_output")

    mem_search = mem_subs.add_parser("search", help="Search memory entries")
    mem_search.add_argument("query", help="Search query")
    mem_search.add_argument("--type", default=None, choices=list(MEMORY_TYPES),
                            help="Filter by memory type")
    mem_search.add_argument("-k", type=int, default=5,
                            help="Number of results (default: 5)")
    mem_search.add_argument("--json", action="store_true", dest="json_output",
                            help="Machine-readable JSON output")

    mem_rag = mem_subs.add_parser("rag", help="Run RAG pipeline")
    mem_rag.add_argument("--directive", required=True,
                         help="Retrieval directive (what kind of knowledge to find)")
    mem_rag.add_argument("--anchor", required=True,
                         help="Topical anchor text or @path/to/file")
    mem_rag.add_argument("-k", type=int, default=5,
                         help="Number of final results (default: 5)")
    mem_rag.add_argument("--json", action="store_true", dest="json_output",
                         help="Machine-readable JSON output")

    mem_reflect = mem_subs.add_parser(
        "reflect",
        help="Reflect on memory entries via an LLM tool-calling loop",
    )
    mem_reflect.add_argument("question", help="The broad question to answer")
    mem_reflect.add_argument(
        "--context", default=None,
        help="Optional caller context (e.g. subsystem being worked on)",
    )
    mem_reflect.add_argument(
        "--show-trace", action="store_true", dest="show_trace",
        help="Stream each search call to stderr during the loop",
    )
    mem_reflect.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Machine-readable JSON output",
    )

    args = parser.parse_args()

    if args.subcommand is None:
        parser.print_help()
        sys.exit(1)

    # Configure logging before any subcommand runs.
    if args.debug:
        log_level = "DEBUG"
    elif args.subcommand == "run":
        log_level = args.log_level
    else:
        log_level = "INFO"
    setup_logging(log_level)

    if args.subcommand == "run":
        args.log_level = log_level
        cmd_run(args)
    elif args.subcommand == "memory":
        args._mem_parser = mem_parser
        cmd_memory(args)


if __name__ == "__main__":
    main()
