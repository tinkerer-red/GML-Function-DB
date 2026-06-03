#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from _catalog import (
    DB_DIR,
    DEFAULT_FIELDS,
    FACTS_PATH,
    GMLSPEC_PATH,
    HEURISTICS_PATH,
    SCHEMA_PATH,
    compact_record,
    compile_expression,
    field_value,
    iter_db_files,
    load_contract,
    load_rows,
    load_json,
    output_rows,
    resolve_record,
    row_matches,
    stringify,
    type_name,
    write_json,
)


class Reporter:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)


def validate_value(reporter: Reporter, location: str, value: Any, allowed_types: list[str]) -> None:
    actual_type = type_name(value)
    if actual_type not in allowed_types:
        reporter.error(f"{location}: expected type {'/'.join(allowed_types)}, got {actual_type}")


def validate_key_order(reporter: Reporter, location: str, actual_keys: list[str], contract_order: list[str]) -> None:
    expected = [key for key in contract_order if key in actual_keys]
    if actual_keys != expected:
        reporter.error(f"{location}: field order must follow schema; expected {expected}, got {actual_keys}")


def load_facts(path: Path = FACTS_PATH) -> list[dict[str, Any]]:
    data = load_json(path)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError(f"{path.as_posix()}: expected a schema_version=1 object")
    facts = data.get("facts")
    if not isinstance(facts, list):
        raise ValueError(f"{path.as_posix()}: facts must be an array")
    return [{**fact, "_source_path": path.as_posix()} for fact in facts]


def validate_fact_definitions(reporter: Reporter, facts: list[dict[str, Any]], contract: dict[str, Any]) -> None:
    fields = contract["fields"]
    seen: set[str] = set()
    for fact in facts:
        source = fact.get("_source_path", "<facts>")
        name = fact.get("name", "<unnamed>")
        if not isinstance(name, str) or not name:
            reporter.error(f"{source}: fact name must be a non-empty string")
            continue
        if name in seen:
            reporter.error(f"{source}::{name}: duplicate fact name")
        seen.add(name)

        implication = "when_any_true" in fact or "then_field" in fact or "then_value" in fact
        forbidden_query = "forbid" in fact
        if implication == forbidden_query:
            reporter.error(f"{source}::{name}: fact must define exactly one implication or forbid query")
            continue
        if implication:
            when_any_true = fact.get("when_any_true")
            then_field = fact.get("then_field")
            if not isinstance(when_any_true, list) or not when_any_true or not all(isinstance(key, str) for key in when_any_true):
                reporter.error(f"{source}::{name}: when_any_true must be a non-empty string array")
                continue
            unknown = [key for key in when_any_true if key not in fields]
            if unknown:
                reporter.error(f"{source}::{name}: unknown when_any_true field(s): {', '.join(unknown)}")
            if not isinstance(then_field, str) or then_field not in fields:
                reporter.error(f"{source}::{name}: then_field must be a known field")
                continue
            if "then_value" not in fact:
                reporter.error(f"{source}::{name}: missing then_value")
                continue
            validate_value(reporter, f"{source}::{name}.then_value", fact["then_value"], fields[then_field].get("types", []))
            continue

        forbid = fact.get("forbid")
        if not isinstance(forbid, dict):
            reporter.error(f"{source}::{name}: forbid must be an object")
            continue
        if forbid.get("source", "db") not in {"db", "spec", "all"}:
            reporter.error(f"{source}::{name}: forbid.source must be db, spec, or all")
        validate_filter_rule(reporter, fact, "forbid")


def validate_filter_rule(reporter: Reporter, rule: dict[str, Any], label: str) -> None:
    source = rule.get("_source_path", "<rules>")
    name = rule.get("name", "<unnamed>")
    query = rule.get(label, rule)
    if not isinstance(query, dict):
        reporter.error(f"{source}::{name}: {label} must be an object")
        return
    if not any(query.get(key) for key in ("all", "any", "none")):
        reporter.error(f"{source}::{name}: {label} must define at least one expression")
    for key in ("all", "any", "none"):
        expressions = query.get(key, [])
        if not isinstance(expressions, list) or not all(isinstance(expression, str) for expression in expressions):
            reporter.error(f"{source}::{name}: {label}.{key} must be a string array")
            continue
        for expression in expressions:
            try:
                compile_expression(expression)
            except ValueError as exc:
                reporter.error(f"{source}::{name}: invalid expression {expression!r}: {exc}")


def validate_fact_implications(reporter: Reporter, location: str, resolved: dict[str, Any], facts: list[dict[str, Any]]) -> None:
    for fact in facts:
        when_any_true = fact.get("when_any_true", [])
        if any(resolved.get(key) is True for key in when_any_true):
            then_field = fact.get("then_field")
            then_value = fact.get("then_value")
            if resolved.get(then_field) != then_value:
                reporter.error(f"{location}: fact {fact.get('name')} requires {then_field}={json.dumps(then_value)}")


