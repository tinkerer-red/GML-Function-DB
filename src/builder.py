#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from _catalog import (
    BUILD_DIR,
    DB_DIR,
    GMLSPEC_PATH,
    SCHEMA_PATH,
    apply_filters,
    compile_expression,
    load_contract,
    load_db_records,
    load_rows,
    stringify,
)
from validate import validate_catalog


OUTPUT_SUFFIX = {
    "json": ".json",
    "names": ".txt",
    "csv": ".csv",
}


def consumer_records(db_dir: Path, contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = {}
    for name, row in load_db_records(db_dir, contract, include_source_only=False).items():
        records[name] = {key: value for key, value in row.items() if key not in {"db_exists", "db_path"}}
    return records


def build_payload(
    rows: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    output_format: str,
) -> Any:
    names = sorted(row["function_name"] for row in rows if row.get("db_exists") is True)
    if output_format == "names":
        return names
    return {name: records[name] for name in names}


def consumer_fields(contract: dict[str, Any]) -> list[str]:
    fields = ["function_name"]
    for field in contract["record_key_order"]:
        if contract["fields"][field].get("source_only") is not True:
            fields.append(field)
    return fields


def parse_fields(fields: str | None, contract: dict[str, Any]) -> list[str]:
    if not fields:
        return consumer_fields(contract)
    return [field.strip() for field in fields.split(",") if field.strip()]


def default_output_path(output_format: str) -> Path:
    return BUILD_DIR / f"functions_resolved{OUTPUT_SUFFIX[output_format]}"


def write_payload(path: Path, payload: Any, output_format: str, csv_fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "names":
        path.write_text("".join(f"{name}\n" for name in payload), encoding="utf-8", newline="\n")
        return
    if output_format == "csv":
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=csv_fields, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            for record in payload.values():
                writer.writerow({field: stringify(record.get(field)) for field in csv_fields})
        return
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=4, ensure_ascii=True)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build filtered GML function catalog outputs.")
    parser.add_argument("--db-dir", type=Path, default=DB_DIR)
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    parser.add_argument("--gmlspec", type=Path, default=GMLSPEC_PATH)
    parser.add_argument("--include", action="append", default=[], metavar="EXPR", help="Require a filter expression.")
    parser.add_argument("--exclude", action="append", default=[], metavar="EXPR", help="Exclude a filter expression.")
    parser.add_argument("--format", choices=["json", "names", "csv"], default="json")
    parser.add_argument("--fields", help="Comma-separated CSV fields. Defaults to the consumer schema fields.")
    parser.add_argument("--out", type=Path, help="Single-build output path.")
    parser.add_argument("--list-fields", action="store_true")
    parser.add_argument("--skip-validation", action="store_true")
    args = parser.parse_args()

    try:
        contract = load_contract(args.schema)
    except Exception as exc:
        print(f"Builder error: {exc}", file=sys.stderr)
        return 1

    for expression in [*args.include, *args.exclude]:
        try:
            compile_expression(expression)
        except Exception as exc:
            print(f"Invalid filter {expression!r}: {exc}", file=sys.stderr)
            return 1

    query_rows = load_rows(args.db_dir, contract, args.gmlspec, "db")

    if args.list_fields:
        for field in sorted({field for row in query_rows for field in row}):
            print(field)
        return 0

    if not args.skip_validation:
        reporter = validate_catalog(args.db_dir, contract, gmlspec_path=args.gmlspec)
        if reporter.errors:
            for error in reporter.errors:
                print(f"error: {error}", file=sys.stderr)
            print("Build aborted because validation failed.", file=sys.stderr)
            return 1

    records = consumer_records(args.db_dir, contract)
    fields = parse_fields(args.fields, contract)
    rows = apply_filters(query_rows, args.include, args.exclude)
    payload = build_payload(rows, records, args.format)
    out = args.out or default_output_path(args.format)
    write_payload(out, payload, args.format, fields)
    print(f"{len(rows)} function(s) written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
