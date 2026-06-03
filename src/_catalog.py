#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DB_DIR = REPO_ROOT / "db"
BUILD_DIR = REPO_ROOT / "build"
SCHEMA_PATH = REPO_ROOT / "src" / "schema" / "fields.json"
GMLSPEC_PATH = REPO_ROOT / "src" / "resources" / "GmlSpec.xml"
FACTS_PATH = REPO_ROOT / "src" / "rules" / "facts.json"
HEURISTICS_PATH = REPO_ROOT / "src" / "rules" / "heuristics.json"
DEFAULT_FIELDS = [
    "function_name",
    "db_path",
    "category_path",
    "param_count",
    "return_type",
    "returns_value",
    "is_getter",
    "is_setter",
    "is_global_reflection",
    "is_asset_reflection",
    "is_safe",
    "is_sandboxed",
]
NO_VALUE_RETURN_TYPES = {"", "undefined", "void", "n/a", "na"}
OPERATORS = ("!~=", "~=", "!~", "!=", ">=", "<=", "~", "=", ">", "<")
Expression = Callable[[dict[str, Any]], bool]


def load_json(path: Path) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        duplicates = []
        for key, value in pairs:
            if key in result:
                duplicates.append(key)
            result[key] = value
        if duplicates:
            duplicate_list = ", ".join(sorted(set(duplicates)))
            raise ValueError(f"{path.as_posix()}: duplicate JSON key(s): {duplicate_list}")
        return result

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=reject_duplicate_keys)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=4, ensure_ascii=True)
        handle.write("\n")


