"""Pure processing: every source record produces exactly one result."""

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict

from .models import ProcessConfig


def process(dataset: Dict[str, Any], config: ProcessConfig) -> Dict[str, Any]:
    missing = {field.source for field in config.fields} - set(dataset["columns"])
    if missing:
        raise ValueError(f"Source columns do not exist: {', '.join(sorted(missing))}")
    records, audit, seen = [], [], {}
    for source in dataset["rows"]:
        cleaned, reasons, events = {}, [], []

        def event(field, before, after, reason, action="transform"):
            events.append(
                {
                    "row": source["row"],
                    "field": field,
                    "action": action,
                    "before": before,
                    "after": after,
                    "reason": reason,
                }
            )

        for issue in source["issues"]:
            reasons.append(issue)
            event("", None, None, issue, "reject")
        if all(value == "" for value in source["original"].values()):
            reasons.append("Entire source record is blank.")
            event("", None, None, reasons[-1], "reject")
        for rule in config.fields:
            value = source["original"][rule.source]
            for enabled, operation, reason in [
                (rule.trim, lambda v: v.strip(), "Removed surrounding whitespace."),
                (
                    rule.collapse_spaces,
                    lambda v: re.sub(r"\s+", " ", v),
                    "Collapsed repeated whitespace.",
                ),
                (
                    rule.casing != "preserve",
                    lambda v: v.lower() if rule.casing == "lower" else v.upper(),
                    f"Converted text to {rule.casing}case.",
                ),
            ]:
                if enabled:
                    updated = operation(value)
                    if updated != value:
                        event(rule.target, value, updated, reason)
                    value = updated
            if value == "" or value in config.null_markers:
                if value != "":
                    event(
                        rule.target,
                        value,
                        None,
                        "Converted an explicitly configured null marker to blank.",
                    )
                value = None
            if value is None:
                if rule.required:
                    reason = f"{rule.target}: a value is required."
                    reasons.append(reason)
                    event(rule.target, value, value, reason, "reject")
            else:
                error = None
                if rule.kind == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
                    error = "expected an email address such as name@example.com."
                elif rule.kind == "decimal":
                    native_exponent = rule.source in source.get(
                        "excel_numbers", {}
                    ) and re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)[eE][+-]?\d+", value)
                    if (
                        not re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)", value)
                        and not native_exponent
                    ):
                        error = "expected a plain decimal such as 1234.50, without currency symbols, commas, or exponents."
                    elif len(value) > 100:
                        error = "decimal values must be at most 100 characters."
                    else:
                        updated = format(Decimal(value), "f")
                        if updated != value:
                            event(
                                rule.target,
                                value,
                                updated,
                                (
                                    "Expanded a typed Excel number to decimal notation without rounding."
                                    if native_exponent
                                    else "Normalized decimal notation without rounding."
                                ),
                            )
                        value = updated
                elif rule.kind == "date":
                    format_label = {
                        "%Y-%m-%d": "YYYY-MM-DD",
                        "%m/%d/%Y": "MM/DD/YYYY",
                        "%d/%m/%Y": "DD/MM/YYYY",
                    }[rule.date_format]
                    pattern = {
                        "%Y-%m-%d": r"\d{4}-\d{2}-\d{2}",
                        "%m/%d/%Y": r"\d{2}/\d{2}/\d{4}",
                        "%d/%m/%Y": r"\d{2}/\d{2}/\d{4}",
                    }[rule.date_format]
                    try:
                        excel_date = source.get("excel_dates", {}).get(rule.source)
                        if excel_date:
                            updated = excel_date
                        else:
                            if not re.fullmatch(pattern, value):
                                raise ValueError()
                            updated = datetime.strptime(value, rule.date_format).date().isoformat()
                        if updated != value:
                            event(
                                rule.target,
                                value,
                                updated,
                                (
                                    "Converted an Excel date at midnight to YYYY-MM-DD."
                                    if excel_date
                                    else f"Converted date from {format_label} to YYYY-MM-DD."
                                ),
                            )
                        value = updated
                    except ValueError:
                        error = f"expected a valid calendar date in {format_label} format."
                if error:
                    reason = f"{rule.target}: {error}"
                    reasons.append(reason)
                    event(rule.target, value, value, reason, "reject")
            cleaned[rule.target] = value
        # Only otherwise valid rows reserve a duplicate key. Blank keys never collide.
        if not reasons and config.duplicate_keys:
            key = tuple(cleaned[field] for field in config.duplicate_keys)
            if all(value is not None for value in key):
                if key in seen:
                    reason = f"Duplicate key ({', '.join(config.duplicate_keys)}) matches source record {seen[key]}."
                    if config.duplicate_policy == "reject_later":
                        reasons.append(reason)
                    event(
                        ", ".join(config.duplicate_keys),
                        None,
                        None,
                        reason,
                        "reject" if config.duplicate_policy == "reject_later" else "duplicate_kept",
                    )
                else:
                    seen[key] = source["row"]
        status = "rejected" if reasons else "accepted"
        changed = any(item["action"] == "transform" for item in events)
        if not events:
            event("", None, None, "Passed all configured rules; values unchanged.", "accept")
        records.append(
            {
                "row": source["row"],
                "status": status,
                "changed": changed,
                "original": source["original"],
                "cleaned": cleaned,
                "reasons": reasons,
                "events": events,
            }
        )
        audit.extend(events)
    accepted = sum(record["status"] == "accepted" for record in records)
    return {
        "summary": {
            "total": len(records),
            "accepted": accepted,
            "changed": sum(
                record["changed"] and record["status"] == "accepted" for record in records
            ),
            "rejected": len(records) - accepted,
            "audit_events": len(audit),
        },
        "records": records,
        "audit": audit,
    }
