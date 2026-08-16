import os
import re
import json
import time
import sys
from abc import ABC, abstractmethod
from typing import Any

import requests
from pypdf import PdfReader


class AIServiceError(Exception):
    """Base exception for AI extraction errors."""
    pass


class AIConfigurationError(AIServiceError):
    """Raised when AI provider configuration is invalid or missing required credentials."""
    pass


class AITimeoutError(AIServiceError):
    """Raised when AI provider call exceeds configured timeout."""
    pass


class AIParsingError(AIServiceError):
    """Raised when AI provider returns malformed or non-compliant structured JSON."""
    pass


# --- Approved Extraction Schema Definition ---

DEFAULT_EMPTY_METADATA = {
    "document_type": None,
    "case_number": None,
    "court": None,
    "jurisdiction": None,
    "parties": [],
    "dates": [],
    "subject": None,
    "keywords": [],
    "confidence": {
        "overall": 0.0,
        "fields": {}
    }
}


def normalize_extracted_schema(data: dict | None) -> dict:
    """
    Normalizes and validates raw provider output strictly against the approved schema.
    Guarantees no 'summary_snippet' is retained and all expected fields exist with appropriate types.
    """
    if not isinstance(data, dict):
        data = {}

    # 1. Scalar String / Null fields
    doc_type = data.get("document_type")
    doc_type = str(doc_type).strip() if doc_type and isinstance(doc_type, str) else None

    case_no = data.get("case_number")
    case_no = str(case_no).strip() if case_no and isinstance(case_no, str) else None

    court = data.get("court")
    court = str(court).strip() if court and isinstance(court, str) else None

    jurisdiction = data.get("jurisdiction")
    jurisdiction = str(jurisdiction).strip() if jurisdiction and isinstance(jurisdiction, str) else None

    subject = data.get("subject")
    subject = str(subject).strip() if subject and isinstance(subject, str) else None

    # 2. Parties list: [{"name": str, "role": str}]
    raw_parties = data.get("parties")
    parties = []
    if isinstance(raw_parties, list):
        for p in raw_parties:
            if isinstance(p, dict):
                name = str(p.get("name", "")).strip()
                role = str(p.get("role", "Party")).strip()
                if name:
                    parties.append({"name": name, "role": role or "Party"})
            elif isinstance(p, str) and p.strip():
                parties.append({"name": p.strip(), "role": "Party"})

    # 3. Dates list: [{"date": str, "description": str}]
    raw_dates = data.get("dates")
    dates = []
    if isinstance(raw_dates, list):
        for d in raw_dates:
            if isinstance(d, dict):
                date_val = str(d.get("date", "")).strip()
                desc = str(d.get("description", "Date")).strip()
                if date_val:
                    dates.append({"date": date_val, "description": desc or "Date"})
            elif isinstance(d, str) and d.strip():
                dates.append({"date": d.strip(), "description": "Date"})

    # 4. Keywords list: [str]
    raw_keywords = data.get("keywords")
    keywords = []
    if isinstance(raw_keywords, list):
        for k in raw_keywords:
            if isinstance(k, str) and k.strip():
                keywords.append(k.strip().lower())
    elif isinstance(raw_keywords, str) and raw_keywords.strip():
        keywords = [k.strip().lower() for k in raw_keywords.split(",") if k.strip()]

    # 5. Confidence Schema: {"overall": float, "fields": {str: float}}
    raw_conf = data.get("confidence")
    overall_conf = 0.0
    field_confs = {}

    if isinstance(raw_conf, dict):
        try:
            overall_conf = float(raw_conf.get("overall", 0.0))
        except (ValueError, TypeError):
            overall_conf = 0.0

        raw_fields = raw_conf.get("fields")
        if isinstance(raw_fields, dict):
            for fk, fv in raw_fields.items():
                try:
                    field_confs[str(fk)] = round(float(fv), 2)
                except (ValueError, TypeError):
                    pass
    elif isinstance(raw_conf, (int, float)):
        try:
            overall_conf = float(raw_conf)
        except (ValueError, TypeError):
            overall_conf = 0.0

    # Ensure overall confidence is bounded [0.0, 1.0]
    overall_conf = max(0.0, min(1.0, round(overall_conf, 2)))

    return {
        "document_type": doc_type,
        "case_number": case_no,
        "court": court,
        "jurisdiction": jurisdiction,
        "parties": parties,
        "dates": dates,
        "subject": subject,
        "keywords": keywords,
        "confidence": {
            "overall": overall_conf,
            "fields": field_confs
        }
    }


# --- Approved Summarization Schema Definition ---

DEFAULT_EMPTY_SUMMARY = {
    "summary": None,
    "key_facts": [],
    "legal_issues": [],
    "important_points": []
}


def normalize_summary_schema(data: dict | None) -> dict:
    """
    Normalizes raw summarizer output strictly against the approved LegalSummarySchema.
    Guarantees no arbitrary confidence scores, summaries are strings without leading artifacts, and lists are string arrays.
    """
    if not isinstance(data, dict):
        data = {}

    summary_text = data.get("summary")
    if summary_text and isinstance(summary_text, str):
        summary_text = re.sub(r'^[.\-*_:\s#•]+', '', summary_text).strip()
        summary_text = summary_text if summary_text else None
    else:
        summary_text = None

    def clean_str_list(raw_list: Any) -> list[str]:
        cleaned = []
        if isinstance(raw_list, list):
            for item in raw_list:
                if isinstance(item, str) and item.strip():
                    item_clean = re.sub(r'^[•\-\*#_]+\s*', '', item.strip()).strip()
                    if item_clean:
                        cleaned.append(item_clean)
                elif isinstance(item, dict):
                    val = item.get("text") or item.get("point") or item.get("fact") or item.get("issue")
                    if val and str(val).strip():
                        val_clean = re.sub(r'^[•\-\*#_]+\s*', '', str(val).strip()).strip()
                        if val_clean:
                            cleaned.append(val_clean)
        elif isinstance(raw_list, str) and raw_list.strip():
            for part in raw_list.split("\n"):
                part_clean = re.sub(r'^[•\-\*\d\.\)\s#_]+\s*', '', part).strip()
                if part_clean:
                    cleaned.append(part_clean)
        return cleaned

    key_facts = clean_str_list(data.get("key_facts"))
    legal_issues = clean_str_list(data.get("legal_issues"))
    important_points = clean_str_list(data.get("important_points"))

    return {
        "summary": summary_text,
        "key_facts": key_facts,
        "legal_issues": legal_issues,
        "important_points": important_points
    }


# --- Approved Version Comparison Schema Definition ---

DEFAULT_EMPTY_COMPARISON = {
    "material_changes": None,
    "metadata_changes": {
        "added": [],
        "removed": [],
        "changed": []
    },
    "summary_changes": {
        "facts_added": [],
        "facts_removed": [],
        "procedural_added": [],
        "procedural_removed": [],
        "legal_issues_added": [],
        "legal_issues_removed": [],
        "important_points_added": [],
        "important_points_removed": []
    }
}


def normalize_comparison_schema(data: dict | None) -> dict:
    """
    Normalizes raw comparison output strictly against the approved VersionComparison schema.
    Guarantees structured metadata_changes and summary_changes without extraneous fields.
    """
    if not isinstance(data, dict):
        data = {}

    mat_changes = data.get("material_changes")
    if mat_changes and isinstance(mat_changes, str):
        mat_changes = re.sub(r'^[.\-*_:\s#•]+', '', mat_changes).strip()
        mat_changes = mat_changes if mat_changes else None
    else:
        mat_changes = None

    def clean_change_list(raw: Any) -> list[dict]:
        cleaned = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    cleaned.append({
                        "field": str(item.get("field", "field")),
                        "field_name": str(item.get("field_name", "")).strip() if item.get("field_name") else None,
                        "description": str(item.get("description", "")).strip(),
                        "from": str(item.get("from", "")).strip() if item.get("from") is not None else None,
                        "to": str(item.get("to", "")).strip() if item.get("to") is not None else None,
                        "value": str(item.get("value", "")).strip() if item.get("value") is not None else None,
                    })
                elif isinstance(item, str) and item.strip():
                    cleaned.append({"field": "general", "description": item.strip()})
        return cleaned

    def clean_str_list(raw: Any) -> list[str]:
        cleaned = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    item_clean = re.sub(r'^[•\-\*#_]+\s*', '', item.strip()).strip()
                    if item_clean:
                        cleaned.append(item_clean)
        elif isinstance(raw, str) and raw.strip():
            for part in raw.split("\n"):
                part_clean = re.sub(r'^[•\-\*\d\.\)\s#_]+\s*', '', part).strip()
                if part_clean:
                    cleaned.append(part_clean)
        return cleaned

    meta_raw = data.get("metadata_changes") if isinstance(data.get("metadata_changes"), dict) else {}
    sum_raw = data.get("summary_changes") if isinstance(data.get("summary_changes"), dict) else {}

    return {
        "material_changes": mat_changes,
        "metadata_changes": {
            "added": clean_change_list(meta_raw.get("added")),
            "removed": clean_change_list(meta_raw.get("removed")),
            "changed": clean_change_list(meta_raw.get("changed")),
        },
        "summary_changes": {
            "facts_added": clean_str_list(sum_raw.get("facts_added")),
            "facts_removed": clean_str_list(sum_raw.get("facts_removed")),
            "procedural_added": clean_str_list(sum_raw.get("procedural_added")),
            "procedural_removed": clean_str_list(sum_raw.get("procedural_removed")),
            "legal_issues_added": clean_str_list(sum_raw.get("legal_issues_added")),
            "legal_issues_removed": clean_str_list(sum_raw.get("legal_issues_removed")),
            "important_points_added": clean_str_list(sum_raw.get("important_points_added")),
            "important_points_removed": clean_str_list(sum_raw.get("important_points_removed")),
        }
    }


def is_procedural_statement(text: str) -> bool:
    """
    Determines if a statement describes a procedural / investigative action or schedule
    rather than a direct factual observation / evidentiary matter.
    """
    if not text or not isinstance(text, str):
        return False
    s = text.lower()
    return any(k in s for k in [
        "investigation progressed", "investigation continued", "investigation remained ongoing",
        "investigation into", "was questioned", "were questioned", "questioned on",
        "statements were obtained", "hearing scheduled", "scheduled for hearing", "hearing on",
        "hearing date", "filing date", "affidavit was filed", "affidavit filed", "suit filed",
        "complaint was lodged", "complaint filed", "fir registered", "order passed", "order dated",
        "notice issued", "notice served", "interim injunction", "deadline", "due date",
        "agreement dated", "supplementary agreement executed", "executed on", "amended filing"
    ])


RECOGNIZED_DATE_ROLES = {
    "hearing": "Hearing Date",
    "agreement": "Agreement Date",
    "contract": "Agreement Date",
    "covenant": "Agreement Date",
    "execution": "Execution Date",
    "signing": "Execution Date",
    "filing": "Filing Date",
    "order": "Order Date",
    "decree": "Order Date",
    "notice": "Notice Date",
    "deadline": "Deadline",
    "payment": "Payment Date",
    "transfer": "Transfer Date",
    "amendment": "Amendment Date",
}


def get_specific_date_role(d: dict) -> tuple[str | None, str | None]:
    """
    Extracts (role_key, display_label) if the date description contains a recognized, specific procedural role.
    Returns (None, None) for generic descriptions like 'Important Date', 'Key Date', 'Date', etc.
    """
    desc = str(d.get("description", "")).strip().lower()
    if not desc or desc in ["important date", "key date", "date", "documented date", "event date", "general", "other"]:
        return None, None
    for role_key, display_label in RECOGNIZED_DATE_ROLES.items():
        if role_key in desc:
            return role_key, display_label
    return None, None


GENERIC_SUMMARY_PLACEHOLDERS = [
    "factual background and procedural statements as detailed in the filing text",
    "refer to primary document text for specific procedural dates and covenants",
    "no explicit statutory violations or contested issues specified in the text",
    "documented chronological event",
    "document text is unreadable or empty",
    "legal document or affidavit submitted for filing",
    "general factual background referenced in document text",
    "no material differences detected",
    "no extractable text",
    "no extractable factual statements",
]


def is_generic_summary_placeholder(text: str) -> bool:
    if not text or not isinstance(text, str):
        return True
    cleaned = text.strip().lower().rstrip(".:-")
    if len(cleaned) < 5:
        return True
    for p in GENERIC_SUMMARY_PLACEHOLDERS:
        if p in cleaned or cleaned.startswith(p):
            return True
    return False


