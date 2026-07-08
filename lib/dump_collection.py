#!/usr/bin/env python3
"""Dump a ChromaDB collection as JSON to stdout. Exists so cross_machine_merge.py
can read the other machine's collection over SSH with a single clean command
instead of fragile inline-python quoting through two shells.

Usage:
    dump_collection.py <collection-name>
    dump_collection.py <collection-name> --since 1783372321.479

--since filters to entries whose metadata "created_epoch" (a Unix timestamp
float) is strictly greater than the given value. ChromaDB's $gt only accepts
int/float, not ISO-8601 strings, hence the numeric field. Keeps a growing
collection like qa-knowledge from being fully re-transferred on every sync run.
"""
import json
import sys
from pathlib import Path

CHROMA_PATH = Path.home() / ".claude" / "chroma"


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("usage: dump_collection.py <collection-name> [--since ISO_TIMESTAMP]", file=sys.stderr)
        sys.exit(1)

    collection_name = args[0]
    since = None
    if "--since" in args:
        since = float(args[args.index("--since") + 1])

    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    col = client.get_or_create_collection(collection_name)

    where = {"created_epoch": {"$gt": since}} if since is not None else None
    data = col.get(include=["documents", "metadatas"], where=where)

    print(json.dumps({
        "ids": data["ids"],
        "documents": data["documents"],
        "metadatas": data["metadatas"],
    }))


if __name__ == "__main__":
    main()