def validate_forbidden_facts(
    reporter: Reporter,
    db_dir: Path,
    contract: dict[str, Any],
    facts: list[dict[str, Any]],
    gmlspec_path: Path,
) -> None:
    forbidden = [fact for fact in facts if "forbid" in fact]
    if not forbidden:
        return
    rows_by_source = {
        source: load_rows(db_dir, contract, gmlspec_path, source)
        for source in ("db", "spec", "all")
    }
    for fact in forbidden:
        query = fact["forbid"]
        for row in rows_by_source[query.get("source", "db")]:
            if row_matches(query, row):
                location = row.get("db_path") or row.get("function_name") or "<unknown>"
                message = fact.get("message") or fact.get("description") or "forbidden fact matched"
                reporter.error(f"{location}::{row.get('function_name')}: fact {fact.get('name')} forbids this record: {message}")


def validate_record(
    reporter: Reporter,
    path: Path,
    function_name: str,
    record: Any,
    contract: dict[str, Any],
    facts: list[dict[str, Any]],
    expected_category_path: str,
) -> None:
    location = f"{path.as_posix()}::{function_name}"
    if not isinstance(record, dict):
        reporter.error(f"{location}: record must be an object")
        return
    fields = contract["fields"]
    contract_order = contract["record_key_order"]
    actual_keys = list(record)
    unknown = [key for key in actual_keys if key not in fields]
    if unknown:
        reporter.error(f"{location}: unknown field(s): {', '.join(unknown)}")
    missing = [key for key in contract_order if fields[key].get("required") is True and key not in record]
    if missing:
        reporter.error(f"{location}: missing required field(s): {', '.join(missing)}")
    validate_key_order(reporter, location, actual_keys, contract_order)
    for key, value in record.items():
        if key in fields:
            validate_value(reporter, f"{location}.{key}", value, fields[key].get("types", []))
    category_path = record.get("category_path")
    if isinstance(category_path, str) and category_path != expected_category_path:
        reporter.error(f"{location}.category_path: expected {expected_category_path!r} from file path, got {category_path!r}")
    try:
        resolved = resolve_record(record, contract)
    except KeyError:
        return
    validate_fact_implications(reporter, location, resolved, facts)


def validate_catalog(
    db_dir: Path = DB_DIR,
    contract: dict[str, Any] | None = None,
    facts: list[dict[str, Any]] | None = None,
    gmlspec_path: Path = GMLSPEC_PATH,
    facts_path: Path = FACTS_PATH,
) -> Reporter:
    reporter = Reporter()
    try:
        contract = contract or load_contract()
        facts = facts or load_facts(facts_path)
    except Exception as exc:
        reporter.error(f"Configuration error: {exc}")
        return reporter
    validate_fact_definitions(reporter, facts, contract)
    seen: dict[str, Path] = {}
    files = iter_db_files(db_dir)
    if not files:
        reporter.error(f"{db_dir.as_posix()}: no JSON files found")
        return reporter
    for path in files:
        expected_category_path = path.relative_to(db_dir).with_suffix("").as_posix()
        try:
            data = load_json(path)
        except Exception as exc:
            reporter.error(f"{path.as_posix()}: failed to parse JSON: {exc}")
            continue
        if not isinstance(data, dict):
            reporter.error(f"{path.as_posix()}: category file must contain an object")
            continue
        for function_name, record in data.items():
            if function_name in seen:
                reporter.error(f"{path.as_posix()}::{function_name}: duplicate; already in {seen[function_name].as_posix()}")
            else:
                seen[function_name] = path
            validate_record(reporter, path, function_name, record, contract, facts, expected_category_path)
    validate_forbidden_facts(reporter, db_dir, contract, facts, gmlspec_path)
    return reporter


def normalize_catalog(db_dir: Path, contract: dict[str, Any], write: bool) -> list[Path]:
    changed = []
    for path in iter_db_files(db_dir):
        data = load_json(path)
        normalized = {name: compact_record(record, contract) for name, record in data.items()}
        if data != normalized or any(
            list(record) != [key for key in contract["record_key_order"] if key in record]
            for record in data.values() if isinstance(record, dict)
        ):
            changed.append(path)
            if write:
                write_json(path, normalized)
    return changed


def load_heuristics(path: Path = HEURISTICS_PATH) -> list[dict[str, Any]]:
    data = load_json(path)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError(f"{path.as_posix()}: expected a schema_version=1 object")
    heuristics = data.get("heuristics")
    if not isinstance(heuristics, list):
        raise ValueError(f"{path.as_posix()}: heuristics must be an array")
    return [{**heuristic, "_source_path": path.as_posix()} for heuristic in heuristics]


def validate_heuristics(heuristics: list[dict[str, Any]]) -> None:
    reporter = Reporter()
    seen: set[str] = set()
    for heuristic in heuristics:
        name = heuristic.get("name")
        if not isinstance(name, str) or not name:
            reporter.error("heuristic name must be a non-empty string")
            continue
        if name in seen:
            reporter.error(f"duplicate heuristic name {name!r}")
        seen.add(name)
        if heuristic.get("source", "db") not in {"db", "spec", "all"}:
            reporter.error(f"{name}: source must be db, spec, or all")
        validate_filter_rule(reporter, heuristic, "heuristic")
    if reporter.errors:
        raise ValueError("; ".join(reporter.errors))