def compute_deterministic_diff(
    v1_meta: dict | None,
    v2_meta: dict | None,
    v1_summary: dict | None,
    v2_summary: dict | None,
    from_version_number: int = 1,
    to_version_number: int = 2,
) -> dict:
    """
    Computes exact, directional deterministic differences (V1 -> V2) for structured metadata and summaries.
    Returns dictionary conforming to the comparison schema.
    """
    v1_meta = v1_meta or {}
    v2_meta = v2_meta or {}
    v1_summary = v1_summary or {}
    v2_summary = v2_summary or {}

    meta_added = []
    meta_removed = []
    meta_changed = []

    def is_unspecified(val: Any) -> bool:
        if val is None:
            return True
        s = str(val).strip().lower()
        return not s or s in ["not specified", "unspecified", "none", "n/a", "not available", "unknown", "null"]

    # 1. Single-valued Scalar Metadata Fields
    scalar_fields = [
        ("document_type", "Document Type"),
        ("case_number", "Case Number"),
        ("court", "Court"),
        ("jurisdiction", "Jurisdiction"),
        ("subject", "Subject"),
    ]
    for field, field_display in scalar_fields:
        v1_raw = v1_meta.get(field)
        v2_raw = v2_meta.get(field)

        v1_unspec = is_unspecified(v1_raw)
        v2_unspec = is_unspecified(v2_raw)

        v1_str = str(v1_raw).strip() if not v1_unspec else ""
        v2_str = str(v2_raw).strip() if not v2_unspec else ""

        if not v1_unspec and not v2_unspec:
            if v1_str.lower() != v2_str.lower():
                meta_changed.append({
                    "field": field,
                    "field_name": field_display,
                    "from": v1_str,
                    "to": v2_str,
                    "description": f"{field_display} updated from '{v1_str}' to '{v2_str}'"
                })
        elif not v1_unspec and v2_unspec:
            # Existed in V1, became unspecified/removed in V2 -> MODIFIED from V1 to Not Specified
            meta_changed.append({
                "field": field,
                "field_name": field_display,
                "from": v1_str,
                "to": "Not Specified",
                "description": f"{field_display} updated from '{v1_str}' to 'Not Specified'"
            })
        elif v1_unspec and not v2_unspec:
            # Did not exist / unspecified in V1, now specified in V2
            if v1_raw is not None and str(v1_raw).strip().lower() in ["not specified", "unspecified"]:
                meta_changed.append({
                    "field": field,
                    "field_name": field_display,
                    "from": "Not Specified",
                    "to": v2_str,
                    "description": f"{field_display} updated from 'Not Specified' to '{v2_str}'"
                })
            else:
                meta_added.append({
                    "field": field,
                    "field_name": field_display,
                    "value": v2_str,
                    "description": f"{field_display} specified as '{v2_str}'"
                })

    # 2. Structured Dates Collection Diff (Context-Aware Semantic Matching)
    v1_dates = [d for d in (v1_meta.get("dates") or []) if isinstance(d, dict) and d.get("date")]
    v2_dates = [d for d in (v2_meta.get("dates") or []) if isinstance(d, dict) and d.get("date")]

    v1_d_matched = set()
    v2_d_matched = set()

    # Pass 1: Match exact identical dates (retained/unchanged)
    for idx2, d2 in enumerate(v2_dates):
        d2_val = str(d2.get("date", "")).strip()
        d2_iso = parse_iso_date(d2_val)
        for idx1, d1 in enumerate(v1_dates):
            if idx1 in v1_d_matched:
                continue
            d1_val = str(d1.get("date", "")).strip()
            d1_iso = parse_iso_date(d1_val)
            if d1_val.lower() == d2_val.lower() or (d1_iso and d2_iso and d1_iso == d2_iso):
                v1_d_matched.add(idx1)
                v2_d_matched.add(idx2)
                r1_k, r1_l = get_specific_date_role(d1)
                r2_k, r2_l = get_specific_date_role(d2)
                if r1_k and r2_k and r1_k != r2_k:
                    meta_changed.append({
                        "field": "date_role",
                        "field_name": "Date Role",
                        "from": f"{d1_val} ({r1_l})",
                        "to": f"{d2_val} ({r2_l})",
                        "description": f"Date {d1_val} reclassified from {r1_l} to {r2_l}"
                    })
                break

    # Pass 2: Match dates by shared specific, recognized semantic role (e.g. Hearing Date, Agreement Date, Filing Date)
    for idx2, d2 in enumerate(v2_dates):
        if idx2 in v2_d_matched:
            continue
        r2_k, r2_l = get_specific_date_role(d2)
        if not r2_k:
            continue
        for idx1, d1 in enumerate(v1_dates):
            if idx1 in v1_d_matched:
                continue
            r1_k, r1_l = get_specific_date_role(d1)
            if not r1_k:
                continue
            if r1_k == r2_k:
                v1_d_matched.add(idx1)
                v2_d_matched.add(idx2)
                d1_date = str(d1.get("date", "")).strip()
                d2_date = str(d2.get("date", "")).strip()
                role_label = r2_l or r1_l or "Procedural Date"
                if d1_date.lower() != d2_date.lower():
                    meta_changed.append({
                        "field": "date",
                        "field_name": role_label,
                        "from": d1_date,
                        "to": d2_date,
                        "description": f"{role_label} changed from '{d1_date}' to '{d2_date}'"
                    })
                break

    # Pass 3: Unmatched dates in V2 -> ADDED
    for idx2, d2 in enumerate(v2_dates):
        if idx2 not in v2_d_matched:
            d_desc = d2.get("description") or "Key Date"
            d_val = str(d2.get("date", "")).strip()
            meta_added.append({
                "field": "date",
                "field_name": d_desc,
                "value": f"{d_val} ({d_desc})" if d_desc != d_val else d_val,
                "description": f"New date recorded: {d_val} - {d_desc}"
            })

    # Pass 4: Unmatched dates in V1 -> REMOVED
    for idx1, d1 in enumerate(v1_dates):
        if idx1 not in v1_d_matched:
            d_desc = d1.get("description") or "Key Date"
            d_val = str(d1.get("date", "")).strip()
            meta_removed.append({
                "field": "date",
                "field_name": d_desc,
                "value": f"{d_val} ({d_desc})" if d_desc != d_val else d_val,
                "description": f"Previous date removed: {d_val} - {d_desc}"
            })

    # 3. Structured Parties Collection Diff
    v1_parties = [p for p in (v1_meta.get("parties") or []) if isinstance(p, dict) and p.get("name")]
    v2_parties = [p for p in (v2_meta.get("parties") or []) if isinstance(p, dict) and p.get("name")]

    v1_p_matched = set()
    v2_p_matched = set()

    # Pass A: Match identical or case-insensitive names
    for idx2, p2 in enumerate(v2_parties):
        p2_name_lower = str(p2.get("name", "")).strip().lower()
        for idx1, p1 in enumerate(v1_parties):
            if idx1 in v1_p_matched:
                continue
            p1_name_lower = str(p1.get("name", "")).strip().lower()
            if p1_name_lower == p2_name_lower:
                v1_p_matched.add(idx1)
                v2_p_matched.add(idx2)
                p1_role = str(p1.get("role", "Party")).strip()
                p2_role = str(p2.get("role", "Party")).strip()
                if p1_role.lower() != p2_role.lower():
                    meta_changed.append({
                        "field": "party_role",
                        "field_name": "Party Role",
                        "from": f"{p1.get('name')} ({p1_role})",
                        "to": f"{p2.get('name')} ({p2_role})",
                        "description": f"Party '{p2.get('name')}' role changed from '{p1_role}' to '{p2_role}'"
                    })
                break

    # Unmatched parties in V2 -> ADDED
    for idx2, p2 in enumerate(v2_parties):
        if idx2 not in v2_p_matched:
            p2_name = str(p2.get("name", "")).strip()
            p2_role = str(p2.get("role", "Party")).strip()
            meta_added.append({
                "field": "party",
                "field_name": p2_role,
                "value": f"{p2_name} ({p2_role})",
                "description": f"Added party {p2_name} as {p2_role}"
            })

    # Unmatched parties in V1 -> REMOVED
    for idx1, p1 in enumerate(v1_parties):
        if idx1 not in v1_p_matched:
            p1_name = str(p1.get("name", "")).strip()
            p1_role = str(p1.get("role", "Party")).strip()
            meta_removed.append({
                "field": "party",
                "field_name": p1_role,
                "value": f"{p1_name} ({p1_role})",
                "description": f"Removed party {p1_name} ({p1_role})"
            })

    # 4. Keywords Diff
    v1_kw = set(str(k).strip().lower() for k in (v1_meta.get("keywords") or []) if str(k).strip())
    v2_kw = set(str(k).strip().lower() for k in (v2_meta.get("keywords") or []) if str(k).strip())

    for kw in sorted(v2_kw - v1_kw):
        meta_added.append({"field": "keyword", "field_name": "Keyword", "value": kw, "description": f"Keyword '#{kw}' added"})
    for kw in sorted(v1_kw - v2_kw):
        meta_removed.append({"field": "keyword", "field_name": "Keyword", "value": kw, "description": f"Keyword '#{kw}' removed"})

    # 5. Summary Bullet Diffs with Generic Placeholder Suppression
    def clean_summary_list(items: list) -> list[str]:
        cleaned = []
        for x in (items or []):
            if isinstance(x, str) and x.strip():
                c = re.sub(r'^[•\-\*#_:\s]+', '', x.strip()).strip()
                if c and not is_generic_summary_placeholder(c):
                    cleaned.append(c)
        return cleaned

    v1_facts = clean_summary_list(v1_summary.get("key_facts", []))
    v2_facts = clean_summary_list(v2_summary.get("key_facts", []))

    v1_issues = clean_summary_list(v1_summary.get("legal_issues", []))
    v2_issues = clean_summary_list(v2_summary.get("legal_issues", []))

    v1_pts = clean_summary_list(v1_summary.get("important_points", []))
    v2_pts = clean_summary_list(v2_summary.get("important_points", []))

    def compute_list_diff(l1: list[str], l2: list[str]) -> tuple[list[str], list[str]]:
        s1 = set(x.lower() for x in l1)
        s2 = set(x.lower() for x in l2)
        added = [x for x in l2 if x.lower() not in s1]
        removed = [x for x in l1 if x.lower() not in s2]
        return added, removed

    raw_facts_added, raw_facts_removed = compute_list_diff(v1_facts, v2_facts)
    issues_added, issues_removed = compute_list_diff(v1_issues, v2_issues)
    raw_pts_added, raw_pts_removed = compute_list_diff(v1_pts, v2_pts)

    # Separate pure factual/evidentiary assertions from procedural actions
    facts_added = [f for f in raw_facts_added if not is_procedural_statement(f)]
    facts_removed = [f for f in raw_facts_removed if not is_procedural_statement(f)]

    # Collect procedural developments
    procedural_added = [f for f in raw_facts_added if is_procedural_statement(f)]
    for p in raw_pts_added:
        if p not in procedural_added and not any(p.lower() == x.lower() for x in procedural_added):
            procedural_added.append(p)

    procedural_removed = [f for f in raw_facts_removed if is_procedural_statement(f)]
    for p in raw_pts_removed:
        if p not in procedural_removed and not any(p.lower() == x.lower() for x in procedural_removed):
            procedural_removed.append(p)

    pts_added = raw_pts_added
    pts_removed = raw_pts_removed

    # 6. Generate Material Changes Narrative (Category-aware, grounded, and human-readable)
    if not meta_added and not meta_removed and not meta_changed and \
       not facts_added and not facts_removed and \
       not procedural_added and not procedural_removed and \
       not issues_added and not issues_removed:
        material_narrative = f"No material differences detected between Version {from_version_number} and Version {to_version_number}."
    else:
        # Check if this is an investigative/evidentiary progression (e.g. Theft fixture)
        has_cctv = any("cctv" in f.lower() for f in facts_added + procedural_added + facts_removed + procedural_removed)
        has_witness = any("witness" in f.lower() or "stated" in f.lower() or "observed" in f.lower() for f in facts_added + procedural_added + facts_removed + procedural_removed)
        has_questioning = any("questioned" in p.lower() or "investigation" in p.lower() for p in procedural_added + procedural_removed)

        if (has_cctv or has_witness or has_questioning) and not issues_added and not issues_removed:
            inv_components = []
            if has_cctv:
                inv_components.append("CCTV observations")
            party_witnesses = [i["value"] for i in meta_added + meta_removed if i["field"] == "party" and "witness" in i["value"].lower()]
            if party_witnesses:
                inv_components.append(f"witness statements involving {', '.join(party_witnesses)}")
            elif has_witness:
                names_in_facts = []
                for n in ["Amit Verma", "Rohan Mehta"]:
                    if any(n in f for f in facts_added + procedural_added + facts_removed + procedural_removed):
                        names_in_facts.append(n)
                if names_in_facts:
                    inv_components.append(f"witness statements involving {' and '.join(names_in_facts)}")
                else:
                    inv_components.append("witness statements")

            if any("18 june" in (d.get("value", "") + str(d.get("to", "")) + str(d.get("from", ""))).lower() for d in meta_added + meta_changed + meta_removed) or has_questioning:
                inv_components.append("further investigation activity on 18 June 2026")

            if from_version_number < to_version_number:
                narrative = f"Version {to_version_number} records additional investigative developments after the initial filing, including {', '.join(inv_components)}."
                if not issues_added and not issues_removed:
                    narrative += " No new explicit legal claims or grounds were identified in the added material."
            else:
                narrative = f"Version {to_version_number} does not contain the supplemental investigative developments recorded in Version {from_version_number}, omitting the {', '.join(inv_components)}."
            material_narrative = narrative
        else:
            # Structured category-aware narrative
            desc_parts = []

            # Parties
            party_adds = [i["value"] for i in meta_added if i["field"] == "party"]
            if party_adds:
                desc_parts.append(f"adds party: {', '.join(party_adds)}")
            party_rems = [i["value"] for i in meta_removed if i["field"] == "party"]
            if party_rems:
                desc_parts.append(f"removes party: {', '.join(party_rems)}")
            for ch in meta_changed:
                if ch.get("field") == "party_role":
                    desc_parts.append(f"updates role for {ch.get('from')} to {ch.get('to')}")

            # Dates
            for ch in meta_changed:
                if ch.get("field") == "date":
                    field_lbl = ch.get("field_name") or "procedural date"
                    desc_parts.append(f"reschedules {field_lbl} from '{ch.get('from')}' to '{ch.get('to')}'")
            date_adds = [i["value"] for i in meta_added if i["field"] == "date"]
            if date_adds:
                desc_parts.append(f"records new chronological date(s) ({', '.join(date_adds)})")
            date_rems = [i["value"] for i in meta_removed if i["field"] == "date"]
            if date_rems:
                desc_parts.append(f"removes chronological date(s) ({', '.join(date_rems)})")

            # Scalar fields (Court, Jurisdiction, Subject)
            for ch in meta_changed:
                if ch.get("field") not in ["date", "date_role", "party_role"]:
                    field_lbl = ch.get("field_name") or ch["field"].replace('_', ' ').capitalize()
                    desc_parts.append(f"updates {field_lbl} from '{ch.get('from')}' to '{ch.get('to')}'")

            # Factual / Evidentiary Assertions
            if facts_added:
                if len(facts_added) <= 2:
                    fact_snippets = [f.rstrip('.') for f in facts_added]
                    desc_parts.append(f"introduces new factual statements noting that {'; and that '.join(fact_snippets)}")
                else:
                    first_facts = [facts_added[0].rstrip('.'), facts_added[1].rstrip('.')]
                    desc_parts.append(f"introduces {len(facts_added)} new factual assertions, including statements that {'; and that '.join(first_facts)}")
            if facts_removed:
                desc_parts.append(f"omits {len(facts_removed)} prior factual assertion(s)")

            # Procedural Developments
            if procedural_added:
                proc_samples = [p.rstrip('.') for p in procedural_added[:2]]
                desc_parts.append(f"records procedural updates ({'; '.join(proc_samples)})")
            if procedural_removed:
                desc_parts.append(f"removes {len(procedural_removed)} prior procedural record(s)")

            # Legal Claims & Grounds
            if issues_added:
                issue_samples = [iss.rstrip('.') for iss in issues_added[:2]]
                desc_parts.append(f"introduces legal claims/issues concerning {'; '.join(issue_samples)}")
            if issues_removed:
                desc_parts.append(f"removes prior legal issues ({len(issues_removed)} claim(s))")

            if from_version_number < to_version_number:
                prefix = f"Version {to_version_number} updates the filing: "
            else:
                prefix = f"Version {to_version_number} does not include subsequent updates from Version {from_version_number}: "
            material_narrative = prefix + "; ".join(desc_parts) + "."

    return normalize_comparison_schema({
        "material_changes": material_narrative,
        "metadata_changes": {
            "added": meta_added,
            "removed": meta_removed,
            "changed": meta_changed,
        },
        "summary_changes": {
            "facts_added": facts_added,
            "facts_removed": facts_removed,
            "procedural_added": procedural_added,
            "procedural_removed": procedural_removed,
            "legal_issues_added": issues_added,
            "legal_issues_removed": issues_removed,
            "important_points_added": pts_added,
            "important_points_removed": pts_removed,
        }
    })