def iter_db_files(db_dir: Path = DB_DIR) -> list[Path]:
    return sorted(db_dir.rglob("*.json"))


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def load_contract(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    contract = load_json(path)
    order = contract.get("record_key_order")
    fields = contract.get("fields")
    if not isinstance(order, list) or not all(isinstance(key, str) for key in order):
        raise ValueError(f"{path}: record_key_order must be a list of strings")
    if not isinstance(fields, dict):
        raise ValueError(f"{path}: fields must be an object")
    if set(order) != set(fields):
        missing_from_order = sorted(set(fields) - set(order))
        missing_from_fields = sorted(set(order) - set(fields))
        raise ValueError(
            f"{path}: record_key_order and fields differ "
            f"(missing_from_order={missing_from_order}, missing_from_fields={missing_from_fields})"
        )
    for field_name, field in fields.items():
        if not isinstance(field, dict):
            raise ValueError(f"{path}: field {field_name!r} must be an object")
        if field.get("required") is not True and field.get("source_only") is not True and "default" not in field:
            raise ValueError(f"{path}: optional field {field_name!r} must define a default")
    return contract


def resolve_record(
    record: dict[str, Any],
    contract: dict[str, Any],
    include_source_only: bool = True,
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    fields = contract["fields"]
    for field_name in contract["record_key_order"]:
        if fields[field_name].get("source_only") is True and not include_source_only:
            continue
        if field_name in record:
            resolved[field_name] = record[field_name]
        elif fields[field_name].get("required") is True:
            raise KeyError(field_name)
        elif fields[field_name].get("source_only") is not True:
            resolved[field_name] = fields[field_name]["default"]
    return resolved


def compact_record(record: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    fields = contract["fields"]
    for field_name in contract["record_key_order"]:
        if field_name not in record:
            continue
        field = fields[field_name]
        optional_default = (
            field.get("required") is not True
            and field.get("source_only") is not True
            and record[field_name] == field.get("default")
        )
        if optional_default:
            continue
        compacted[field_name] = record[field_name]
    return compacted


def parse_xml_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() == "true"


def text_content(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def load_gmlspec(path: Path = GMLSPEC_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    root = ET.parse(path).getroot()
    functions_node = root.find("Functions")
    if functions_node is None:
        raise ValueError(f"{path.as_posix()}: missing Functions node")

    functions: dict[str, dict[str, Any]] = {}
    for function_node in functions_node.findall("Function"):
        name = function_node.get("Name")
        if not name:
            continue
        parameters = []
        for parameter_node in function_node.findall("Parameter"):
            parameters.append(
                {
                    "name": parameter_node.get("Name", ""),
                    "type": parameter_node.get("Type", ""),
                    "optional": parse_xml_bool(parameter_node.get("Optional")) is True,
                    "description": text_content(parameter_node),
                }
            )
        return_type = function_node.get("ReturnType", "")
        functions[name] = {
            "spec_exists": True,
            "spec_deprecated": parse_xml_bool(function_node.get("Deprecated")),
            "spec_pure": parse_xml_bool(function_node.get("Pure")),
            "return_type": return_type,
            "returns_value": return_type.strip().lower() not in NO_VALUE_RETURN_TYPES,
            "param_count": len(parameters),
            "required_param_count": sum(1 for parameter in parameters if not parameter["optional"]),
            "optional_param_count": sum(1 for parameter in parameters if parameter["optional"]),
            "param_names": [parameter["name"] for parameter in parameters],
            "param_types": [parameter["type"] for parameter in parameters],
            "params": parameters,
            "description": text_content(function_node.find("Description")),
        }
    return functions


def load_db_records(
    db_dir: Path,
    contract: dict[str, Any],
    include_source_only: bool = True,
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in iter_db_files(db_dir):
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        try:
            db_path = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            db_path = path.as_posix()
        for function_name, record in data.items():
            records[function_name] = {
                "function_name": function_name,
                "db_exists": True,
                "db_path": db_path,
                **resolve_record(record, contract, include_source_only=include_source_only),
            }
    return records


def join_records(
    db_records: dict[str, dict[str, Any]],
    spec_records: dict[str, dict[str, Any]],
    source: str,
) -> list[dict[str, Any]]:
    if source == "db":
        names = set(db_records)
    elif source == "spec":
        names = set(spec_records)
    else:
        names = set(db_records) | set(spec_records)
    rows = []
    for name in sorted(names):
        row = {"function_name": name, "db_exists": False, "spec_exists": False}
        row.update(spec_records.get(name, {}))
        row.update(db_records.get(name, {}))
        rows.append(row)
    return rows


def load_rows(
    db_dir: Path = DB_DIR,
    contract: dict[str, Any] | None = None,
    gmlspec_path: Path = GMLSPEC_PATH,
    source: str = "all",
) -> list[dict[str, Any]]:
    contract = contract or load_contract()
    db_records = load_db_records(db_dir, contract)
    spec_records = load_gmlspec(gmlspec_path)
    return join_records(db_records, spec_records, source)


def parse_literal(value: str) -> Any:
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ",".join(stringify(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    return str(value)


def field_value(row: dict[str, Any], field: str) -> Any:
    if field in {"name", "function"}:
        return row.get("function_name")
    return row.get(field)


def is_truthy(value: Any) -> bool:
    return value is not None and value is not False and value != "" and value != []


def compile_expression(expression: str) -> Expression:
    expression = expression.strip()
    if not expression:
        raise ValueError("empty expression")
    for operator in OPERATORS:
        if operator not in expression:
            continue
        field, raw_expected = expression.split(operator, 1)
        field = field.strip()
        expected = parse_literal(raw_expected.strip())

        def matcher(row: dict[str, Any], field: str = field, operator: str = operator, expected: Any = expected) -> bool:
            actual = field_value(row, field)
            if operator == "~":
                return str(expected).lower() in stringify(actual).lower()
            if operator == "!~":
                return str(expected).lower() not in stringify(actual).lower()
            if operator == "~=":
                return re.search(str(expected), stringify(actual), re.IGNORECASE) is not None
            if operator == "!~=":
                return re.search(str(expected), stringify(actual), re.IGNORECASE) is None
            if operator == "=":
                return actual == expected
            if operator == "!=":
                return actual != expected
            try:
                actual_number = float(actual)
                expected_number = float(expected)
            except (TypeError, ValueError):
                return False
            if operator == ">":
                return actual_number > expected_number
            if operator == "<":
                return actual_number < expected_number
            if operator == ">=":
                return actual_number >= expected_number
            return actual_number <= expected_number

        return matcher
    if expression.startswith("!"):
        field = expression[1:].strip()
        return lambda row, field=field: not is_truthy(field_value(row, field))
    return lambda row, field=expression: is_truthy(field_value(row, field))


def row_matches(rule: dict[str, Any], row: dict[str, Any]) -> bool:
    required = [compile_expression(expression) for expression in rule.get("all", [])]
    alternatives = [compile_expression(expression) for expression in rule.get("any", [])]
    excluded = [compile_expression(expression) for expression in rule.get("none", [])]
    return (
        all(matcher(row) for matcher in required)
        and (not alternatives or any(matcher(row) for matcher in alternatives))
        and not any(matcher(row) for matcher in excluded)
    )


def apply_filters(
    rows: Iterable[dict[str, Any]],
    include: list[str],
    exclude: list[str],
) -> list[dict[str, Any]]:
    include_matchers = [compile_expression(expression) for expression in include]
    exclude_matchers = [compile_expression(expression) for expression in exclude]
    return [
        row for row in rows
        if all(matcher(row) for matcher in include_matchers)
        and not any(matcher(row) for matcher in exclude_matchers)
    ]


def output_rows(rows: list[dict[str, Any]], fields: list[str], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(rows, indent=2, ensure_ascii=True))
        return
    if output_format == "names":
        for row in rows:
            print(row["function_name"])
        return
    if output_format == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: stringify(field_value(row, field)) for field in fields})
        return
    rendered = [{field: stringify(field_value(row, field)) for field in fields} for row in rows]
    widths = {field: max([len(field), *(len(row[field]) for row in rendered)]) for field in fields}
    print("  ".join(field.ljust(widths[field]) for field in fields))
    print("  ".join("-" * widths[field] for field in fields))
    for row in rendered:
        print("  ".join(row[field].ljust(widths[field]) for field in fields))