def run_heuristics(
    heuristics: list[dict[str, Any]],
    db_dir: Path,
    contract: dict[str, Any],
    gmlspec_path: Path,
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    rows_by_source = {
        source: load_rows(db_dir, contract, gmlspec_path, source)
        for source in ("db", "spec", "all")
    }
    results = []
    for heuristic in heuristics:
        rows = [row for row in rows_by_source[heuristic.get("source", "db")] if row_matches(heuristic, row)]
        rows.sort(key=lambda row: stringify(field_value(row, "function_name")))
        results.append((heuristic, rows))
    return results


def print_heuristics(results: list[tuple[dict[str, Any], list[dict[str, Any]]]], output_format: str, limit: int) -> None:
    if output_format == "summary":
        width = max([len("heuristic"), *(len(rule["name"]) for rule, _ in results)])
        print(f"{'heuristic'.ljust(width)}  results  description")
        print(f"{'-' * width}  -------  -----------")
        for rule, rows in results:
            print(f"{rule['name'].ljust(width)}  {str(len(rows)).rjust(7)}  {rule.get('description', '')}")
        return
    if output_format == "json":
        print(json.dumps([
            {"name": rule["name"], "count": len(rows), "rows": rows[:limit] if limit else rows}
            for rule, rows in results
        ], indent=2, ensure_ascii=True))
        return
    if output_format == "csv":
        fields = ["heuristic_name", *DEFAULT_FIELDS]
        writer = csv.DictWriter(sys.stdout, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for rule, rows in results:
            for row in rows[:limit] if limit else rows:
                writer.writerow({"heuristic_name": rule["name"], **{field: stringify(field_value(row, field)) for field in DEFAULT_FIELDS}})
        return
    for index, (rule, rows) in enumerate(results):
        if index:
            print()
        print(f"== {rule['name']} ({len(rows)} result(s)) ==")
        selected = rows[:limit] if limit else rows
        if output_format == "names":
            for row in selected:
                print(row["function_name"])
        else:
            output_rows(selected, rule.get("fields") or DEFAULT_FIELDS, "table")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and maintain the GML function catalog.")
    parser.add_argument("--db-dir", type=Path, default=DB_DIR)
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    parser.add_argument("--facts", type=Path, default=FACTS_PATH)
    parser.add_argument("--gmlspec", type=Path, default=GMLSPEC_PATH)
    parser.add_argument("--normalize", action="store_true", help="Report source files that need normalization.")
    parser.add_argument("--write", action="store_true", help="Write normalization changes. Implies --normalize.")
    parser.add_argument("--heuristics", action="store_true", help="Print heuristic review queues.")
    parser.add_argument("--heuristics-file", type=Path, default=HEURISTICS_PATH)
    parser.add_argument("--heuristic", action="append", default=[], help="Run one named heuristic.")
    parser.add_argument("--list-heuristics", action="store_true")
    parser.add_argument("--format", choices=["summary", "table", "json", "csv", "names"], default="summary")
    parser.add_argument("--limit", type=int, default=25, help="Rows per heuristic outside summary mode. 0 means unlimited.")
    parser.add_argument("--fail-on-results", action="store_true")
    args = parser.parse_args()

    try:
        contract = load_contract(args.schema)
        facts = load_facts(args.facts)
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    reporter = validate_catalog(args.db_dir, contract, facts, args.gmlspec)
    for warning in reporter.warnings:
        print(f"warning: {warning}")
    for error in reporter.errors:
        print(f"error: {error}", file=sys.stderr)
    if reporter.errors:
        print(f"Validation failed: {len(reporter.errors)} error(s).", file=sys.stderr)
        return 1
    print(f"Validation passed: {len(iter_db_files(args.db_dir))} file(s) checked.")

    if args.normalize or args.write:
        changed = normalize_catalog(args.db_dir, contract, args.write)
        print(f"{'Normalized' if args.write else 'Normalization needed for'} {len(changed)} file(s).")
        for path in changed:
            print(path.as_posix())

    if args.heuristics or args.heuristic or args.list_heuristics:
        try:
            heuristics = load_heuristics(args.heuristics_file)
            validate_heuristics(heuristics)
            if args.heuristic:
                requested = set(args.heuristic)
                heuristics = [rule for rule in heuristics if rule["name"] in requested]
                missing = requested - {rule["name"] for rule in heuristics}
                if missing:
                    raise ValueError(f"unknown heuristic(s): {', '.join(sorted(missing))}")
        except Exception as exc:
            print(f"Heuristic error: {exc}", file=sys.stderr)
            return 1
        if args.list_heuristics:
            for heuristic in heuristics:
                print(f"{heuristic['name']}: {heuristic.get('description', '')}")
            return 0
        results = run_heuristics(heuristics, args.db_dir, contract, args.gmlspec)
        print_heuristics(results, args.format, args.limit)
        if args.fail_on_results and any(rows for _rule, rows in results):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