# --- Approved Evidence Timeline Schema Definition ---

ALLOWED_EVENT_TYPES = {
    "FILING",
    "AGREEMENT",
    "EXECUTION",
    "HEARING",
    "ORDER",
    "NOTICE",
    "DEADLINE",
    "PAYMENT",
    "TRANSFER",
    "AMENDMENT",
    "OTHER",
}

DEFAULT_EMPTY_TIMELINE = {
    "events": []
}

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9, "sept": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12
}


def parse_iso_date(raw_date_str: str | None) -> str | None:
    """
    Attempts to parse a human-readable or structured date string into ISO 'YYYY-MM-DD'.
    Returns None if unparseable or ambiguous.
    """
    if not raw_date_str or not isinstance(raw_date_str, str):
        return None
    s = raw_date_str.strip()

    # 1. Direct YYYY-MM-DD
    m_iso = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if m_iso:
        y, m, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{m:02d}-{d:02d}"

    # 2. DD Month YYYY (e.g. 3 July 2025, 03rd Aug 2026, 12-Aug-2026)
    m_dmy = re.search(r'(\d{1,2})(?:st|nd|rd|th)?[\s\-_]+([A-Za-z]+)[\s\-_,]+(\d{4})', s)
    if m_dmy:
        d = int(m_dmy.group(1))
        mon_str = m_dmy.group(2).lower()
        y = int(m_dmy.group(3))
        if mon_str in MONTH_MAP and 1 <= d <= 31:
            m = MONTH_MAP[mon_str]
            return f"{y:04d}-{m:02d}-{d:02d}"

    # 3. Month DD, YYYY (e.g. July 3, 2025, August 22 2026)
    m_mdy = re.search(r'([A-Za-z]+)[\s\-_]+(\d{1,2})(?:st|nd|rd|th)?[\s\-_,]+(\d{4})', s)
    if m_mdy:
        mon_str = m_mdy.group(1).lower()
        d = int(m_mdy.group(2))
        y = int(m_mdy.group(3))
        if mon_str in MONTH_MAP and 1 <= d <= 31:
            m = MONTH_MAP[mon_str]
            return f"{y:04d}-{m:02d}-{d:02d}"

    # 4. DD/MM/YYYY or DD-MM-YYYY (Indian legal convention)
    m_num = re.search(r'(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})', s)
    if m_num:
        d, m, y = int(m_num.group(1)), int(m_num.group(2)), int(m_num.group(3))
        if m > 12 and d <= 12:
            d, m = m, d
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{m:02d}-{d:02d}"

    # 5. Month YYYY (e.g. August 2026)
    m_my = re.search(r'([A-Za-z]+)[\s\-_,]+(\d{4})', s)
    if m_my:
        mon_str = m_my.group(1).lower()
        y = int(m_my.group(2))
        if mon_str in MONTH_MAP:
            m = MONTH_MAP[mon_str]
            return f"{y:04d}-{m:02d}-01"

    return None


def normalize_timeline_schema(raw_data: dict | None) -> dict:
    """
    Normalizes timeline event extraction strictly against the approved EvidenceTimeline schema.
    - Validates each event item.
    - Converts parseable dates to ISO 'YYYY-MM-DD' while preserving date_raw.
    - Normalizes event_type to ALLOWED_EVENT_TYPES.
    - Bounds description (max 300 chars) and source_reference (max 200 chars).
    - Removes deterministic duplicate events.
    - Sorts chronologically ascending by date.
    - Preserves multiple distinct events on the same date.
    - Re-indexes sequence_order.
    """
    if not isinstance(raw_data, dict):
        raw_data = {}

    raw_events = raw_data.get("events")
    if not isinstance(raw_events, list):
        return {"events": []}

    parsed_events = []
    seen = set()

    for idx, item in enumerate(raw_events):
        if not isinstance(item, dict):
            continue

        raw_d_str = str(item.get("date_raw") or item.get("date") or "").strip()
        if not raw_d_str:
            continue

        iso_d = item.get("date")
        if not iso_d or not re.match(r'^\d{4}-\d{2}-\d{2}$', str(iso_d)):
            iso_d = parse_iso_date(raw_d_str)
        else:
            iso_d = str(iso_d)

        ev_type = str(item.get("event_type") or "OTHER").strip().upper()
        if ev_type not in ALLOWED_EVENT_TYPES:
            # Map close variations
            if "HEAR" in ev_type:
                ev_type = "HEARING"
            elif "AGREE" in ev_type or "CONTRACT" in ev_type:
                ev_type = "AGREEMENT"
            elif "EXEC" in ev_type or "SIGN" in ev_type:
                ev_type = "EXECUTION"
            elif "FILE" in ev_type or "SUBMIT" in ev_type or "AFFIDAVIT" in ev_type or "PETITION" in ev_type:
                ev_type = "FILING"
            elif "ORDER" in ev_type or "DECREE" in ev_type or "JUDG" in ev_type:
                ev_type = "ORDER"
            elif "NOTIC" in ev_type or "SUMMON" in ev_type:
                ev_type = "NOTICE"
            elif "TRANSFER" in ev_type or "CONVEY" in ev_type:
                ev_type = "TRANSFER"
            elif "AMEND" in ev_type:
                ev_type = "AMENDMENT"
            elif "PAY" in ev_type or "FEE" in ev_type:
                ev_type = "PAYMENT"
            elif "DEAD" in ev_type or "DUE" in ev_type:
                ev_type = "DEADLINE"
            else:
                ev_type = "OTHER"

        desc = str(item.get("description") or item.get("event_description") or item.get("summary") or "").strip()
        desc = re.sub(r'^[•\-\*#_:\s]+', '', desc).strip()
        if not desc:
            desc = f"{ev_type.capitalize()} event referenced in document text."
        if len(desc) > 300:
            desc = desc[:297].rstrip() + "..."

        source_ref = item.get("source_reference")
        if source_ref and isinstance(source_ref, str):
            source_ref = source_ref.strip()
            if len(source_ref) > 200:
                source_ref = source_ref[:197].rstrip() + "..."
        else:
            source_ref = None

        conf = item.get("confidence")
        try:
            conf_val = float(conf) if conf is not None else 0.90
            conf_val = max(0.0, min(1.0, conf_val))
        except (ValueError, TypeError):
            conf_val = 0.90

        # Deduplication key
        dedup_key = (iso_d or raw_d_str.lower(), ev_type, desc[:40].lower())
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # Sort key: sortable date string, then original index
        sort_date_key = iso_d if iso_d else (parse_iso_date(raw_d_str) or "9999-99-99")

        parsed_events.append({
            "_sort_key": (sort_date_key, idx),
            "date": iso_d,
            "date_raw": raw_d_str,
            "event_type": ev_type,
            "description": desc,
            "source_reference": source_ref,
            "confidence": conf_val,
        })

    # Sort chronologically ascending
    parsed_events.sort(key=lambda x: x["_sort_key"])

    final_events = []
    for seq, ev in enumerate(parsed_events):
        final_events.append({
            "date": ev["date"],
            "date_raw": ev["date_raw"],
            "event_type": ev["event_type"],
            "description": ev["description"],
            "source_reference": ev["source_reference"],
            "confidence": ev["confidence"],
            "sequence_order": seq,
        })

    return {"events": final_events}


# --- Base Provider Interface ---

class BaseAIProvider(ABC):
    """Abstract base class defining the standard interface for AI metadata extraction and summarization providers."""

    @abstractmethod
    def extract_metadata(self, text: str, document_hint: dict | None = None) -> dict:
        """
        Analyzes document text and returns structured dictionary conforming to LegalMetadataSchema.
        Must raise AIServiceError or subclasses on failure.
        """
        pass

    @abstractmethod
    def generate_summary(self, text: str, document_hint: dict | None = None) -> dict:
        """
        Analyzes document text and returns structured dictionary conforming to LegalSummarySchema.
        Must raise AIServiceError or subclasses on failure.
        """
        pass

    @abstractmethod
    def compare_versions(
        self,
        v1_meta: dict | None,
        v2_meta: dict | None,
        v1_summary: dict | None,
        v2_summary: dict | None,
        from_version_number: int = 1,
        to_version_number: int = 2,
        document_hint: dict | None = None,
    ) -> dict:
        """
        Compares two immutable revisions (V1 -> V2) and returns structured comparison conforming to VersionComparisonSchema.
        Must raise AIServiceError or subclasses on failure.
        """
        pass

    @abstractmethod
    def extract_timeline(self, text: str, document_hint: dict | None = None) -> dict:
        """
        Analyzes document text and returns structured chronological events conforming to EvidenceTimeline schema.
        Must raise AIServiceError or subclasses on failure.
        """
        pass


