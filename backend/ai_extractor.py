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


# --- Mock Provider Implementation ---

class MockProvider(BaseAIProvider):
    """
    Deterministic offline heuristic provider for automated testing, CI/CD,
    and air-gapped demo environments. Uses regex heuristics on legal text.
    """

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
                    desc = "Important Date"
                    start_pos = max(0, m.start() - 30)
                    context_snippet = cleaned_text[start_pos:m.start()].lower()
                    if "filing" in context_snippet or "filed" in context_snippet:
                        desc = "Filing Date"
                    elif "hearing" in context_snippet:
                        desc = "Hearing Date"
                    elif "order" in context_snippet or "decree" in context_snippet:
                        desc = "Order Date"
                    elif "execution" in context_snippet or "executed" in context_snippet:
                        desc = "Execution Date"
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
            if any(k in s_lower for k in [
                "submitted by", "affidavit is submitted", "in support of", "concerning",
                "ownership and possession", "disputed property", "agricultural land",
                "transferred under", "agreement dated", "executed on", "title transfer",
                "scheduled for hearing", "hearing on", "filing date", "deponent", "states that",
                "affirmation", "covenant", "situated at", "in the matter of", "versus"
            ]):
                if not re.match(r'^(?:CASE NO|SUBJECT:|AFFIDAVIT OF|IN THE HIGH COURT|IN THE DISTRICT)', s, re.IGNORECASE):
                    formatted_fact = s if s.endswith(('.', '!', '?')) else f"{s}."
                    if formatted_fact not in key_facts and len(s) > 15:
                        key_facts.append(formatted_fact)
                        if len(key_facts) >= 4:
                            break

        if not key_facts:
            key_facts = ["Factual background and procedural statements as detailed in the filing text."]

        # 5. Extract legal issues / claims & grounds (concise targeted clauses/issues)
        legal_issues = []
        for s in cleaned_sentences:
            s_lower = s.lower()

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

            # Clause D: Subject line with partition / suit / dispute
            if s_lower.startswith("subject:"):
                sub_val = s[8:].strip()
                issue_str = f"Subject matter: {sub_val}"
                if not issue_str.endswith('.'):
                    issue_str += '.'
                if issue_str not in legal_issues:
                    legal_issues.append(issue_str)

            # Clause E: Prayer clause
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
                if any(k in s_lower for k in ["dispute", "suit no", "in connection with", "challenge", "breach", "illegal", "ground", "injunction", "interim relief"]):
                    if not re.match(r'^(?:CASE NO|IN THE|DATED|AFFIDAVIT OF)', s, re.IGNORECASE):
                        formatted_issue = s if s.endswith(('.', '!', '?')) else f"{s}."
                        if formatted_issue not in legal_issues and len(s) > 20:
                            legal_issues.append(formatted_issue)
                            if len(legal_issues) >= 2:
                                break

        if not legal_issues:
            legal_issues = ["No explicit statutory violations or contested issues specified in the text."]

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
                    if not re.match(r'^(?:AFFIDAVIT OF|IN THE)', s, re.IGNORECASE):
                        formatted_pt = s if s.endswith(('.', '!', '?')) else f"{s}."
                        if formatted_pt not in important_points:
                            important_points.append(formatted_pt)
                            if len(important_points) >= 4:
                                break

        if not important_points:
            important_points = ["Refer to primary document text for specific procedural dates and covenants."]

        raw_summary = {
            "summary": summary_narrative,
            "key_facts": key_facts,
            "legal_issues": legal_issues,
            "important_points": important_points
        }
        return normalize_summary_schema(raw_summary)


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