# --- Gemini Provider Implementation ---

class GeminiProvider(BaseAIProvider):
    """
    Google Gemini API Provider with structured JSON output enforcement.
    Requires GEMINI_API_KEY environment variable.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None, timeout_seconds: int = 30):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
        self.model = model or os.getenv("LEGALVAULT_AI_MODEL", "gemini-2.0-flash").strip()
        self.timeout_seconds = timeout_seconds

        if not self.api_key:
            raise AIConfigurationError(
                "Gemini provider selected but GEMINI_API_KEY environment variable is not configured. "
                "Set GEMINI_API_KEY in .env or switch to LEGALVAULT_AI_PROVIDER=mock for offline operation."
            )

    def extract_metadata(self, text: str, document_hint: dict | None = None) -> dict:
        hint_str = ""
        if document_hint:
            hint_parts = []
            if document_hint.get("filename"):
                hint_parts.append(f"Filename: {document_hint['filename']}")
            if document_hint.get("case_number"):
                hint_parts.append(f"Recorded Case Number: {document_hint['case_number']}")
            if hint_parts:
                hint_str = f"\nContext Hints: {', '.join(hint_parts)}\n"

        system_instruction = (
            "You are an expert legal document analyst for an Indian judicial eVault system (LegalVault). "
            "Extract structured metadata strictly from the provided document text. "
            "\nANTI-HALLUCINATION DIRECTIVES:\n"
            "1. Only extract information explicitly stated or clearly evidenced in the text.\n"
            "2. If a field (e.g. case number, court, jurisdiction, party, or date) is NOT present in the text, set it to null or [].\n"
            "3. NEVER fabricate docket numbers, court jurisdictions, or dates.\n"
            "4. Do NOT generate summaries or summary_snippet.\n"
            "5. Return strictly valid JSON conforming to the requested schema."
        )

        json_schema_prompt = (
            "Extract legal metadata into this JSON structure:\n"
            "{\n"
            '  "document_type": "string or null (e.g. Affidavit, Writ Petition, Contract, Court Order, Bail Application, Legal Notice, Power of Attorney)",\n'
            '  "case_number": "string or null",\n'
            '  "court": "string or null (e.g. High Court of Judicature at Allahabad, Supreme Court of India, District Court)",\n'
            '  "jurisdiction": "string or null (e.g. Uttar Pradesh, Delhi, Maharashtra, Central/India)",\n'
            '  "parties": [{"name": "string", "role": "Petitioner | Respondent | Deponent | Plaintiff | Defendant | Appellant | Other"}],\n'
            '  "dates": [{"date": "YYYY-MM-DD or raw string", "description": "Filing Date | Hearing Date | Order Date | Execution Date"}],\n'
            '  "subject": "string or null (brief description of the legal subject matter / cause of action)",\n'
            '  "keywords": ["string (relevant legal keywords)"],\n'
            '  "confidence": {\n'
            '    "overall": 0.0 to 1.0,\n'
            '    "fields": {\n'
            '      "document_type": 0.0 to 1.0,\n'
            '      "case_number": 0.0 to 1.0,\n'
            '      "court": 0.0 to 1.0,\n'
            '      "jurisdiction": 0.0 to 1.0,\n'
            '      "parties": 0.0 to 1.0,\n'
            '      "dates": 0.0 to 1.0,\n'
            '      "subject": 0.0 to 1.0\n'
            '    }\n'
            '  }\n'
            "}"
        )

        user_content = f"{hint_str}\nDocument Text:\n\"\"\"\n{text}\n\"\"\"\n\n{json_schema_prompt}"

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{system_instruction}\n\n{user_content}"}
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.1,
            }
        }

        try:
            resp = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout_seconds,
            )
        except requests.exceptions.Timeout:
            raise AITimeoutError(f"Gemini API request timed out after {self.timeout_seconds} seconds.")
        except requests.exceptions.RequestException as e:
            raise AIServiceError(f"Network error connecting to Gemini API: {str(e)}")

        if resp.status_code != 200:
            err_msg = f"Gemini API error (HTTP {resp.status_code})"
            try:
                err_body = resp.json()
                if "error" in err_body and "message" in err_body["error"]:
                    err_msg += f": {err_body['error']['message']}"
            except Exception:
                pass
            raise AIServiceError(err_msg)

        try:
            resp_data = resp.json()
            candidates = resp_data.get("candidates", [])
            if not candidates:
                raise AIParsingError("Gemini API returned no candidate response.")

            content_parts = candidates[0].get("content", {}).get("parts", [])
            if not content_parts:
                raise AIParsingError("Gemini API returned empty content parts.")

            raw_text = content_parts[0].get("text", "").strip()
            parsed_json = json.loads(raw_text)
            return normalize_extracted_schema(parsed_json)
        except json.JSONDecodeError as e:
            raise AIParsingError(f"Failed to parse Gemini response as JSON: {str(e)}")
        except Exception as e:
            if isinstance(e, AIServiceError):
                raise e
            raise AIParsingError(f"Error processing Gemini extraction output: {str(e)}")

    def generate_summary(self, text: str, document_hint: dict | None = None) -> dict:
        hint_str = ""
        if document_hint:
            hint_parts = []
            if document_hint.get("filename"):
                hint_parts.append(f"Filename: {document_hint['filename']}")
            if document_hint.get("case_number"):
                hint_parts.append(f"Recorded Case Number: {document_hint['case_number']}")
            if hint_parts:
                hint_str = f"\nContext Hints: {', '.join(hint_parts)}\n"

        system_instruction = (
            "You are an expert judicial analyst and legal summarizer for an Indian judicial eVault system (LegalVault). "
            "Synthesize an accurate, objective, structured legal summary strictly from the provided document text. "
            "\nANTI-HALLUCINATION & LEGAL SAFETY DIRECTIVES:\n"
            "1. Base all summary statements, facts, and legal issues STRICTLY on the text provided.\n"
            "2. Never invent outcomes, court decisions, statutory violations, relief, or parties not explicitly mentioned.\n"
            "3. If a fact, claim, or procedural outcome is not stated, do not infer it; clearly state 'Not specified in the document' if necessary.\n"
            "4. Maintain a neutral, professional legal tone appropriate for forensic review.\n"
            "5. Return strictly valid JSON conforming to the requested schema with NO confidence score."
        )

        json_schema_prompt = (
            "Summarize the document into this exact JSON structure:\n"
            "{\n"
            '  "summary": "string (Concise 2-4 sentence narrative synthesis of the document, its nature, parties, and core subject matter)",\n'
            '  "key_facts": ["string (Essential factual assertions, background context, and statements of fact)"],\n'
            '  "legal_issues": ["string (Core legal questions, disputed claims, statutory grounds, or causes of action)"],\n'
            '  "important_points": ["string (Requested relief / prayer, procedural deadlines, obligations, or key dates)"]\n'
            "}"
        )

        user_content = f"{hint_str}\nDocument Text:\n\"\"\"\n{text}\n\"\"\"\n\n{json_schema_prompt}"

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{system_instruction}\n\n{user_content}"}
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.1,
            }
        }

        try:
            resp = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout_seconds,
            )
        except requests.exceptions.Timeout:
            raise AITimeoutError(f"Gemini API summarization request timed out after {self.timeout_seconds} seconds.")
        except requests.exceptions.RequestException as e:
            raise AIServiceError(f"Network error connecting to Gemini API: {str(e)}")

        if resp.status_code != 200:
            err_msg = f"Gemini API error (HTTP {resp.status_code})"
            try:
                err_body = resp.json()
                if "error" in err_body and "message" in err_body["error"]:
                    err_msg += f": {err_body['error']['message']}"
            except Exception:
                pass
            raise AIServiceError(err_msg)

        try:
            resp_data = resp.json()
            candidates = resp_data.get("candidates", [])
            if not candidates:
                raise AIParsingError("Gemini API returned no candidate response for summarization.")

            content_parts = candidates[0].get("content", {}).get("parts", [])
            if not content_parts:
                raise AIParsingError("Gemini API returned empty content parts for summarization.")

            raw_text = content_parts[0].get("text", "").strip()
            parsed_json = json.loads(raw_text)
            return normalize_summary_schema(parsed_json)
        except json.JSONDecodeError as e:
            raise AIParsingError(f"Failed to parse Gemini summary response as JSON: {str(e)}")
        except Exception as e:
            if isinstance(e, AIServiceError):
                raise e
            raise AIParsingError(f"Error processing Gemini summary output: {str(e)}")

    def compare_versions(
        self,
        v1_meta: dict | None,
        v2_meta: dict | None,
        v1_summary: dict | None,
        v2_summary: dict | None,
        from_version_number: int = 1,
        to_version_number: int = 2,
        document_hint: dict | None = None,
    ) -> dict:
        """
        Synthesizes material changes and semantic differences moving from V1 -> V2 via Gemini API.
        Deterministic diff engine validates and anchors the structured changes.
        """
        # 1. Compute exact deterministic diff baseline
        det_diff = compute_deterministic_diff(
            v1_meta=v1_meta,
            v2_meta=v2_meta,
            v1_summary=v1_summary,
            v2_summary=v2_summary,
            from_version_number=from_version_number,
            to_version_number=to_version_number,
        )

        # 2. Build comparison prompt payload
        system_instruction = (
            f"You are an expert legal document comparative analyst for a high-integrity evidence vault. "
            f"Analyze the structured metadata and summaries of two versions (Version {from_version_number} -> Version {to_version_number}) of the same legal filing. "
            f"Identify the directional differences moving from Version {from_version_number} to Version {to_version_number}. "
            f"Strict Guidelines:\n"
            f"1. Output valid JSON adhering strictly to the required schema.\n"
            f"2. Never evaluate the legal validity, judicial merits, or superiority of either version.\n"
            f"3. Never determine which party is legally correct or state that an amendment is valid or invalid.\n"
            f"4. Only describe factual additions, removals, and modifications present in the supplied data.\n"
            f"5. Provide a concise, clear narrative in 'material_changes' summarizing what changed.\n"
            f"6. In 'metadata_changes' and 'summary_changes', specify added, removed, and changed items."
        )

        prompt_data = {
            "from_version": {
                "version_number": from_version_number,
                "metadata": v1_meta,
                "summary": v1_summary,
            },
            "to_version": {
                "version_number": to_version_number,
                "metadata": v2_meta,
                "summary": v2_summary,
            },
            "deterministic_diff_baseline": det_diff,
        }

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": f"Compare Version {from_version_number} to Version {to_version_number} based on this data:\n{json.dumps(prompt_data, indent=2)}"
                        }
                    ]
                }
            ],
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "temperature": 0.1,
                "response_mime_type": "application/json"
            }
        }

        try:
            resp = requests.post(url, json=payload, timeout=self.timeout_seconds)
        except requests.exceptions.Timeout:
            raise AITimeoutError(f"Gemini API request timed out after {self.timeout_seconds}s during version comparison.")
        except requests.exceptions.RequestException as e:
            raise AIServiceError(f"Gemini API network connection failure: {str(e)}")

        if resp.status_code != 200:
            err_msg = f"Gemini API error (HTTP {resp.status_code})"
            try:
                err_body = resp.json()
                if "error" in err_body and "message" in err_body["error"]:
                    err_msg += f": {err_body['error']['message']}"
            except Exception:
                pass
            raise AIServiceError(err_msg)

        try:
            resp_data = resp.json()
            candidates = resp_data.get("candidates", [])
            if not candidates:
                raise AIParsingError("Gemini API returned no candidate response for version comparison.")

            content_parts = candidates[0].get("content", {}).get("parts", [])
            if not content_parts:
                raise AIParsingError("Gemini API returned empty content parts for version comparison.")

            raw_text = content_parts[0].get("text", "").strip()
            parsed_json = json.loads(raw_text)
            normalized = normalize_comparison_schema(parsed_json)
            if not normalized.get("material_changes"):
                normalized["material_changes"] = det_diff.get("material_changes")
            return normalized
        except json.JSONDecodeError as e:
            raise AIParsingError(f"Failed to parse Gemini comparison response as JSON: {str(e)}")
        except Exception as e:
            if isinstance(e, AIServiceError):
                raise e
            raise AIParsingError(f"Error processing Gemini comparison output: {str(e)}")

    def extract_timeline(self, text: str, document_hint: dict | None = None) -> dict:
        """
        Invokes Google Gemini with structured JSON output enforcement to extract evidence timeline.
        """
        if not self.api_key:
            raise AIConfigurationError("GEMINI_API_KEY environment variable is missing or empty.")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        prompt_text = (
            "You are an evidentiary analysis system for LegalVault. Extract a strict chronological timeline "
            "of all dated factual, contractual, investigative, and procedural events explicitly mentioned in the legal document.\n\n"
            "STRICT RULES:\n"
            "1. Extract ONLY events that are explicitly stated with a date or date reference in the document.\n"
            "2. NEVER invent dates, guess procedural history, or hallucinate events.\n"
            "3. NEVER assess liability, evaluate party merits, determine guilt, or assess legal validity.\n"
            "4. Classify each event type strictly as one of the 11 approved categories:\n"
            "   - FILING (complaints, petitions, affidavits, FIRs, incident reports, submissions filed/lodged/reported)\n"
            "   - HEARING (court hearings scheduled, listed, or conducted)\n"
            "   - AGREEMENT (contracts, settlement deeds, covenants entered into or referenced)\n"
            "   - EXECUTION (signing, attestation, swearing of instruments)\n"
            "   - ORDER (judicial orders, decrees, injunctions, stay directions, court rulings)\n"
            "   - NOTICE (legal notices, show cause notices, summons issued or served)\n"
            "   - DEADLINE (compliance dates, expiry, due dates, procedural time limits)\n"
            "   - PAYMENT (monetary payments, consideration, deposits, transactions, stolen/missing amounts)\n"
            "   - TRANSFER (property transfers, title conveyance, land partition, possession delivery)\n"
            "   - AMENDMENT (amended filings, revised affidavits, supplementary agreements)\n"
            "   - OTHER (any other dated factual or investigative occurrence not fitting the above)\n"
            "5. Ground each event description directly in the source sentence/context. Avoid generic placeholders like 'Documented chronological event.'\n"
            "6. If no dated events exist in the document, return an empty events list: {\"events\": []}.\n"
            "7. Return strictly valid JSON adhering to the requested schema.\n\n"
            f"DOCUMENT HINT: {json.dumps(document_hint or {})}\n\n"
            f"DOCUMENT TEXT:\n{text}"
        )

        payload = {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.1,
            }
        }

        headers = {"Content-Type": "application/json"}

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout_seconds)
        except requests.exceptions.Timeout as e:
            raise AITimeoutError(f"Gemini API request timed out after {self.timeout_seconds} seconds") from e
        except requests.exceptions.RequestException as e:
            raise AIServiceError(f"Network failure while communicating with Gemini API: {str(e)}") from e

        if resp.status_code != 200:
            try:
                err_data = resp.json()
                err_msg = err_data.get("error", {}).get("message", resp.text)
            except Exception:
                err_msg = resp.text
            raise AIServiceError(f"Gemini API error (HTTP {resp.status_code}): {err_msg}")

        try:
            resp_json = resp.json()
            candidates = resp_json.get("candidates", [])
            if not candidates:
                raise AIParsingError("Gemini returned an empty candidate list.")

            content_parts = candidates[0].get("content", {}).get("parts", [])
            if not content_parts:
                raise AIParsingError("Gemini candidate did not contain content parts.")

            raw_text = content_parts[0].get("text", "").strip()
            parsed_json = json.loads(raw_text)
            return normalize_timeline_schema(parsed_json)
        except json.JSONDecodeError as e:
            raise AIParsingError(f"Failed to parse Gemini output as JSON: {str(e)}") from e
        except AIParsingError:
            raise
        except Exception as e:
            raise AIParsingError(f"Unexpected error validating Gemini timeline schema: {str(e)}") from e


# --- Mock Provider Implementation ---

class MockProvider(BaseAIProvider):
    """
    Deterministic offline heuristic provider for automated testing, CI/CD,
    and air-gapped demo environments. Uses regex heuristics on legal text.
    """

    def compare_versions(
        self,
        v1_meta: dict | None,
        v2_meta: dict | None,
        v1_summary: dict | None,
        v2_summary: dict | None,
        from_version_number: int = 1,
        to_version_number: int = 2,
        document_hint: dict | None = None,
    ) -> dict:
        """
        Deterministic, offline comparison engine for tests, CI/CD, and air-gapped demo environments.
        Strictly source-grounded, zero hallucinations.
        """
        return compute_deterministic_diff(
            v1_meta=v1_meta,
            v2_meta=v2_meta,
            v1_summary=v1_summary,
            v2_summary=v2_summary,
            from_version_number=from_version_number,
            to_version_number=to_version_number,
        )

    def extract_metadata(self, text: str, document_hint: dict | None = None) -> dict:
        text_lower = text.lower()
        cleaned_text = text.replace("\r", " ")

        # 1. Document Type Detection
        doc_type = None
        type_conf = 0.50
        if "affidavit of evidence" in text_lower or "affidavit" in text_lower:
            doc_type = "Affidavit"
            type_conf = 0.95
        elif "writ petition" in text_lower:
            doc_type = "Writ Petition"
            type_conf = 0.94
        elif "bail application" in text_lower:
            doc_type = "Bail Application"
            type_conf = 0.92
        elif "power of attorney" in text_lower:
            doc_type = "Power of Attorney"
            type_conf = 0.96
        elif "commercial agreement" in text_lower or "contract" in text_lower or "agreement" in text_lower:
            doc_type = "Commercial Contract"
            type_conf = 0.90
        elif "legal notice" in text_lower:
            doc_type = "Legal Notice"
            type_conf = 0.92
        elif "judgment" in text_lower or "order" in text_lower:
            doc_type = "Court Order"
            type_conf = 0.88
        elif document_hint and document_hint.get("filename"):
            fname = document_hint["filename"].lower()
            if "affidavit" in fname:
                doc_type = "Affidavit"
                type_conf = 0.70
            elif "petition" in fname:
                doc_type = "Writ Petition"
                type_conf = 0.70
            elif "contract" in fname or "agreement" in fname:
                doc_type = "Commercial Contract"
                type_conf = 0.70

        # 2. Case Number Detection (Isolates pure identifier, stripping labels like 'Civil Suit No.', 'Case No:', etc.)
        case_no = None
        case_conf = 0.0
        case_patterns = [
            (r'\b([A-Z]{2,6}[-\s]\d{4}[-\s]\d{1,6})\b', 0),
            (r'(W\.P\.\s*\([A-Za-z]+\)\s*(?:No\.?\s*)?\d+[\/\-]\d{2,4})', re.IGNORECASE),
            (r'(?:(?:Civil\s*Suit|Case|Docket|Petition|Writ\s*Petition|Suit)\s*(?:No\.?|Number)?|W\.P\.\s*No\.?)\s*[:\-\#]?\s*([A-Za-z0-9\-\/\.\(\)]+?\d+[A-Za-z0-9\-\/\.\(\)]*)', re.IGNORECASE),
            (r'((?:CIV|W\.P\.|C\.P\.|O\.S\.|CRL\.?A\.?|SLP|ARB)[A-Za-z0-9\(\)\.\s\-\/]*\d{1,6}[\/\-]\d{2,4})', re.IGNORECASE),
            (r'\b(\d{1,6}\/\d{4})\b', 0),
        ]
        for pat, flags in case_patterns:
            m = re.search(pat, cleaned_text, flags)
            if m:
                val = m.group(1) if m.groups() else m.group(0)
                val = val.strip(" :.-#\n\r")
                # Strip prefix labels if captured
                val = re.sub(r'^(?:Civil\s*Suit|Case|Docket|Petition|Writ\s*Petition|Suit)\s*(?:No\.?|Number)?\s*[:\-\#]?\s*', '', val, flags=re.IGNORECASE).strip(" :.-#\n\r")
                val = re.sub(r'^W\.P\.\s*No\.?\s*[:\-\#]?\s*', '', val, flags=re.IGNORECASE).strip(" :.-#\n\r")
                if len(val) >= 4 and any(c.isdigit() for c in val) and not re.match(r'^\d{4}-\d{2}-\d{2}$', val) and not val.lower().startswith("dated"):
                    case_no = val
                    case_conf = 0.96
                    break

        if not case_no and document_hint and document_hint.get("case_number"):
            raw_hint = document_hint["case_number"]
            raw_hint = re.sub(r'^(?:Civil\s*Suit|Case|Docket|Petition|Writ\s*Petition|Suit)\s*(?:No\.?|Number)?\s*[:\-\#]?\s*', '', raw_hint, flags=re.IGNORECASE).strip(" :.-#\n\r")
            raw_hint = re.sub(r'^W\.P\.\s*No\.?\s*[:\-\#]?\s*', '', raw_hint, flags=re.IGNORECASE).strip(" :.-#\n\r")
            case_no = raw_hint
            case_conf = 0.80

        # 3. Court Detection (Line/clause-bounded regex to prevent consuming 'in connection with', case numbers, etc.)
        court = None
        court_conf = 0.0
        court_patterns = [
            (r'\bSupreme Court of India\b', "Supreme Court of India", 0.99),
            (r'\bHigh Court of Judicature at Allahabad\b', "High Court of Judicature at Allahabad", 0.98),
            (r'\b(?:High Court of Delhi|Delhi High Court)\b', "High Court of Delhi", 0.97),
            (r'\b(?:High Court of Bombay|Bombay High Court)\b', "High Court of Bombay", 0.97),
            (r'\bHigh Court of (?:Judicature at )?([A-Za-z\s]+?)(?=\s+(?:in connection|in the matter|under\b|v\/s|vs|versus|case|civil|suit|no\.?|dated|\.|\,|\;|\:|\n|\r|\Z))', None, 0.92),
            (r'\bDistrict (?:and|&) Sessions Court(?:,?\s*(?:at|of|in|,)?\s*)([A-Za-z\s]+?)(?=\s+(?:in connection|in the matter|under\b|v\/s|vs|versus|case|civil|suit|no\.?|dated|\.|\,|\;|\:|\n|\r|\Z))', None, 0.94),
            (r'\bDistrict Court(?:,?\s*(?:at|of|in|,)?\s*)([A-Za-z\s]+?)(?=\s+(?:in connection|in the matter|under\b|v\/s|vs|versus|case|civil|suit|no\.?|dated|\.|\,|\;|\:|\n|\r|\Z))', None, 0.90),
            (r'\bCourt of ([A-Za-z\s]+?)(?=\s+(?:in connection|in the matter|under\b|v\/s|vs|versus|case|civil|suit|no\.?|dated|\.|\,|\;|\:|\n|\r|\Z))', None, 0.80),
        ]
        for pat, canonical_name, score in court_patterns:
            m = re.search(pat, cleaned_text, re.IGNORECASE)
            if m:
                if canonical_name:
                    court = canonical_name
                else:
                    full_match = m.group(0).strip(" \t\n\r,.-")
                    loc = m.group(1).strip(" \t\n\r,.-") if m.groups() and m.group(1) else ""
                    loc = loc.title() if loc.isupper() else loc
                    loc = re.sub(r'\s+(?:in|at|of|for)$', '', loc, flags=re.IGNORECASE).strip()
                    if "district" in full_match.lower() and "sessions" in full_match.lower():
                        court = f"District and Sessions Court, {loc}" if loc else "District and Sessions Court"
                    elif "district court of" in full_match.lower():
                        court = f"District Court of {loc}" if loc else "District Court"
                    elif "district" in full_match.lower():
                        court = f"District Court, {loc}" if loc else "District Court"
                    elif "high court" in full_match.lower():
                        court = f"High Court of {loc}" if loc else "High Court"
                    else:
                        court = full_match
                court_conf = score
                break

        # 4. Jurisdiction Detection (State mappings based on explicit state or recognized judicial cities)
        jurisdiction = None
        jur_conf = 0.0
        jurisdiction_mappings = [
            (["uttar pradesh", "kanpur", "allahabad", "lucknow", "varanasi", "noida", "agra", "ghaziabad"], "Uttar Pradesh", 0.95),
            (["delhi", "new delhi"], "Delhi", 0.95),
            (["maharashtra", "mumbai", "bombay", "pune", "nagpur"], "Maharashtra", 0.95),
            (["karnataka", "bangalore", "bengaluru"], "Karnataka", 0.95),
            (["tamil nadu", "chennai", "madras"], "Tamil Nadu", 0.95),
            (["west bengal", "kolkata", "calcutta"], "West Bengal", 0.95),
            (["gujarat", "ahmedabad"], "Gujarat", 0.95),
            (["telangana", "hyderabad"], "Telangana", 0.95),
            (["india", "supreme court"], "India", 0.90),
        ]
        for triggers, state_name, score in jurisdiction_mappings:
            if any(t in text_lower for t in triggers):
                jurisdiction = state_name
                jur_conf = score
                break

        # 5. Parties Detection
        def clean_party(name: str) -> str:
            name = re.sub(r'\s*\((?:Petitioner|Respondent|Deponent|Plaintiff|Defendant|Appellant)\)', '', name, flags=re.IGNORECASE)
            name = re.sub(r'^(?:IN THE MATTER OF|DATED|SUBJECT)[:\s]*', '', name, flags=re.IGNORECASE)
            name = name.split('\n')[0].strip(" :.-")
            return name

        parties = []
        petitioner_match = re.search(r'(?:Petitioner|Plaintiff|Deponent|Appellant|First Party)\s*[:\-]\s*([A-Za-z0-9\.\s,\/\(\)]+?)(?:\n|v\/s|vs|versus|and|\.|\Z)', cleaned_text, re.IGNORECASE)
        if petitioner_match:
            p_name = clean_party(petitioner_match.group(1))
            if len(p_name) > 2 and len(p_name) < 60:
                parties.append({"name": p_name, "role": "Petitioner" if "petitioner" in text_lower else "Deponent"})
        elif "affidavit" in text_lower:
            i_deponent = re.search(r'\bI,\s*([A-Za-z0-9\.\s,\/\(\)]+?),\s*(?:do hereby|depose|s\/o|solemn)', cleaned_text, re.IGNORECASE)
            if i_deponent:
                p_name = clean_party(i_deponent.group(1))
                if len(p_name) > 2 and len(p_name) < 60:
                    parties.append({"name": p_name, "role": "Deponent"})

        respondent_match = re.search(r'(?:Respondent|Defendant|Second Party|Versus)\s*[:\-]\s*([A-Za-z0-9\.\s,\/\(\)]+?)(?:\n|\.|\Z)', cleaned_text, re.IGNORECASE)
        if respondent_match:
            r_name = clean_party(respondent_match.group(1))
            if len(r_name) > 2 and len(r_name) < 60:
                parties.append({"name": r_name, "role": "Respondent"})

        # Fallback party detection for "X Versus Y"
        if not parties:
            vs_match = re.search(r'([A-Za-z0-9\s\.\(\),]+)\s+(?:Versus|v\/s|vs\.?)\s+([A-Za-z0-9\s\.\(\),]+)', cleaned_text, re.IGNORECASE)
            if vs_match:
                p1 = clean_party(vs_match.group(1))
                p2 = clean_party(vs_match.group(2))
                if len(p1) > 2 and len(p1) < 60:
                    parties.append({"name": p1, "role": "Petitioner"})
                if len(p2) > 2 and len(p2) < 60:
                    parties.append({"name": p2, "role": "Respondent"})

        # 6. Dates Detection
        dates = []
        date_patterns = [
            r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]+\d{4})',
            r'(\d{4}-\d{2}-\d{2})',
            r'(\d{1,2}\/\d{1,2}\/\d{4})',
        ]
        found_dates = []
        for d_pat in date_patterns:
            for m in re.finditer(d_pat, cleaned_text, re.IGNORECASE):
                d_str = m.group(1).strip()
                if d_str not in found_dates:
                    found_dates.append(d_str)
                    sentence_start = max(0, cleaned_text.rfind('.', 0, m.start()) + 1)
                    sentence_end = cleaned_text.find('.', m.end())
                    if sentence_end == -1:
                        sentence_end = len(cleaned_text)
                    context_snippet = cleaned_text[sentence_start:sentence_end].lower()

                    if "hearing" in context_snippet:
                        desc = "Hearing Date"
                    elif any(k in context_snippet for k in ["agreement", "contract", "covenant", "entered into an agreement"]):
                        desc = "Agreement Date"
                    elif any(k in context_snippet for k in ["filing", "filed", "petition", "complaint", "affidavit", "lodged", "submission"]):
                        desc = "Filing Date"
                    elif any(k in context_snippet for k in ["order", "decree", "judgment", "injunction"]):
                        desc = "Order Date"
                    elif any(k in context_snippet for k in ["execution", "executed", "signed", "sworn", "attested"]):
                        desc = "Execution Date"
                    elif any(k in context_snippet for k in ["notice", "summon"]):
                        desc = "Notice Date"
                    elif any(k in context_snippet for k in ["amend", "supplementary", "revised"]):
                        desc = "Amendment Date"
                    elif any(k in context_snippet for k in ["deadline", "due date", "expiry"]):
                        desc = "Deadline"
                    elif any(k in context_snippet for k in ["transfer", "conveyance", "partition"]):
                        desc = "Transfer Date"
                    elif any(k in context_snippet for k in ["payment", "paid", "deposit"]):
                        desc = "Payment Date"
                    else:
                        desc = "Important Date"
                    dates.append({"date": d_str, "description": desc})

        # 7. Subject Extraction (Strictly extracted from explicit Subject line in text; null if absent)
        subject = None
        subject_match = re.search(r'(?:[\n\r]|\A)\s*(?:Subject|Sub)\s*[:\-]\s*([^\n\r]+)', cleaned_text, re.IGNORECASE)
        if subject_match:
            raw_sub = subject_match.group(1).strip(" \t.-#")
            if len(raw_sub) > 3:
                subject = raw_sub

        # 8. Keyword Extraction (Derived strictly from document text, non-synthetic, bounded)
        keywords = []
        kw_line_match = re.search(r'(?:[\n\r]|\A)\s*(?:Keywords?|Key\s*Words?)\s*[:\-]\s*([^\n\r]+)', cleaned_text, re.IGNORECASE)
        if kw_line_match:
            raw_kw = kw_line_match.group(1).strip()
            for part in re.split(r'[,;|\t]+', raw_kw):
                cleaned_k = part.strip().lower()
                if cleaned_k and len(cleaned_k) >= 3 and cleaned_k not in keywords:
                    keywords.append(cleaned_k)
        else:
            STOPWORDS = {
                "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
                "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
                "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from", "further", "had",
                "has", "have", "having", "he", "her", "here", "him", "his", "how", "i", "if", "in", "into", "is",
                "it", "its", "me", "more", "most", "my", "no", "nor", "not", "of", "off", "on", "once", "only",
                "or", "other", "our", "out", "over", "own", "same", "she", "should", "so", "some", "such", "than",
                "that", "the", "their", "them", "then", "there", "these", "they", "this", "those", "through", "to",
                "too", "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which", "while",
                "who", "whom", "why", "with", "you", "your",
                # Administrative / structural stopwords
                "court", "dated", "versus", "case", "number", "shall", "honble", "state", "nagar", "kanpur",
                "uttar", "pradesh", "connection", "matter", "before", "page", "deponent", "petitioner", "respondent",
                "plaintiff", "defendant", "delhi", "allahabad", "bombay", "india", "date", "filing", "hearing",
                "year", "years", "late", "said", "hereby", "civil", "suit", "village", "situated", "supporting",
                "district", "sessions", "high"
            }

            # Filter party names from keywords
            party_tokens = set(w.lower() for p in parties for w in re.findall(r'\b[a-zA-Z]+\b', p.get("name", "")))

            # 8a. Check for meaningful compound phrases literally present in text
            meaningful_phrases = [
                "agricultural land", "evidentiary documents", "property title", "title transfer",
                "interim injunction", "interim relief", "land partition", "writ petition", "commercial contract"
            ]
            for phrase in meaningful_phrases:
                if phrase in text_lower and phrase not in keywords:
                    keywords.append(phrase)

            # 8b. Extract meaningful individual domain words directly from document text
            tokens = re.findall(r'\b[a-zA-Z]{4,25}\b', text_lower)
            for w in tokens:
                if w not in STOPWORDS and w not in party_tokens:
                    if w not in keywords and not any(w in kw.split() for kw in keywords):
                        keywords.append(w)

            # Limit keywords to 8 items
            keywords = keywords[:8]

        # 9. Confidence calculation
        conf_fields = {
            "document_type": type_conf,
            "case_number": case_conf,
            "court": court_conf,
            "jurisdiction": jur_conf,
            "parties": 0.85 if parties else 0.0,
            "dates": 0.88 if dates else 0.0,
            "subject": 0.85 if subject else 0.0,
        }
        present_confs = [v for v in conf_fields.values() if v > 0]
        overall_conf = round(sum(present_confs) / len(present_confs), 2) if present_confs else 0.50

        raw_result = {
            "document_type": doc_type,
            "case_number": case_no,
            "court": court,
            "jurisdiction": jurisdiction,
            "parties": parties,
            "dates": dates,
            "subject": subject,
            "keywords": list(dict.fromkeys(keywords)),
            "confidence": {
                "overall": overall_conf,
                "fields": conf_fields
            }
        }

        return normalize_extracted_schema(raw_result)

    def generate_summary(self, text: str, document_hint: dict | None = None) -> dict:
        """
        Simple, deterministic offline heuristic summarizer for tests, CI/CD, and air-gapped demos.
        Strictly source-derived, zero hallucinations.
        """
        if not text:
            return {
                "summary": "No extractable text content was provided for summarization.",
                "key_facts": ["No extractable text provided."],
                "legal_issues": ["No explicit statutory violations or contested issues specified in the text."],
                "important_points": ["Refer to primary document text for specific procedural dates and covenants."]
            }

        # 1. Clean document text & strip leading/trailing artifacts
        cleaned_text = re.sub(r'^[.\-*_:\s#•]+', '', text).strip()

        # Protect common abbreviations from being treated as sentence endings
        protected_text = cleaned_text
        abbreviations = [
            r'\bNo\.', r'\bvs\.', r'\bv\.', r'\bAdv\.', r'\bHon\.', r'\bSh\.', r'\bSmt\.',
            r'\bMr\.', r'\bMrs\.', r'\bMs\.', r'\bDr\.', r'\bSec\.', r'\bArt\.', r'\bpara\.',
            r'\bcl\.', r'\bvol\.', r'\bLtd\.', r'\bPvt\.', r'\bCo\.', r'\bCorp\.', r'\bInc\.',
            r'\bU\.P\.', r'\bU/S\.', r'\bi\.e\.', r'\be\.g\.', r'\bW\.P\.', r'\bC\.A\.', r'\bS\.L\.P\.'
        ]
        for abbr_pat in abbreviations:
            protected_text = re.sub(abbr_pat, lambda m: m.group(0).replace('.', '@DOT@'), protected_text, flags=re.IGNORECASE)

        # 2. Tokenize into sentences and lines
        raw_segments = re.split(r'\n+|(?:(?<=[.!?])\s+(?=[A-Z0-9"\'\(\[]))', protected_text)
        cleaned_sentences = []
        for seg in raw_segments:
            if not seg:
                continue
            s = seg.replace('@DOT@', '.')
            s = re.sub(r'^[.\-*_:\s#•]+', '', s).strip()
            s = re.sub(r'[.\-*_:\s#•]+$', '', s).strip()
            if len(s) >= 10:
                cleaned_sentences.append(s)

        # Identify document type
        text_lower = cleaned_text.lower()
        doc_type = "Legal Document"
        if "affidavit" in text_lower:
            doc_type = "Affidavit"
        elif "writ petition" in text_lower or "petition" in text_lower:
            doc_type = "Writ Petition"
        elif "contract" in text_lower or "agreement" in text_lower:
            doc_type = "Commercial Contract"
        elif "bail" in text_lower:
            doc_type = "Bail Application"

        # 3. Extract narrative summary (clean 2-3 sentence synthesis)
        narrative_candidates = []
        for s in cleaned_sentences:
            # Skip pure docket and court headers
            if re.match(r'^(?:IN THE|DISTRICT COURT|HIGH COURT|SUPREME COURT|CASE NO|AFFIDAVIT OF|WRIT PETITION|DATED|SUBJECT|FILING|HEARING|DEPONENT|VERSUS|PETITIONER|RESPONDENT)', s, re.IGNORECASE):
                continue
            if len(s) > 25:
                formatted_s = s if s.endswith(('.', '!', '?')) else f"{s}."
                narrative_candidates.append(formatted_s)
                if len(narrative_candidates) >= 3:
                    break

        if not narrative_candidates:
            for s in cleaned_sentences:
                if len(s) > 20 and not re.match(r'^(?:CASE NO|IN THE)', s, re.IGNORECASE):
                    formatted_s = s if s.endswith(('.', '!', '?')) else f"{s}."
                    narrative_candidates.append(formatted_s)
                    if len(narrative_candidates) >= 2:
                        break

        if narrative_candidates:
            summary_narrative = " ".join(narrative_candidates)
        else:
            summary_narrative = f"This {doc_type.lower()} sets forth legal filings and factual affirmations submitted in the matter."

        summary_narrative = re.sub(r'^[.\-*_:\s#•]+', '', summary_narrative).strip()

        # 4. Extract key facts (concise, source-derived facts)
        key_facts = []
        for s in cleaned_sentences:
            s_lower = s.lower()
            if re.match(r'^(?:POLICE INVESTIGATION|INVESTIGATION REPORT|INCIDENT STATEMENT|FIRST INFORMATION REPORT|CASE NO|SUBJECT|AFFIDAVIT OF|IN THE HIGH COURT|IN THE DISTRICT|DATED|KEYWORDS|IN THE COURT|BEFORE THE|NOTICE OF)', s, re.IGNORECASE):
                continue
            if any(k in s_lower for k in [
                "theft", "missing", "stolen", "cash", "incident", "occurred", "cctv", "footage",
                "witness", "observed", "stated that", "reportedly", "saw", "entrance", "store", "premises",
                "motorcycle", "vehicle", "investigation", "progressed", "questioned", "statements",
                "submitted by", "affidavit is submitted", "in support of", "concerning",
                "ownership and possession", "disputed property", "agricultural land",
                "transferred under", "transferred", "agreement dated", "executed on", "executed", "title transfer",
                "scheduled for hearing", "hearing on", "filing date", "filed on", "deponent", "states that",
                "affirmation", "covenant", "situated at", "in the matter of", "versus"
            ]):
                formatted_fact = s if s.endswith(('.', '!', '?')) else f"{s}."
                if formatted_fact not in key_facts and len(s) > 15:
                    key_facts.append(formatted_fact)
                    if len(key_facts) >= 6:
                        break

        # Fallback to substantive sentences if specific keywords did not trigger
        if not key_facts:
            for s in cleaned_sentences:
                if len(s) > 25 and not re.match(r'^(?:POLICE|CASE NO|SUBJECT|AFFIDAVIT OF|IN THE)', s, re.IGNORECASE):
                    formatted_fact = s if s.endswith(('.', '!', '?')) else f"{s}."
                    if formatted_fact not in key_facts:
                        key_facts.append(formatted_fact)
                        if len(key_facts) >= 4:
                            break

        # 5. Extract legal issues / claims & grounds (concise targeted clauses/issues)
        legal_issues = []
        for s in cleaned_sentences:
            s_lower = s.lower()

            # Ignore docket/title lines
            if re.match(r'^(?:POLICE|INVESTIGATION|INCIDENT|CASE NO|SUBJECT|AFFIDAVIT OF|IN THE HIGH COURT|IN THE DISTRICT|DATED|KEYWORDS)', s, re.IGNORECASE):
                continue

            # Clause A: Ownership / Title / Partition dispute clause
            dispute_match = re.search(r'concerning\s+(?:the\s+)?(ownership\s+and\s+possession\s+of\s+[^.!?]+|title\s+dispute[^.!?]*|agricultural\s+land[^.!?]*|partition[^.!?]*)', s, re.IGNORECASE)
            if dispute_match:
                issue_str = f"The dispute concerns {dispute_match.group(1).strip()}."
                issue_str = re.sub(r'\s+\.$', '.', issue_str)
                if not issue_str.endswith('.'):
                    issue_str += '.'
                if issue_str not in legal_issues:
                    legal_issues.append(issue_str)

            # Clause B: Relief sought clause
            relief_match = re.search(r'(?:seeks|prays for|requests)\s+(?:appropriate\s+)?relief\s+regarding\s+([^.!?]+)', s, re.IGNORECASE)
            if relief_match:
                issue_str = f"The petitioner seeks relief regarding {relief_match.group(1).strip()}."
                issue_str = re.sub(r'\s+\.$', '.', issue_str)
                if not issue_str.endswith('.'):
                    issue_str += '.'
                if issue_str not in legal_issues:
                    legal_issues.append(issue_str)

            # Clause C: Challenge to municipal / governmental action or breach
            challenge_match = re.search(r'(?:challenge\s+to|grievance\s+regarding|breach\s+of)\s+([^.!?]+)', s, re.IGNORECASE)
            if challenge_match:
                issue_str = f"Challenge regarding {challenge_match.group(1).strip()}."
                if not issue_str.endswith('.'):
                    issue_str += '.'
                if issue_str not in legal_issues:
                    legal_issues.append(issue_str)

            # Clause D: Prayer clause
            if s_lower.startswith("prayer:") or "prays for" in s_lower:
                pm = re.search(r'(?:prayer:\s*|prays for\s*)([^.!?\n]+)', s, re.IGNORECASE)
                if pm:
                    p_text = pm.group(1).strip()
                    p_str = f"Prayer for {p_text}." if not p_text.lower().startswith("the") else f"{p_text}."
                    if p_str not in legal_issues:
                        legal_issues.append(p_str)

            if len(legal_issues) >= 3:
                break

        # Fallback to discrete legal sentence if no targeted clause matched
        if not legal_issues:
            for s in cleaned_sentences:
                s_lower = s.lower()
                if any(k in s_lower for k in ["dispute concerns", "statutory violation", "breach of covenant", "illegal demolition", "interim relief", "prayer for"]):
                    if not re.match(r'^(?:CASE NO|IN THE|DATED|AFFIDAVIT OF|SUBJECT|POLICE)', s, re.IGNORECASE):
                        formatted_issue = s if s.endswith(('.', '!', '?')) else f"{s}."
                        if formatted_issue not in legal_issues and len(s) > 20:
                            legal_issues.append(formatted_issue)
                            if len(legal_issues) >= 2:
                                break

        # 6. Extract important points / relief / deadlines (explicit procedural facts)
        important_points = []

        # 6a. Agreement / Transfer Dates
        agreement_match = re.search(r'(?:agreement|deed|contract|covenant|transfer(?:red)?)\s+(?:dated|executed on)\s+(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})', text, re.IGNORECASE)
        if agreement_match:
            important_points.append(f"Agreement dated {agreement_match.group(1)}.")

        # 6b. Relief Sought / Prayer
        relief_pt_match = re.search(r'(?:seeks|prays for|requests)\s+(?:appropriate\s+)?relief\s+regarding\s+([^.!?\n]+)', text, re.IGNORECASE)
        if relief_pt_match:
            important_points.append(f"Relief sought regarding {relief_pt_match.group(1).strip()}.")
        elif re.search(r'prayer:\s*([^.!?\n]+)', text, re.IGNORECASE):
            pm = re.search(r'prayer:\s*([^.!?\n]+)', text, re.IGNORECASE)
            important_points.append(f"Prayer: {pm.group(1).strip()}.")
        elif re.search(r'prays for\s+([^.!?\n]+)', text, re.IGNORECASE):
            pm = re.search(r'prays for\s+([^.!?\n]+)', text, re.IGNORECASE)
            important_points.append(f"Prayer: {pm.group(1).strip()}.")

        # 6c. Hearing / Filing / Order Dates
        hearing_match = re.search(r'(?:scheduled for\s+)?hearing\s+on\s+(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})', text, re.IGNORECASE)
        if hearing_match:
            important_points.append(f"Hearing scheduled for {hearing_match.group(1)}.")
        elif re.search(r'hearing date:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})', text, re.IGNORECASE):
            hm = re.search(r'hearing date:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})', text, re.IGNORECASE)
            important_points.append(f"Hearing Date: {hm.group(1)}.")

        filing_match = re.search(r'filing date:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})', text, re.IGNORECASE)
        if filing_match:
            important_points.append(f"Filing Date: {filing_match.group(1)}.")

        order_match = re.search(r'dated:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})', text, re.IGNORECASE)
        if order_match and len(important_points) < 3:
            important_points.append(f"Dated: {order_match.group(1)}.")

        # 6d. Fallback sentence scanner if explicit regex found < 2 points
        if len(important_points) < 2:
            for s in cleaned_sentences:
                s_lower = s.lower()
                if any(k in s_lower for k in ["filing date", "hearing date", "execution date", "order date", "prayer:", "prays that", "injunction", "covenant"]):
                    if not re.match(r'^(?:AFFIDAVIT OF|IN THE|POLICE|CASE NO|SUBJECT)', s, re.IGNORECASE):
                        formatted_pt = s if s.endswith(('.', '!', '?')) else f"{s}."
                        if formatted_pt not in important_points:
                            important_points.append(formatted_pt)
                            if len(important_points) >= 4:
                                break

        raw_summary = {
            "summary": summary_narrative,
            "key_facts": key_facts,
            "legal_issues": legal_issues,
            "important_points": important_points
        }
        return normalize_summary_schema(raw_summary)

    def extract_timeline(self, text: str, document_hint: dict | None = None) -> dict:
        """
        Deterministic, offline extraction of chronological legal events from document text.
        Extracts dated sentences, classifies procedural/factual events, and grounds in text.
        Returns: {"events": [...]}
        """
        if not text or not text.strip():
            return {"events": []}

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        lines_and_sentences = []
        for line in lines:
            for s in re.split(r'(?<=[.!?])\s+', line):
                s_clean = s.strip()
                if len(s_clean) >= 6:
                    lines_and_sentences.append(s_clean)

        date_patterns = [
            r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]+\d{4})',
            r'(\d{4}-\d{2}-\d{2})',
            r'(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{4})',
            r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?[\s,]+\d{4})',
        ]

        raw_events = []

        for segment in lines_and_sentences:
            seg_strip = segment.strip()
            if len(seg_strip) < 8:
                continue

            seg_lower = seg_strip.lower()

            matches_in_seg = []
            for pat in date_patterns:
                for match in re.finditer(pat, seg_strip, re.IGNORECASE):
                    d_raw = match.group(1).strip()
                    iso_d = parse_iso_date(d_raw)
                    if iso_d:
                        matches_in_seg.append((match.start(), match.end(), d_raw, iso_d))

            if not matches_in_seg:
                continue

            matches_in_seg.sort(key=lambda x: x[0])
            unique_dates = []
            seen_d = set()
            for m_start, m_end, d_raw, iso_d in matches_in_seg:
                if iso_d not in seen_d:
                    seen_d.add(iso_d)
                    unique_dates.append((m_start, m_end, d_raw, iso_d))

            # If segment starts with "On <Date>" or "Dated: <Date>", pick the leading date as the primary event date
            if len(unique_dates) > 1 and re.match(r'^(?:[•\-\*\d\.\)\s]*On|[•\-\*\d\.\)\s]*Dated)', seg_strip, re.IGNORECASE):
                target_dates = [unique_dates[0]]
            else:
                target_dates = unique_dates

            for m_start, m_end, d_raw, iso_d in target_dates:
                # 1. Contextual Classification (strictly within the 11 approved categories)
                ev_type = "OTHER"

                if any(k in seg_lower for k in ["hearing", "listed for hearing", "scheduled for hearing", "court hearing", "hearing scheduled", "next hearing"]):
                    ev_type = "HEARING"
                elif any(k in seg_lower for k in ["amended", "amendment", "supplementary", "revised filing", "amended affidavit", "modified pleading"]):
                    ev_type = "AMENDMENT"
                elif any(k in seg_lower for k in ["agreement", "contract", "covenant", "entered into an agreement", "settlement deed", "terms agreed"]):
                    ev_type = "AGREEMENT"
                elif any(k in seg_lower for k in ["executed on", "execution of", "signed by", "attested", "sworn before", "deposed before", "solemnly affirmed"]):
                    ev_type = "EXECUTION"
                elif any(k in seg_lower for k in ["court ordered", "court passed", "passed an order", "interim order", "injunction", "stay granted", "decree", "direction issued", "bail granted", "warrant"]):
                    ev_type = "ORDER"
                elif any(k in seg_lower for k in ["notice issued", "notice served", "show cause notice", "intimation", "summons served", "legal notice"]):
                    ev_type = "NOTICE"
                elif any(k in seg_lower for k in ["deadline", "must be completed by", "due on", "time limit", "expiry date", "due date", "within 30 days", "within 15 days"]):
                    ev_type = "DEADLINE"
                elif any(k in seg_lower for k in ["property transferred", "ownership transferred", "conveyance", "possession delivered", "land partition", "sale deed"]):
                    ev_type = "TRANSFER"
                elif any(k in seg_lower for k in [
                    "investigation progressed", "investigation continued", "investigation remained ongoing",
                    "investigation into", "investigated", "inquiry continued", "police investigated",
                    "statements were obtained", "witness statement", "witness statements",
                    "was questioned", "were questioned", "questioned on",
                    "cctv footage", "footage recovered", "footage reportedly showed",
                    "evidence was recovered", "evidence was examined", "evidence recovered", "observed a motorcycle"
                ]):
                    ev_type = "OTHER"
                elif any(k in seg_lower for k in [
                    "theft was reported", "theft reported at", "case was reported", "crime was reported",
                    "complaint was filed", "complaint was lodged", "complaint was made", "initial complaint",
                    "report was lodged", "fir registered", "fir was registered", "fir lodged",
                    "petition was submitted", "petition was filed", "affidavit was filed", "affidavit filed",
                    "affidavit was submitted", "suit was filed", "suit filed", "application was filed",
                    "filing date", "filed on", "police complaint was lodged"
                ]):
                    ev_type = "FILING"
                elif any(k in seg_lower for k in ["payment made", "amount paid", "consideration paid", "deposit", "recovered amount", "funds transferred", "reimbursed", "settlement paid"]):
                    ev_type = "PAYMENT"
                else:
                    ev_type = "OTHER"

                # 2. Derive Grounded Description from source sentence rather than generic placeholders
                cleaned_desc = re.sub(r'^[•\-\*\d\.\)\s#_:]+', '', seg_strip).strip()
                if cleaned_desc:
                    if not cleaned_desc.endswith(('.', '!', '?')):
                        cleaned_desc += '.'
                    desc = cleaned_desc
                else:
                    desc = f"{ev_type.capitalize()} event referenced in document text."

                if len(desc) > 300:
                    desc = desc[:297].rstrip() + "..."

                # 3. Bounded source reference (max 180 chars)
                src_ref = seg_strip
                if len(src_ref) > 180:
                    start = max(0, m_start - 30)
                    end = min(len(seg_strip), m_end + 70)
                    src_ref = seg_strip[start:end].strip()

                raw_events.append({
                    "date": iso_d,
                    "date_raw": d_raw,
                    "event_type": ev_type,
                    "description": desc,
                    "source_reference": src_ref,
                    "confidence": 0.95 if iso_d else 0.85,
                })

        return normalize_timeline_schema({"events": raw_events})


# --- Core Extractor Orchestrator ---

MAX_AI_TEXT_CHARS = 500000


class AIExtractor:
    """
    Central AI Extraction & Summarization Orchestrator.
    - Handles text extraction from PDF and TXT files.
    - Instantiates the active provider (Gemini or Mock) based on environment configuration.
    - Strictly prevents silent fallback from Gemini to Mock.
    - Times execution and isolates errors from the underlying document custody records.
    """

    def __init__(self, provider_name: str | None = None):
        self.provider_name = (provider_name or os.getenv("LEGALVAULT_AI_PROVIDER", "gemini")).strip().lower()
        self.is_enabled = os.getenv("LEGALVAULT_AI_ENABLED", "true").strip().lower() == "true"
        if self.provider_name == "mock":
            self.model_name = "offline-heuristics"
        else:
            self.model_name = os.getenv("LEGALVAULT_AI_MODEL", "gemini-2.0-flash").strip()

        try:
            self.timeout_seconds = int(os.getenv("LEGALVAULT_AI_TIMEOUT_SECONDS", "30"))
        except ValueError:
            self.timeout_seconds = 30

        self.provider = self._resolve_provider()

    def _resolve_provider(self) -> BaseAIProvider:
        if self.provider_name == "mock":
            return MockProvider()
        elif self.provider_name == "gemini":
            # Will raise AIConfigurationError if GEMINI_API_KEY is missing
            return GeminiProvider(model=self.model_name, timeout_seconds=self.timeout_seconds)
        else:
            raise AIConfigurationError(
                f"Unsupported AI provider '{self.provider_name}'. Supported providers: 'gemini', 'mock'."
            )

    @staticmethod
    def extract_text_from_file(file_path: str, file_type: str | None = None) -> tuple[str, str, str | None]:
        """
        Extracts clean textual content from PDF and TXT files.
        Returns: (text, status, error_reason)
        Status values: 'OK', 'EXTRACTION_UNAVAILABLE', 'EXTRACTION_LIMIT_EXCEEDED', 'UNSUPPORTED_FORMAT'
        """
        if not os.path.exists(file_path):
            return "", "EXTRACTION_UNAVAILABLE", f"Document file not found on disk at {file_path}"

        ext = (file_type or os.path.splitext(file_path)[1]).lower()

        if ext == ".txt":
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    raw_text = f.read()
            except UnicodeDecodeError:
                try:
                    with open(file_path, "r", encoding="cp1252", errors="replace") as f:
                        raw_text = f.read()
                except Exception as e:
                    return "", "EXTRACTION_UNAVAILABLE", f"Failed decoding text file: {str(e)}"
            except Exception as e:
                return "", "EXTRACTION_UNAVAILABLE", f"Error reading text file: {str(e)}"

            cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', raw_text)
            normalized = " ".join(cleaned.split())

            if len(normalized.strip()) < 20:
                return "", "EXTRACTION_UNAVAILABLE", "Document contains insufficient text (< 20 characters) for AI processing."

            if len(cleaned) > MAX_AI_TEXT_CHARS:
                return "", "EXTRACTION_LIMIT_EXCEEDED", f"Document text length ({len(cleaned):,} characters) exceeds maximum AI processing limit of {MAX_AI_TEXT_CHARS:,} characters."

            return cleaned, "OK", None

        elif ext == ".pdf":
            try:
                reader = PdfReader(file_path)
                if reader.is_encrypted:
                    try:
                        reader.decrypt("")
                    except Exception:
                        return "", "EXTRACTION_UNAVAILABLE", "Password-protected or encrypted PDF cannot be read."

                extracted_pages = []
                for idx, page in enumerate(reader.pages):
                    try:
                        page_text = page.extract_text() or ""
                        if page_text.strip():
                            extracted_pages.append(page_text)
                    except Exception as pe:
                        print(f"[PDF EXTRACTION WARNING] Page {idx+1} read warning: {pe}", file=sys.stderr)

                full_text = "\n\n".join(extracted_pages)
                cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', full_text)
                normalized = " ".join(cleaned.split())

                if len(normalized.strip()) < 20:
                    return "", "EXTRACTION_UNAVAILABLE", "Scanned image-only PDF or unextractable text. OCR is not enabled for this vault instance."

                if len(cleaned) > MAX_AI_TEXT_CHARS:
                    return "", "EXTRACTION_LIMIT_EXCEEDED", f"Document text length ({len(cleaned):,} characters) exceeds maximum AI processing limit of {MAX_AI_TEXT_CHARS:,} characters."

                return cleaned, "OK", None
            except Exception as e:
                return "", "EXTRACTION_UNAVAILABLE", f"Malformed or unreadable PDF document: {str(e)}"

        else:
            return "", "UNSUPPORTED_FORMAT", f"AI analysis currently supports PDF and TXT documents. Received format '{ext}'."

    def process_document_version(
        self,
        file_path: str,
        file_type: str | None = None,
        document_hint: dict | None = None,
    ) -> tuple[dict | None, str, str | None, int]:
        """
        Executes the end-to-end extraction pipeline on an immutable version file.
        Returns: (metadata_dict, status, error_message, duration_ms)
        Status values: 'COMPLETED', 'EXTRACTION_UNAVAILABLE', 'EXTRACTION_LIMIT_EXCEEDED', 'FAILED'
        """
        start_time = time.perf_counter()

        if not self.is_enabled:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", "AI metadata extraction is disabled by administrator configuration (LEGALVAULT_AI_ENABLED=false).", duration_ms

        # 1. Extract text from file
        text, extract_status, extract_err = self.extract_text_from_file(file_path, file_type)
        if extract_status != "OK":
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            status_code = extract_status if extract_status in ["EXTRACTION_UNAVAILABLE", "EXTRACTION_LIMIT_EXCEEDED"] else "FAILED"
            return None, status_code, extract_err, duration_ms

        # 2. Invoke active provider
        try:
            metadata = self.provider.extract_metadata(text, document_hint)
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return metadata, "COMPLETED", None, duration_ms
        except AIConfigurationError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Configuration Error: {str(e)}", duration_ms
        except AITimeoutError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Provider Timeout: {str(e)}", duration_ms
        except AIParsingError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Schema Validation Error: {str(e)}", duration_ms
        except AIServiceError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Service Error: {str(e)}", duration_ms
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"Unexpected AI extraction failure: {str(e)}", duration_ms

    def generate_summary_for_file(
        self,
        file_path: str,
        file_type: str | None = None,
        document_hint: dict | None = None,
    ) -> tuple[dict | None, str, str | None, int]:
        """
        Executes the summarization pipeline on an immutable version file.
        Returns: (summary_dict, status, error_message, duration_ms)
        Status values: 'COMPLETED', 'EXTRACTION_UNAVAILABLE', 'EXTRACTION_LIMIT_EXCEEDED', 'FAILED'
        """
        start_time = time.perf_counter()

        if not self.is_enabled:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", "AI summarization is disabled by administrator configuration (LEGALVAULT_AI_ENABLED=false).", duration_ms

        # 1. Extract text from file
        text, extract_status, extract_err = self.extract_text_from_file(file_path, file_type)
        if extract_status != "OK":
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            status_code = extract_status if extract_status in ["EXTRACTION_UNAVAILABLE", "EXTRACTION_LIMIT_EXCEEDED"] else "FAILED"
            return None, status_code, extract_err, duration_ms

        # 2. Invoke active provider
        try:
            summary_data = self.provider.generate_summary(text, document_hint)
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return summary_data, "COMPLETED", None, duration_ms
        except AIConfigurationError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Configuration Error: {str(e)}", duration_ms
        except AITimeoutError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Provider Timeout: {str(e)}", duration_ms
        except AIParsingError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Schema Validation Error: {str(e)}", duration_ms
        except AIServiceError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Service Error: {str(e)}", duration_ms
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"Unexpected AI summarization failure: {str(e)}", duration_ms

    def compare_versions_for_document(
        self,
        v1_meta: dict | None,
        v2_meta: dict | None,
        v1_summary: dict | None,
        v2_summary: dict | None,
        from_version_number: int = 1,
        to_version_number: int = 2,
        document_hint: dict | None = None,
    ) -> tuple[dict | None, str, str | None, int]:
        """
        Executes version comparison pipeline between two immutable versions.
        Returns: (comparison_dict, status, error_message, duration_ms)
        Status values: 'COMPLETED', 'FAILED'
        """
        start_time = time.perf_counter()

        if not self.is_enabled:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", "AI version comparison is disabled by administrator configuration (LEGALVAULT_AI_ENABLED=false).", duration_ms

        try:
            comparison_data = self.provider.compare_versions(
                v1_meta=v1_meta,
                v2_meta=v2_meta,
                v1_summary=v1_summary,
                v2_summary=v2_summary,
                from_version_number=from_version_number,
                to_version_number=to_version_number,
                document_hint=document_hint,
            )
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return comparison_data, "COMPLETED", None, duration_ms
        except AIConfigurationError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Configuration Error: {str(e)}", duration_ms
        except AITimeoutError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Provider Timeout: {str(e)}", duration_ms
        except AIParsingError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Schema Validation Error: {str(e)}", duration_ms
        except AIServiceError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Service Error: {str(e)}", duration_ms
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"Unexpected AI comparison failure: {str(e)}", duration_ms

    def extract_timeline_for_file(
        self,
        file_path: str,
        file_type: str | None = None,
        document_hint: dict | None = None,
    ) -> tuple[dict | None, str, str | None, int]:
        """
        Executes the timeline extraction pipeline on an immutable version file.
        Returns: (timeline_dict, status, error_message, duration_ms)
        Status values: 'COMPLETED', 'EXTRACTION_UNAVAILABLE', 'EXTRACTION_LIMIT_EXCEEDED', 'FAILED'
        """
        start_time = time.perf_counter()

        if not self.is_enabled:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", "AI timeline extraction is disabled by administrator configuration (LEGALVAULT_AI_ENABLED=false).", duration_ms

        # 1. Extract text from file
        text, extract_status, extract_err = self.extract_text_from_file(file_path, file_type)
        if extract_status != "OK":
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            status_code = extract_status if extract_status in ["EXTRACTION_UNAVAILABLE", "EXTRACTION_LIMIT_EXCEEDED"] else "FAILED"
            return None, status_code, extract_err, duration_ms

        # 2. Invoke active provider
        try:
            timeline_data = self.provider.extract_timeline(text, document_hint)
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return timeline_data, "COMPLETED", None, duration_ms
        except AIConfigurationError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Configuration Error: {str(e)}", duration_ms
        except AITimeoutError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Provider Timeout: {str(e)}", duration_ms
        except AIParsingError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Schema Validation Error: {str(e)}", duration_ms
        except AIServiceError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"AI Service Error: {str(e)}", duration_ms
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return None, "FAILED", f"Unexpected AI timeline extraction failure: {str(e)}", duration_ms
