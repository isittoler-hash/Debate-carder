from __future__ import annotations

import io
import json
import logging
import os
import re
import ssl
import sys
import zipfile
from datetime import date
from logging.handlers import RotatingFileHandler
import time
import urllib.error
import urllib.request
from collections import Counter
from html import escape, unescape
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from uuid import uuid4
import xml.etree.ElementTree as ET

try:
    from pypdf import PdfReader  # type: ignore
except Exception:
    PdfReader = None


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        cleaned = value.strip()
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
            cleaned = cleaned[1:-1]
        os.environ[key] = cleaned


ROOT = Path(__file__).resolve().parent
_load_env_file(ROOT / ".env")
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "server.log"
REQUEST_LOG_FILE = LOG_DIR / "requests.log"
RESEARCH_LOG_FILE = LOG_DIR / "research.log"
PROVIDER_LOG_FILE = LOG_DIR / "providers.log"
ERROR_LOG_FILE = LOG_DIR / "errors.log"
MAX_BODY_BYTES = 5 * 1024 * 1024
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.1")
OPENAI_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/responses")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "").strip()
OPENAI_COMPAT_BASE_URL = os.getenv("OPENAI_COMPAT_BASE_URL", "").rstrip("/")
OPENAI_COMPAT_PATH = os.getenv("OPENAI_COMPAT_PATH", "/chat/completions").strip() or "/chat/completions"
OPENAI_COMPAT_MODEL = os.getenv("OPENAI_COMPAT_MODEL", "").strip()
OPENAI_COMPAT_API_KEY = os.getenv("OPENAI_COMPAT_API_KEY", "").strip()
BEDROCK_BASE_URL = os.getenv("BEDROCK_BASE_URL", "").rstrip("/")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "").strip()
BEDROCK_MODEL = os.getenv("BEDROCK_MODEL", "").strip()
BEDROCK_INFERENCE_PROFILE = os.getenv("BEDROCK_INFERENCE_PROFILE", "").strip()
BEDROCK_API_KEY = os.getenv("BEDROCK_API_KEY", os.getenv("AWS_BEARER_TOKEN_BEDROCK", "")).strip()
CHATGPT_BRIDGE_BASE_URL = os.getenv("CHATGPT_BRIDGE_BASE_URL", os.getenv("CHATGPT_BRIDGE_URL", "")).rstrip("/")
CHATGPT_BRIDGE_PATH = os.getenv("CHATGPT_BRIDGE_PATH", "/chat/completions").strip() or "/chat/completions"
CHATGPT_BRIDGE_MODEL = os.getenv("CHATGPT_BRIDGE_MODEL", "").strip()
CHATGPT_BRIDGE_API_KEY = os.getenv("CHATGPT_BRIDGE_API_KEY", os.getenv("CHATGPT_BRIDGE_TOKEN", "")).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


OLLAMA_TIMEOUT = _env_int("OLLAMA_TIMEOUT", 120)
BEDROCK_TIMEOUT = _env_int("BEDROCK_TIMEOUT", 120)
CHATGPT_BRIDGE_TIMEOUT = _env_int("CHATGPT_BRIDGE_TIMEOUT", 120)
SEARCH_RESULTS = _env_int("SEARCH_RESULTS", 50)
SOURCE_RETRY_LIMIT = _env_int("SOURCE_RETRY_LIMIT", 10)
SOURCE_SELECTION_SNIPPET_CHARS = _env_int("SOURCE_SELECTION_SNIPPET_CHARS", 220)
SEARCH_TIMEOUT = _env_int("SEARCH_TIMEOUT", 20)
FETCH_TIMEOUT = _env_int("FETCH_TIMEOUT", 20)
FETCH_MAX_BYTES = _env_int("FETCH_MAX_BYTES", 1500000)
MODEL_INPUT_MAX_CHARS = _env_int("MODEL_INPUT_MAX_CHARS", 24000)
MODEL_OUTPUT_TOKENS = _env_int("MODEL_OUTPUT_TOKENS", 3500)
MAX_QUEUE_TAGS = _env_int("MAX_QUEUE_TAGS", 25)
SEARCH_ENGINE = os.getenv("SEARCH_ENGINE", "duckduckgo").strip().lower()
WEB_USE_ENV_PROXY = os.getenv("WEB_USE_ENV_PROXY", "false").strip().lower() in {"1", "true", "yes", "on"}
OUTBOUND_USE_ENV_PROXY = os.getenv("OUTBOUND_USE_ENV_PROXY", os.getenv("WEB_USE_ENV_PROXY", "false")).strip().lower() in {"1", "true", "yes", "on"}
SEARCH_PROVIDER_COOLDOWN_SEC = _env_int("SEARCH_PROVIDER_COOLDOWN_SEC", 600)
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)
BLOCKED_DOMAINS = [item.strip().lower() for item in os.getenv("BLOCKED_DOMAINS", "").split(",") if item.strip()]
SEMANTIC_SEARCH_DEFAULT = os.getenv("SEMANTIC_SEARCH_DEFAULT", "true").strip().lower() not in {"0", "false", "no", "off"}

ACADEMIC_BUCKET_TARGET = 4
THINK_TANK_BUCKET_TARGET = 2
WEB_BUCKET_TARGET = 2
MIXED_SOURCE_POOL_SIZE = ACADEMIC_BUCKET_TARGET + THINK_TANK_BUCKET_TARGET + WEB_BUCKET_TARGET

ACADEMIC_SEARCH_DOMAINS = [
    "doi.org",
    "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
    "nber.org",
    "ssrn.com",
    "sciencedirect.com",
    "springer.com",
    "onlinelibrary.wiley.com",
    "cambridge.org",
    "tandfonline.com",
    "sagepub.com",
    "jstor.org",
]

THINK_TANK_SEARCH_DOMAINS = [
    "rand.org",
    "brookings.edu",
    "cfr.org",
    "imf.org",
    "worldbank.org",
    "nber.org",
]


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "for",
    "from",
    "has",
    "have",
    "he",
    "her",
    "his",
    "i",
    "if",
    "in",
    "is",
    "it",
    "its",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "s",
    "she",
    "should",
    "that",
    "the",
    "their",
    "them",
    "there",
    "these",
    "they",
    "this",
    "to",
    "was",
    "we",
    "were",
    "what",
    "when",
    "which",
    "who",
    "will",
    "with",
    "you",
    "your",
}

DEBATE_CARD_GUIDANCE = {
    "sample_file_pattern": [
        "Each card should read like a debate file block: Heading4-style tag line, one cite line, then an evidence paragraph.",
        "Keep the full evidence paragraph for context instead of returning only a clipped quote.",
        "The words meant to be read in-round should be the strongest, most strategic part of the source and should sit inside the context paragraph when possible.",
    ],
    "citation_conventions": [
        "Prefer a short cite plus a bracketed full cite ending in //IT.",
        "A strong full cite usually includes author, date, title, publication or qualifications, source URL, and date of access.",
        "The cite should be one readable line, not a prose paragraph or metadata dump.",
    ],
    "evidence_selection_rules": [
        "Select the exact source language that proves the draft tag, not vague background setup.",
        "Prefer warrants, quantified findings, causal claims, comparative claims, or explicit author conclusions.",
        "Avoid scene-setting, rhetoric, transitions, duplicated sentences, and unsupported summaries.",
        "Underlined spans are the broader exact source language that supports the argument.",
        "Highlighted spans are the exact words or phrases the debater would read aloud; they may jump across non-contiguous phrases.",
        "Highlighted spans should usually sit inside underlined spans, but the model should never invent a separate read-text field.",
        "If the source does not support the tag with a useful quote, reject the source instead of forcing a card.",
    ],
    "validation_rules": [
        "Validation must separately check source fidelity, debate usefulness, and formatting quality.",
        "Mark the card weak if any underline or highlight is not grounded in the source, if the tag overclaims, or if the card is too generic to win an argument.",
        "Prefer a different source when the current one cannot produce a clean, quotable warrant.",
    ],
}


def _make_file_logger(name: str, path: Path) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = RotatingFileHandler(path, maxBytes=1_500_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


LOGGER = logging.getLogger("debate_card_cutter")
if not LOGGER.handlers:
    LOGGER.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_500_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(stream_handler)
    LOGGER.propagate = False

REQUEST_LOGGER = _make_file_logger("debate_card_cutter.requests", REQUEST_LOG_FILE)
RESEARCH_LOGGER = _make_file_logger("debate_card_cutter.research", RESEARCH_LOG_FILE)
PROVIDER_LOGGER = _make_file_logger("debate_card_cutter.providers", PROVIDER_LOG_FILE)
ERROR_LOGGER = _make_file_logger("debate_card_cutter.errors", ERROR_LOG_FILE)


class ResearchError(RuntimeError):
    pass


class ProviderAccessError(RuntimeError):
    pass


class ProviderQuotaError(ProviderAccessError):
    pass


SEARCH_PROVIDER_DISABLED_UNTIL: dict[str, float] = {}


def _json_response(handler: SimpleHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")
    try:
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        handler.end_headers()
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        _log_event(logging.WARNING, "response_write_failed", status=status, payload_keys=list(payload.keys()))


def _request_id(payload: dict[str, Any] | None = None) -> str:
    if isinstance(payload, dict):
        value = _clean_text(payload.get("_request_id"))
        if value:
            return value
    return "-"


def _log_event(level: int, event: str, **fields: Any) -> None:
    cleaned: dict[str, Any] = {"event": event}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, Path):
            cleaned[key] = str(value)
        elif isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        elif isinstance(value, dict):
            cleaned[key] = {str(k): v for k, v in value.items()}
        elif isinstance(value, list):
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    line = json.dumps(cleaned, ensure_ascii=True)
    LOGGER.log(level, line)
    if event.startswith("request_") or event.endswith("_response_write_failed") or event in {"response_write_failed", "binary_response_write_failed"}:
        REQUEST_LOGGER.log(level, line)
    if event.startswith("research_") or event.startswith("search_"):
        RESEARCH_LOGGER.log(level, line)
    if event.startswith("cut_") or event.startswith("provider_"):
        PROVIDER_LOGGER.log(level, line)
    if level >= logging.WARNING or event.endswith("_error") or event.endswith("_failed"):
        ERROR_LOGGER.log(level, line)


def _binary_response(
    handler: SimpleHTTPRequestHandler,
    status: int,
    body: bytes,
    *,
    content_type: str,
    filename: str,
) -> None:
    try:
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        handler.end_headers()
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        _log_event(logging.WARNING, "binary_response_write_failed", status=status, filename=filename)


def _read_json_body(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        raise ValueError("Request body is required")
    if length > MAX_BODY_BYTES:
        raise ValueError("Request body is too large")
    raw = handler.rfile.read(length)
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Request body must be valid UTF-8") from exc
    try:
        data = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    cleaned = _clean_text(value).lower()
    if cleaned in {"1", "true", "yes", "on"}:
        return True
    if cleaned in {"0", "false", "no", "off"}:
        return False
    return default


def to_array(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _parse_domain_blacklist(value: Any) -> list[str]:
    raw_items: list[str] = []
    if isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = re.split(r"[\s,;\r\n]+", _clean_text(value))

    domains: list[str] = []
    for item in [*BLOCKED_DOMAINS, *raw_items]:
        cleaned = _clean_text(item).lower().strip().lstrip(".")
        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            cleaned = (urlparse(cleaned).hostname or "").lower().lstrip(".")
        if cleaned and cleaned not in domains:
            domains.append(cleaned)
    return domains


def _hostname(url: str) -> str:
    return (urlparse(_clean_text(url)).hostname or "").lower().lstrip(".")


def _domain_is_blocked(url: str, blocked_domains: list[str]) -> bool:
    host = _hostname(url)
    if not host:
        return False
    for blocked in blocked_domains:
        blocked = blocked.lower().lstrip(".")
        if host == blocked or host.endswith(f".{blocked}"):
            return True
    return False


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    normalized = dict(payload)
    normalized["article_text"] = _clean_text(
        payload.get("article_text")
        or payload.get("articleText")
        or payload.get("source_text")
        or payload.get("sourceText")
        or payload.get("text")
    )
    normalized["resolution"] = _clean_text(payload.get("resolution"))
    normalized["side"] = _clean_text(payload.get("side"))
    normalized["source_title"] = _clean_text(payload.get("source_title") or payload.get("sourceTitle") or source.get("title"))
    normalized["source_author"] = _clean_text(payload.get("source_author") or payload.get("sourceAuthor") or source.get("author"))
    normalized["source_date"] = _clean_text(payload.get("source_date") or payload.get("sourceDate") or source.get("date"))
    normalized["source_url"] = _clean_text(payload.get("source_url") or payload.get("sourceUrl") or source.get("url"))
    normalized["source_publication"] = _clean_text(
        payload.get("source_publication")
        or payload.get("sourcePublication")
        or payload.get("publication")
        or payload.get("outlet")
        or payload.get("source_outlet")
        or source.get("publication")
        or source.get("outlet")
    )
    normalized["desired_cards"] = payload.get("desired_cards", payload.get("desiredCards"))
    normalized["emphasis"] = _clean_text(payload.get("emphasis") or payload.get("focus"))
    normalized["draft_tag"] = _clean_text(
        payload.get("draft_tag")
        or payload.get("draftTag")
        or payload.get("tag")
        or payload.get("topic")
    )
    normalized["domain_blacklist"] = _parse_domain_blacklist(payload.get("domain_blacklist") or payload.get("domainBlacklist") or payload.get("blocked_domains") or payload.get("blockedDomains"))
    normalized["draft_tags"] = _parse_queue_tags(payload.get("draft_tags") or payload.get("draftTags") or payload.get("queue_tags") or payload.get("queueTags") or payload.get("tags"))
    normalized["cards"] = [card for card in to_array(payload.get("cards")) if isinstance(card, dict)]
    normalized["title"] = _clean_text(payload.get("title") or payload.get("file_name") or payload.get("fileName"))
    normalized["provider"] = _clean_text(payload.get("provider") or payload.get("model_provider"))
    normalized["semantic_search_enabled"] = _parse_bool(
        payload.get("semantic_search_enabled")
        if payload.get("semantic_search_enabled") is not None
        else payload.get("semanticSearchEnabled"),
        SEMANTIC_SEARCH_DEFAULT,
    )
    normalized["query_pack"] = payload.get("query_pack") if isinstance(payload.get("query_pack"), dict) else (
        payload.get("queryPack") if isinstance(payload.get("queryPack"), dict) else {}
    )
    normalized["research_meta"] = payload.get("research_meta") if isinstance(payload.get("research_meta"), dict) else (
        payload.get("researchMeta") if isinstance(payload.get("researchMeta"), dict) else {}
    )
    return normalized


def _normalize_side(raw_side: str) -> str:
    side = raw_side.strip().lower()
    if side in {"pro", "affirmative", "aff", "yes", "support", "gov"}:
        return "pro"
    if side in {"con", "negative", "neg", "no", "opp", "oppose"}:
        return "con"
    return side or "pro"


def _normalize_desired_cards(value: Any) -> int:
    # The product now cuts one card per request and validates it recursively.
    return 1


def _truncate_for_prompt(text: str) -> str:
    return _truncate(text, MODEL_INPUT_MAX_CHARS)


def _normalize_web_url(url: str) -> str:
    candidate = _clean_text(url)
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"}:
        return candidate
    if candidate.startswith("//"):
        return f"https:{candidate}"
    if "." in candidate and " " not in candidate:
        return f"https://{candidate}"
    return ""


def _today_accessed() -> str:
    return date.today().strftime("%m-%d-%Y")


def _surname(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    parts = re.findall(r"[A-Za-z0-9'-]+", cleaned)
    if not parts:
        return cleaned
    return parts[-1]


def _extract_year(value: str) -> str:
    cleaned = _clean_text(value)
    match = re.search(r"(19|20)\d{2}", cleaned)
    if match:
        return match.group(0)[-2:]
    if cleaned:
        return cleaned[-2:]
    return date.today().strftime("%y")


def _build_short_citation(source: dict[str, Any]) -> str:
    author = _clean_text(source.get("author")) or _clean_text(source.get("title"))
    surname = _surname(author) or "Source"
    year = _extract_year(_clean_text(source.get("date") or source.get("published") or source.get("date_accessed")))
    return f"{surname} {year}".strip()


def _build_full_citation(source: dict[str, Any], date_accessed: str | None = None) -> str:
    date_accessed = _clean_text(date_accessed or _today_accessed())
    bits = [
        _clean_text(source.get("author")),
        _clean_text(source.get("date") or source.get("published")),
        _clean_text(source.get("title")),
        _clean_text(source.get("publication") or source.get("outlet")),
        _clean_text(source.get("url")),
    ]
    body = ", ".join(bit for bit in bits if bit)
    if date_accessed:
        body = f"{body}, DOA:{date_accessed}" if body else f"DOA:{date_accessed}"
    return f"[{body}]"


def _ensure_bracketed_citation(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    if cleaned.startswith("[") and cleaned.endswith("]"):
        return cleaned
    return f"[{cleaned}]"


def _text_from_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            chunk = _text_from_value(item)
            if chunk:
                chunks.append(chunk)
        return "".join(chunks).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "value", "output_text"):
            chunk = _text_from_value(value.get(key))
            if chunk:
                return chunk
        return ""
    return str(value).strip()


def _build_verbal_citation(source: dict[str, Any]) -> str:
    author = _clean_text(source.get("author"))
    qualification = _clean_text(source.get("author_qualifications"))
    title = _clean_text(source.get("title"))
    publication = _clean_text(source.get("publication") or source.get("outlet"))
    sentence = "According to"
    if author:
        sentence += f" {author}"
    if qualification:
        sentence += f", {qualification}"
    if publication:
        sentence += f" of {publication}"
    if title:
        sentence += f", {title}"
    return sentence.strip()


def _build_cite_line(short_citation: str, full_citation: str) -> str:
    short_citation = _clean_text(short_citation)
    full_citation = _ensure_bracketed_citation(full_citation)
    pieces = [piece for piece in [short_citation, full_citation] if piece]
    if not pieces:
        return ""
    return f"{' '.join(pieces)} //IT"


def _normalize_span_list(value: Any, full_context: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized_context = _clean_text(full_context)
    spans: list[dict[str, Any]] = []
    cursor = 0
    for item in value:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue

        text = _clean_text(item.get("text") or item.get("quote") or item.get("value"))
        if not text:
            continue

        start = item.get("start")
        end = item.get("end")
        try:
            start_int = int(start) if start is not None else -1
        except (TypeError, ValueError):
            start_int = -1
        try:
            end_int = int(end) if end is not None else -1
        except (TypeError, ValueError):
            end_int = -1

        if normalized_context:
            if start_int < 0 or end_int <= start_int or normalized_context[start_int:end_int] != text:
                start_int = normalized_context.find(text, max(0, cursor))
                if start_int < 0:
                    start_int = normalized_context.find(text)
                end_int = start_int + len(text) if start_int >= 0 else -1
        if start_int >= 0 and end_int > start_int:
            cursor = end_int

        normalized = {
            "text": text,
            "start": start_int if start_int >= 0 else None,
            "end": end_int if end_int > start_int else None,
        }
        reason = _clean_text(item.get("reason"))
        if reason:
            normalized["reason"] = reason
        spans.append(normalized)
    return spans


def _span_text(spans: list[dict[str, Any]]) -> str:
    return " ... ".join(_clean_text(span.get("text")) for span in spans if _clean_text(span.get("text")))


def _annotate_context_with_spans(full_context: str, underlined_spans: list[dict[str, Any]], highlighted_spans: list[dict[str, Any]]) -> str:
    full_context = _clean_text(full_context)
    if not full_context:
        return _span_text(highlighted_spans) or _span_text(underlined_spans)

    events: dict[int, list[str]] = {}
    for span in underlined_spans:
        start = span.get("start")
        end = span.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(full_context):
            events.setdefault(start, []).append("__")
            events.setdefault(end, []).append("__")
    for span in highlighted_spans:
        start = span.get("start")
        end = span.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(full_context):
            events.setdefault(start, []).append("[[")
            events.setdefault(end, []).append("]]")

    pieces: list[str] = []
    for index, char in enumerate(full_context):
        if index in events:
            pieces.extend(events[index])
        pieces.append(char)
    if len(full_context) in events:
        pieces.extend(events[len(full_context)])
    return "".join(pieces).strip()


def _build_formatted_card(card: dict[str, Any]) -> str:
    lines = []
    tag_line = _clean_text(card.get("tag_line") or card.get("title"))
    cite_line = _clean_text(card.get("cite_line"))
    full_context = _clean_text(card.get("full_context") or card.get("body"))
    underlined_spans = _normalize_span_list(card.get("underlined_spans") or card.get("underlinedSpans"), full_context)
    highlighted_spans = _normalize_span_list(card.get("highlighted_spans") or card.get("highlightedSpans"), full_context)

    if tag_line:
        lines.append(tag_line)
    if cite_line:
        lines.append(cite_line)
    if full_context:
        lines.append("")
        lines.append(_annotate_context_with_spans(full_context, underlined_spans, highlighted_spans))
    elif highlighted_spans or underlined_spans:
        lines.append("")
        lines.append(_span_text(highlighted_spans) or _span_text(underlined_spans))
    return "\n".join(lines).strip()


def _build_card_source(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": _clean_text(payload.get("source_id")),
        "title": _clean_text(payload.get("source_title")),
        "author": _clean_text(payload.get("source_author")),
        "author_qualifications": _clean_text(payload.get("author_qualifications") or payload.get("source_author_qualifications")),
        "date": _clean_text(payload.get("source_date")),
        "publication": _clean_text(payload.get("source_publication")),
        "url": _clean_text(payload.get("source_url")),
        "credibility_score": payload.get("credibility_score") if isinstance(payload.get("credibility_score"), (int, float)) else None,
        "credibility_notes": _clean_text(payload.get("credibility_notes")),
    }


def _resolve_openai_compat_url() -> str:
    base_url = OPENAI_COMPAT_BASE_URL
    if not base_url:
        return ""
    parsed = urlparse(base_url)
    if parsed.path.endswith("/chat/completions"):
        return base_url
    if parsed.path.endswith("/responses"):
        return base_url
    if parsed.path.endswith("/v1"):
        return f"{base_url}/chat/completions"
    return f"{base_url.rstrip('/')}/{OPENAI_COMPAT_PATH.lstrip('/')}"


def _resolve_chatgpt_bridge_url() -> str:
    base_url = CHATGPT_BRIDGE_BASE_URL
    if not base_url:
        return ""
    parsed = urlparse(base_url)
    if parsed.path.endswith("/chat/completions"):
        return base_url
    if parsed.path.endswith("/v1"):
        return f"{base_url}/chat/completions"
    return f"{base_url.rstrip('/')}/{CHATGPT_BRIDGE_PATH.lstrip('/')}"


def _bedrock_api_key() -> str:
    return BEDROCK_API_KEY or os.getenv("AWS_BEARER_TOKEN_BEDROCK", "").strip()


def _bedrock_configured() -> bool:
    return bool((BEDROCK_BASE_URL or BEDROCK_REGION) and (BEDROCK_INFERENCE_PROFILE or BEDROCK_MODEL) and _bedrock_api_key())


def _resolve_bedrock_model_id(model: str = "") -> str:
    explicit = _clean_text(model or BEDROCK_INFERENCE_PROFILE or BEDROCK_MODEL)
    if not explicit:
        return ""
    if explicit.startswith("arn:"):
        return explicit
    if explicit.startswith(("us.", "eu.", "apac.", "sa.")):
        return explicit
    if explicit.startswith("meta.llama4-"):
        return f"us.{explicit}"
    return explicit


def _resolve_bedrock_url(model: str = "") -> str:
    model_id = _resolve_bedrock_model_id(model)
    if not model_id:
        return ""
    base_url = BEDROCK_BASE_URL.rstrip("/")
    if not base_url:
        region = _clean_text(BEDROCK_REGION)
        if not region:
            return ""
        base_url = f"https://bedrock-runtime.{region}.amazonaws.com"
    parsed = urlparse(base_url)
    if parsed.path.endswith("/converse"):
        return base_url
    return f"{base_url}/model/{quote_plus(model_id).replace('+', '%20')}/converse"


def _normalize_provider(value: Any) -> str:
    provider = _clean_text(value).lower()
    if provider in {"ollama", "local", "local_model", "local-model"}:
        return "ollama"
    if provider in {"bedrock", "aws_bedrock", "aws-bedrock", "bedrock_converse", "aws"}:
        return "bedrock"
    if provider in {"chatgpt_bridge", "chatgpt_subscription", "chatgpt_proxy", "chatgpt-web", "chatgpt_web"}:
        return "chatgpt_bridge"
    if provider in {"openai_compat", "compat", "remote", "remote_model", "remote-model", "nvidia"}:
        return "openai_compat"
    if provider in {"openai", "api"}:
        return "openai"
    if provider in {"fallback", "heuristic"}:
        return "fallback"
    return ""


def _validate_requested_provider(payload: dict[str, Any]) -> str:
    requested = _clean_text(payload.get("provider") or payload.get("model_provider"))
    if not requested:
        return ""
    provider = _normalize_provider(requested)
    if provider:
        return provider
    raise ValueError("Unsupported provider. Use bedrock, ollama, chatgpt_bridge, openai_compat, openai, or fallback.")


def _provider_preference(payload: dict[str, Any]) -> list[str]:
    configured_provider = _validate_requested_provider(payload)
    if configured_provider:
        return [configured_provider, "fallback"]

    pinned_provider = _normalize_provider(os.getenv("LOCAL_MODEL_PROVIDER", ""))
    if OLLAMA_MODEL:
        return ["ollama", "bedrock", "chatgpt_bridge", "openai_compat", "openai", "fallback"]
    if pinned_provider == "ollama":
        return ["ollama", "bedrock", "chatgpt_bridge", "openai_compat", "openai", "fallback"]
    if pinned_provider == "bedrock":
        return ["bedrock", "fallback"]
    if _bedrock_configured():
        return ["bedrock", "fallback"]
    if CHATGPT_BRIDGE_BASE_URL and CHATGPT_BRIDGE_MODEL:
        return ["chatgpt_bridge", "openai_compat", "openai", "fallback"]
    if OPENAI_COMPAT_BASE_URL and OPENAI_COMPAT_MODEL:
        return ["openai_compat", "openai", "fallback"]
    if os.getenv("OPENAI_API_KEY", "").strip():
        return ["openai", "fallback"]
    return ["fallback"]


def _strict_provider_mode(payload: dict[str, Any]) -> bool:
    requested_provider = _normalize_provider(payload.get("provider") or payload.get("model_provider"))
    if requested_provider and requested_provider != "fallback":
        return True

    pinned_provider = _normalize_provider(os.getenv("LOCAL_MODEL_PROVIDER", ""))
    if pinned_provider and pinned_provider != "fallback":
        return True

    providers = [provider for provider in _provider_preference(payload) if provider != "fallback"]
    return len(providers) == 1


def _summarize_card_for_prompt(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "tag_line": _clean_text(card.get("tag_line") or card.get("title")),
        "short_citation": _clean_text(card.get("short_citation")),
        "underlined_text": _clean_text(card.get("underlined_text") or _span_text(to_array(card.get("underlined_spans")))),
        "highlighted_text": _clean_text(card.get("highlighted_text") or _span_text(to_array(card.get("highlighted_spans")))),
        "claim": _clean_text(card.get("claim")),
        "warrant": _clean_text(card.get("warrant")),
        "impact": _clean_text(card.get("impact")),
    }


def _summarize_candidate_for_prompt(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": int(candidate.get("index", 0) or 0),
        "source_id": _clean_text(candidate.get("source_id") or f"S{int(candidate.get('index', 0) or 0)}"),
        "engine": _clean_text(candidate.get("engine")),
        "title": _clean_text(candidate.get("title")),
        "url": _clean_text(candidate.get("url")),
        "domain": _hostname(candidate.get("url", "")),
        "author": _clean_text(candidate.get("author")),
        "publication": _clean_text(candidate.get("publication")),
        "published": _clean_text(candidate.get("published")),
        "score": round(float(candidate.get("score", 0.0)), 2),
        "overall_score": round(float(candidate.get("score", 0.0)), 3),
        "topical_fit_score": round(float(candidate.get("topical_fit_score", 0.0)), 3),
        "quote_strength_score": round(float(candidate.get("quote_strength_score", 0.0)), 3),
        "credibility_score": round(float(candidate.get("credibility_score", 0.0)), 3),
        "paper_score": round(float(candidate.get("paper_score", 0.0)), 3),
        "credibility_notes": _clean_text(candidate.get("credibility_notes")),
        "content_type": _clean_text(candidate.get("content_type")),
        "source_class": _clean_text(candidate.get("source_class")),
        "paper_verified": bool(candidate.get("paper_verified")),
        "paper_confidence": round(float(candidate.get("paper_confidence", 0.0)), 3),
        "doi": _clean_text(candidate.get("doi")),
        "pdf_url": _clean_text(candidate.get("pdf_url")),
        "paper_signals": _coerce_string_list(candidate.get("paper_signals")),
        "summary_signals": _coerce_string_list(candidate.get("summary_signals")),
        "fetch_error": _clean_text(candidate.get("fetch_error")),
        "snippet": _candidate_snippet(candidate),
    }


def _public_research_meta(research_meta: dict[str, Any]) -> dict[str, Any]:
    public_meta = dict(research_meta)
    public_meta.pop("candidates", None)
    return public_meta


def _build_prompt(
    payload: dict[str, Any],
    *,
    stage: str = "cut",
    candidate_card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requested_cards = _normalize_desired_cards(payload.get("desired_cards"))
    total_cards = max(1, requested_cards)
    card_number = _normalize_desired_cards(payload.get("card_number") or payload.get("card_index") or 1)
    card_number = max(1, min(card_number, total_cards))
    stage = _clean_text(stage).lower() or "cut"

    base_input = {
        "article_text": _truncate_for_prompt(_clean_text(payload.get("article_text"))),
        "resolution": _clean_text(payload.get("resolution")),
        "side": _normalize_side(_clean_text(payload.get("side"))),
        "source_title": _clean_text(payload.get("source_title")),
        "source_author": _clean_text(payload.get("source_author")),
        "source_date": _clean_text(payload.get("source_date")),
        "source_publication": _clean_text(payload.get("source_publication")),
        "source_url": _clean_text(payload.get("source_url")),
        "requested_cards": total_cards,
        "card_number": card_number,
        "emphasis": _clean_text(payload.get("emphasis")),
        "draft_tag": _clean_text(payload.get("draft_tag")),
        "search_mode": "semantic" if _parse_bool(payload.get("semantic_search_enabled"), SEMANTIC_SEARCH_DEFAULT) else "literal",
        "query_pack": payload.get("query_pack") if isinstance(payload.get("query_pack"), dict) else {},
        "domain_blacklist": _parse_domain_blacklist(payload.get("domain_blacklist")),
        "source_selection": payload.get("source_selection") if isinstance(payload.get("source_selection"), dict) else {},
        "prior_cards": [
            _summarize_card_for_prompt(card)
            for card in to_array(payload.get("prior_cards"))
            if isinstance(card, dict)
        ],
        "candidate_sources": [
            _summarize_candidate_for_prompt(candidate)
            for candidate in to_array(payload.get("candidate_sources"))
            if isinstance(candidate, dict)
        ],
        "reference_guide": DEBATE_CARD_GUIDANCE,
    }

    if candidate_card:
        base_input["candidate_card"] = {
            "tag_line": _clean_text(candidate_card.get("tag_line") or candidate_card.get("title")),
            "short_citation": _clean_text(candidate_card.get("short_citation")),
            "full_citation": _clean_text(candidate_card.get("full_citation") or candidate_card.get("citation")),
            "cite_line": _clean_text(candidate_card.get("cite_line")),
            "verbal_citation": _clean_text(candidate_card.get("verbal_citation")),
            "full_context": _clean_text(candidate_card.get("full_context") or candidate_card.get("body")),
            "underlined_spans": to_array(candidate_card.get("underlined_spans")),
            "highlighted_spans": to_array(candidate_card.get("highlighted_spans")),
            "claim": _clean_text(candidate_card.get("claim")),
            "warrant": _clean_text(candidate_card.get("warrant")),
            "impact": _clean_text(candidate_card.get("impact")),
            "formatted_card": _clean_text(candidate_card.get("formatted_card")),
        }

    base_schema = {
        "cards": [
            {
                "tag_line": "string",
                "short_citation": "string",
                "full_citation": "string",
                "cite_line": "string",
                "verbal_citation": "string",
                "author_qualifications": "string",
                "full_context": "string",
                "underlined_spans": [
                    {
                        "text": "string",
                        "start": "number",
                        "end": "number",
                        "reason": "string",
                    }
                ],
                "highlighted_spans": [
                    {
                        "text": "string",
                        "start": "number",
                        "end": "number",
                        "reason": "string",
                    }
                ],
                "date_accessed": "string",
                "source_url": "string",
                "formatted_card": "string",
                "claim": "string",
                "warrant": "string",
                "impact": "string",
                "title": "string",
                "tag": "string",
                "citation": "string",
                "card_text": "string",
                "body": "string",
                "evidence": "string",
                "source": {
                    "source_id": "string",
                    "title": "string",
                    "author": "string",
                    "author_qualifications": "string",
                    "date": "string",
                    "publication": "string",
                    "url": "string",
                    "credibility_score": "number",
                    "credibility_notes": "string",
                },
                "quoted_text": "string",
                "exact_excerpt": "string",
                "excerpt": "string",
                "highlighted_excerpt": "string",
            }
        ]
    }

    if stage == "select_source":
        return {
            "task": "Rank the source candidates for the strongest debate card source.",
            "requirements": [
                "Return strict JSON only.",
                "Review every candidate source using the metadata and snippet provided.",
                "Rank the sources from best to worst for cutting a debate card.",
                "Prefer the source that is most on-topic, most usable, and most likely to yield a precise, quotable card.",
                "If a source is weak, off-topic, paywalled, too thin, or duplicates another source, rank it lower.",
                "Return zero-based candidate indexes in ordered_indices.",
                "Return only one selection object.",
            ],
            "input": base_input,
            "output_schema": {
                "selection": {
                    "best_index": "number",
                    "ordered_indices": ["number"],
                    "rejected_indices": ["number"],
                    "notes": "string",
                    "reasons": ["string"],
                }
            },
        }

    if stage == "validate":
        return {
            "task": "Validate and revise one debate card against the provided source.",
            "requirements": [
                "Return strict JSON only.",
                "Review the proposed card for fidelity, usefulness, and debate usability.",
                "Treat this as a separate validation call, not a continuation of drafting.",
                "Check whether every underlined and highlighted span is actually grounded in the source article and whether the tag overclaims the source.",
                "Use query_pack and search_mode as context for what the user actually meant by the draft tag.",
                "If the card is weak, unsupported, too broad, duplicated, or awkwardly formatted, revise it.",
                "If the source cannot support the tag cleanly, mark the card not useful instead of forcing a rewrite.",
                "Treat draft_tag as the target claim. Keep the tag close to it, but tighten the tag if the source only supports a narrower claim.",
                "Underlines mean every exact source substring that materially supports the argument: warrants, statistics, causal links, comparisons, author conclusions, and impact language.",
                "Highlights mean only the exact words actually read aloud in-round.",
                "Highlighted spans may be discontiguous and can jump across sentences or phrases.",
                "Every underline and highlight span must be copied exactly from full_context and should include start/end offsets when possible. If offsets are uncertain, keep the exact text and leave the offsets empty instead of guessing.",
                "Reject or revise the card if highlighted spans are not exact source substrings, if highlights are not inside underlined support when offsets allow checking, or if the tag is stronger than the highlighted evidence.",
                "Return exactly one final card in a cards array.",
                "Include a validation object with useful, revised, passed, notes, issues, source_checks, confidence, tag_fit, span_grounding, and source_choice when possible.",
                "Keep the debate-file structure intact: tag line, short cite, bracketed cite line ending in //IT, then one readable evidence paragraph.",
                "Do not ask for or create a freeform read_text field; derive any read-aloud text only from highlighted_spans.",
                "Preserve compatibility by also returning the legacy fields title, tag, citation, card_text, body, evidence, excerpt, and highlighted_excerpt.",
            ],
            "input": base_input,
            "output_schema": {
                **base_schema,
                "validation": {
                    "useful": "boolean",
                    "revised": "boolean",
                    "passed": "boolean",
                    "notes": "string",
                    "issues": ["string"],
                    "source_checks": ["string"],
                    "confidence": "number",
                    "tag_fit": "string",
                    "span_grounding": "string",
                    "source_choice": "string",
                },
            },
        }

    return {
        "task": "Cut one debate card from the provided source or article.",
        "requirements": [
            "Return strict JSON only.",
            "Create exactly one card in the cards array.",
            "Every card must be concise, reusable in debate, and anchored to the source text.",
            "Prefer the card shape used in actual debate files: tag_line, short_citation, full_citation, verbal_citation, full_context, underlined_spans, highlighted_spans, date_accessed, and source_url.",
            "If available, include author_qualifications and optional claim, warrant, impact fields.",
            "Model the result after the user's actual files: tag line, short cite plus bracketed full cite ending with //IT, then a full evidence paragraph with clearly identified underlines and highlights.",
            "Use the reference guide to mimic actual debate-card conventions rather than generic article summarization.",
            "Use query_pack and search_mode as research context: search and source choice should follow the meaning of the tag, not only its literal words.",
            "Use candidate_sources and source_selection as the research packet: compare the top sources, then cut from the current selected source_id unless the source cannot support the draft tag.",
            "Keep source credibility and source usefulness separate: high credibility alone is not enough if the quote does not prove the tag, and a merely generic source should not outrank a better topical quote.",
            "Treat draft_tag as the target claim. The tag_line should stay close to that claim, but must not overclaim the source. If the source supports only a narrower version, tighten the tag_line rather than broadening the evidence.",
            "Determine which exact parts of the source are the strategic warrants, statistics, causal links, comparative claims, author conclusions, or impact language, and mark those as underlined_spans.",
            "Underlines are every exact source substring that materially supports the argument. Highlights are only the exact words actually read in-round.",
            "Highlights may be discontiguous and can jump phrase-to-phrase or sentence-to-sentence. A highlighted span should usually be a subset of an underlined span.",
            "Do not create a made-up read_text field. Select exact substrings from full_context and serialize them as spans.",
            "Do not highlight setup, throat-clearing, or filler merely because it appears near the quote.",
            "full_context should preserve surrounding context and should usually be two to six sentences or a short paragraph when the source supports it.",
            "Stay very close to the draft_tag. If the source only weakly supports the tag, prefer a tighter tag instead of a broader one.",
            "If the source is too vague to produce a useful card, return the best possible grounded card rather than inventing stronger language.",
            "If earlier cards were provided in prior_cards, avoid duplicating them and keep this card on a different useful angle.",
            "Preserve compatibility by also returning the legacy fields title, tag, citation, card_text, body, evidence, excerpt, and highlighted_excerpt.",
        ],
        "input": base_input,
        "output_schema": base_schema,
    }


def _normalize_model_cards(cards: Any, requested_cards: int) -> list[dict[str, Any]]:
    if not isinstance(cards, list):
        raise ValueError("Model response missing cards array")

    normalized_cards: list[dict[str, Any]] = []
    for card in cards[:requested_cards]:
        if not isinstance(card, dict):
            continue
        source = card.get("source") if isinstance(card.get("source"), dict) else {}
        raw_credibility_score = source.get("credibility_score") if isinstance(source.get("credibility_score"), (int, float)) else card.get("credibility_score", card.get("credibilityScore"))
        source_info = {
            "title": _clean_text(source.get("title") or card.get("source_title") or card.get("sourceTitle") or card.get("publication") or card.get("outlet")),
            "author": _clean_text(source.get("author") or card.get("source_author") or card.get("sourceAuthor") or card.get("author")),
            "author_qualifications": _clean_text(source.get("author_qualifications") or card.get("author_qualifications") or card.get("authorQualifications")),
            "date": _clean_text(source.get("date") or card.get("source_date") or card.get("sourceDate") or card.get("date")),
            "publication": _clean_text(source.get("publication") or source.get("outlet") or card.get("source_publication") or card.get("sourcePublication") or card.get("publication") or card.get("outlet")),
            "url": _clean_text(source.get("url") or card.get("source_url") or card.get("sourceUrl") or card.get("url")),
            "source_id": _clean_text(source.get("source_id") or card.get("source_id") or card.get("sourceId")),
            "credibility_score": raw_credibility_score if isinstance(raw_credibility_score, (int, float)) else None,
            "credibility_notes": _clean_text(source.get("credibility_notes") or card.get("credibility_notes") or card.get("credibilityNotes")),
        }
        tag_line = _clean_text(card.get("tag_line") or card.get("tagLine") or card.get("title") or card.get("heading") or card.get("tag"))
        full_context = _clean_text(card.get("full_context") or card.get("fullContext") or card.get("body") or card.get("card_text") or card.get("cardText") or card.get("evidence") or card.get("read_text") or card.get("highlighted_text") or card.get("highlightedText"))
        underlined_spans = _normalize_span_list(card.get("underlined_spans") or card.get("underlinedSpans"), full_context)
        highlighted_spans = _normalize_span_list(card.get("highlighted_spans") or card.get("highlightedSpans"), full_context)
        if not underlined_spans:
            fallback_underlined = _clean_text(card.get("underlined_text") or card.get("underlinedText") or card.get("read_text") or card.get("evidence") or card.get("card_text") or card.get("cardText"))
            if fallback_underlined:
                underlined_spans = _normalize_span_list([{"text": fallback_underlined}], full_context)
        if not highlighted_spans:
            fallback_highlight = _clean_text(card.get("highlighted_text") or card.get("highlightedText") or card.get("highlighted_excerpt") or card.get("highlightedExcerpt") or card.get("excerpt") or card.get("read_text"))
            if fallback_highlight:
                highlighted_spans = _normalize_span_list([{"text": fallback_highlight}], full_context)
        if not underlined_spans and highlighted_spans:
            underlined_spans = [dict(span) for span in highlighted_spans]

        underlined_text = _span_text(underlined_spans)
        highlighted_text = _span_text(highlighted_spans) or _clean_text(card.get("highlighted_text") or card.get("highlightedText") or card.get("highlighted_excerpt") or card.get("highlightedExcerpt") or card.get("excerpt"))
        read_text = highlighted_text or _clean_text(card.get("read_text") or card.get("highlighted_text") or card.get("highlightedText") or card.get("highlighted_excerpt") or card.get("highlightedExcerpt") or card.get("excerpt") or card.get("evidence") or card.get("card_text") or card.get("cardText"))
        short_citation = _clean_text(card.get("short_citation") or card.get("shortCitation")) or _build_short_citation(source_info)
        full_citation = _clean_text(card.get("full_citation") or card.get("fullCitation")) or _build_full_citation(source_info, _clean_text(card.get("date_accessed") or card.get("dateAccessed") or card.get("dox")) or _today_accessed())
        cite_line = _clean_text(card.get("cite_line") or card.get("citeLine")) or _build_cite_line(short_citation, full_citation)
        verbal_citation = _clean_text(card.get("verbal_citation") or card.get("verbalCitation")) or _build_verbal_citation(source_info)
        date_accessed = _clean_text(card.get("date_accessed") or card.get("dateAccessed") or card.get("dox")) or _today_accessed()
        exact_excerpt = _clean_text(card.get("exact_excerpt") or card.get("exactExcerpt") or card.get("quoted_text") or card.get("quotedText") or card.get("excerpt") or highlighted_text or read_text)
        claim = _clean_text(card.get("claim") or card.get("takeaway") or card.get("thesis"))
        warrant = _clean_text(card.get("warrant") or card.get("reason") or card.get("analysis"))
        impact = _clean_text(card.get("impact") or card.get("significance") or card.get("implication"))
        source_url = _clean_text(card.get("source_url") or card.get("sourceUrl") or source_info["url"])
        author_qualifications = _clean_text(card.get("author_qualifications") or card.get("authorQualifications") or source_info["author_qualifications"])
        normalized = {
            "tag_line": tag_line,
            "short_citation": short_citation,
            "full_citation": full_citation,
            "cite_line": cite_line,
            "verbal_citation": verbal_citation,
            "author_qualifications": author_qualifications,
            "underlined_spans": underlined_spans,
            "highlighted_spans": highlighted_spans,
            "underlined_text": underlined_text,
            "full_context": full_context,
            "quoted_text": exact_excerpt,
            "exact_excerpt": exact_excerpt,
            "highlighted_text": highlighted_text,
            "date_accessed": date_accessed,
            "source_url": source_url,
            "claim": claim,
            "warrant": warrant,
            "impact": impact,
            "title": tag_line,
            "tag": tag_line,
            "citation": full_citation or short_citation,
            "card_text": full_context or highlighted_text,
            "body": full_context,
            "evidence": full_context or highlighted_text,
            "source": {
                **source_info,
            },
            "excerpt": highlighted_text or read_text,
            "highlighted_excerpt": highlighted_text or read_text,
        }
        validation = _normalize_validation_meta(card.get("validation"))
        if validation:
            normalized["validation"] = validation
        normalized["formatted_card"] = _build_formatted_card(normalized)
        normalized_cards.append(normalized)

    if not normalized_cards:
        raise ValueError("Model response returned no usable cards")
    return normalized_cards


def _strip_html(fragment: str) -> str:
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    fragment = unescape(fragment)
    fragment = re.sub(r"\s+", " ", fragment).strip()
    return fragment


def _score_terms(text: str) -> set[str]:
    return {token for token in _word_tokens(text) if token not in STOPWORDS}


class _VisibleTextExtractor(HTMLParser):
    block_tags = {
        "article",
        "aside",
        "div",
        "footer",
        "header",
        "li",
        "main",
        "p",
        "section",
        "tr",
    }
    ignore_tags = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.meta: dict[str, str] = {}
        self.title_parts: list[str] = []
        self._ignore_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if tag in self.ignore_tags:
            self._ignore_depth += 1
            return
        if tag == "br" or tag in self.block_tags:
            self.chunks.append("\n")
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            key = (attr_map.get("property") or attr_map.get("name") or "").strip().lower()
            content = _clean_text(attr_map.get("content"))
            if key and content and key in {"og:title", "title", "twitter:title", "description", "og:description", "article:author", "author", "article:published_time", "pubdate", "date"}:
                self.meta[key] = content

    def handle_endtag(self, tag: str) -> None:
        if tag in self.ignore_tags and self._ignore_depth > 0:
            self._ignore_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        if tag in self.block_tags:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignore_depth > 0:
            return
        text = _clean_text(data)
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        self.chunks.append(text)


def _parse_html_text(html_text: str) -> dict[str, Any]:
    parser = _VisibleTextExtractor()
    parser.feed(html_text)
    parser.close()

    raw_text = "\n".join(parser.chunks)
    lines: list[str] = []
    for line in raw_text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if len(line) < 18 and len(line.split()) < 4 and not re.search(r"[.!?:;]$", line):
            continue
        lines.append(line)

    body_text = "\n".join(lines).strip()
    meta = parser.meta
    title = _clean_text(" ".join(parser.title_parts) or meta.get("og:title") or meta.get("title") or meta.get("twitter:title"))
    author = _clean_text(meta.get("article:author") or meta.get("author"))
    published = _clean_text(meta.get("article:published_time") or meta.get("pubdate") or meta.get("date"))
    description = _clean_text(meta.get("description") or meta.get("og:description"))
    return {
        "title": title,
        "author": author,
        "published": published,
        "description": description,
        "text": body_text or description or title,
    }


def _build_http_opener(*, use_env_proxy: bool = OUTBOUND_USE_ENV_PROXY) -> urllib.request.OpenerDirector:
    context = ssl.create_default_context()
    handlers: list[Any] = [urllib.request.HTTPSHandler(context=context)]
    if not use_env_proxy:
        handlers.insert(0, urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def _open_http_request(
    request: urllib.request.Request,
    *,
    timeout: int,
    use_env_proxy: bool = OUTBOUND_USE_ENV_PROXY,
):
    opener = _build_http_opener(use_env_proxy=use_env_proxy)
    return opener.open(request, timeout=timeout)


def _fetch_url_bytes(url: str, timeout: int, max_bytes: int) -> tuple[bytes, str, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "identity",
        },
    )
    with _open_http_request(request, timeout=timeout, use_env_proxy=WEB_USE_ENV_PROXY) as resp:
        body = resp.read(max_bytes + 1)
        content_type = resp.headers.get_content_type() or ""
        charset = resp.headers.get_content_charset() or "utf-8"
        final_url = resp.geturl()
    return body[:max_bytes], content_type, charset, final_url


def _decode_duckduckgo_redirect(url: str) -> str:
    normalized = _clean_text(url)
    if not normalized:
        return ""
    if normalized.startswith("//"):
        normalized = f"https:{normalized}"
    parsed = urlparse(normalized)
    if parsed.netloc.endswith("duckduckgo.com"):
        query = parse_qs(parsed.query)
        target = query.get("uddg", [""])[0]
        if target:
            return unquote(target)
    return normalized


def _search_duckduckgo(query: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    patterns = [
        re.compile(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S),
        re.compile(r'<a[^>]*href="([^"]*duckduckgo\.com/l/\?[^"]*uddg=[^"]+)"[^>]*>(.*?)</a>', re.I | re.S),
        re.compile(r'<a[^>]*rel="nofollow"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S),
    ]
    for offset in range(0, max(limit, 1), 30):
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}&s={offset}"
        body, _, charset, _ = _fetch_url_bytes(search_url, SEARCH_TIMEOUT, 500000)
        html_text = body.decode(charset, errors="replace")
        page_added = 0
        for pattern in patterns:
            for href, title_html in pattern.findall(html_text):
                url = _normalize_web_url(_decode_duckduckgo_redirect(href))
                if not url or url in seen:
                    continue
                seen.add(url)
                results.append(
                    {
                        "engine": "duckduckgo",
                        "title": _strip_html(title_html),
                        "url": url,
                        "query": query,
                    }
                )
                page_added += 1
                if len(results) >= limit:
                    return results
        if page_added == 0:
            break
    return results


def _search_bing_rss(query: str, limit: int) -> list[dict[str, Any]]:
    search_url = f"https://www.bing.com/search?format=rss&q={quote_plus(query)}"
    body, _, charset, _ = _fetch_url_bytes(search_url, SEARCH_TIMEOUT, 500000)
    xml_text = body.decode(charset, errors="replace")
    root = ET.fromstring(xml_text)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in root.findall(".//item"):
        title = _clean_text(item.findtext("title"))
        url = _normalize_web_url(_clean_text(item.findtext("link")))
        if not title or not url or url in seen:
            continue
        seen.add(url)
        results.append(
            {
                "engine": "bing_rss",
                "title": title,
                "url": url,
                "query": query,
            }
        )
        if len(results) >= limit:
            break
    return results


def _search_bing(query: str, limit: int) -> list[dict[str, Any]]:
    try:
        rss_results = _search_bing_rss(query, limit)
        if rss_results:
            return rss_results
    except Exception:
        pass
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    pattern = re.compile(r'<li[^>]*class="[^"]*\bb_algo\b[^"]*"[^>]*>.*?<h2><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
    for start in range(1, max(limit, 1) + 1, 10):
        search_url = f"https://www.bing.com/search?q={quote_plus(query)}&first={start}"
        body, _, charset, _ = _fetch_url_bytes(search_url, SEARCH_TIMEOUT, 500000)
        html_text = body.decode(charset, errors="replace")
        page_added = 0
        for href, title_html in pattern.findall(html_text):
            url = _normalize_web_url(href)
            if not url or url in seen:
                continue
            seen.add(url)
            results.append(
                {
                    "engine": "bing",
                    "title": _strip_html(title_html),
                    "url": url,
                    "query": query,
                }
            )
            page_added += 1
            if len(results) >= limit:
                return results
        if page_added == 0:
            break
    return results


def _search_web(query: str, limit: int) -> list[dict[str, Any]]:
    query = _clean_text(query)
    if not query:
        return []

    providers = [SEARCH_ENGINE] if SEARCH_ENGINE else []
    if "duckduckgo" not in providers:
        providers.append("duckduckgo")
    if "bing" not in providers:
        providers.append("bing")

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    now = time.monotonic()
    for provider in providers:
        disabled_until = SEARCH_PROVIDER_DISABLED_UNTIL.get(provider, 0.0)
        if disabled_until > now:
            _log_event(
                logging.INFO,
                "search_provider_skipped",
                provider=provider,
                query=query,
                disabled_for_seconds=round(disabled_until - now, 2),
            )
            continue
        try:
            if provider == "bing":
                provider_results = _search_bing(query, limit)
            else:
                provider_results = _search_duckduckgo(query, limit)
        except Exception as exc:
            SEARCH_PROVIDER_DISABLED_UNTIL[provider] = time.monotonic() + SEARCH_PROVIDER_COOLDOWN_SEC
            _log_event(logging.WARNING, "search_provider_failed", provider=provider, query=query, error=str(exc))
            continue
        SEARCH_PROVIDER_DISABLED_UNTIL.pop(provider, None)
        _log_event(logging.INFO, "search_provider_results", provider=provider, query=query, result_count=len(provider_results))
        for item in provider_results:
            url = item.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            results.append(item)
            if len(results) >= limit:
                return results
    return results


def _extract_pdf_url_from_html(html_text: str, base_url: str) -> str:
    patterns = [
        re.compile(r'citation_pdf_url["\']?\s+content=["\']([^"\']+)["\']', re.I),
        re.compile(r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', re.I),
    ]
    for pattern in patterns:
        match = pattern.search(html_text)
        if match:
            return _normalize_web_url(urljoin(base_url, unescape(match.group(1))))
    return ""


def _extract_doi(text: str, url: str = "") -> str:
    doi_match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", f"{url} {text}", re.I)
    if doi_match:
        return doi_match.group(0).rstrip(").,;")
    parsed = urlparse(url)
    if parsed.netloc.endswith("doi.org"):
        return parsed.path.strip("/")
    return ""


def _extract_pdf_text(body: bytes) -> str:
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(io.BytesIO(body))
        return re.sub(r"\s+", " ", " ".join((page.extract_text() or "") for page in reader.pages)).strip()
    except Exception:
        return ""


def _fetch_article(url: str, timeout: int = FETCH_TIMEOUT, max_bytes: int = FETCH_MAX_BYTES) -> dict[str, Any]:
    body, content_type, charset, final_url = _fetch_url_bytes(url, timeout, max_bytes)
    if "pdf" in content_type or final_url.lower().endswith(".pdf"):
        extracted = _extract_pdf_text(body)
        return {
            "url": final_url,
            "landing_page_url": final_url,
            "title": "",
            "publication": urlparse(final_url).netloc,
            "author": "",
            "published": "",
            "description": "",
            "text": extracted,
            "content_type": content_type or "application/pdf",
            "byte_count": len(body),
            "pdf_url": final_url,
            "doi": _extract_doi("", final_url),
        }

    text = body.decode(charset, errors="replace")
    if "html" in content_type or "xml" in content_type or "<html" in text[:1000].lower():
        parsed = _parse_html_text(text)
        extracted = parsed["text"]
        return {
            "url": final_url,
            "landing_page_url": final_url,
            "title": parsed["title"],
            "publication": parsed["title"] or urlparse(final_url).netloc,
            "author": parsed["author"],
            "published": parsed["published"],
            "description": parsed["description"],
            "text": extracted,
            "content_type": content_type,
            "byte_count": len(body),
            "pdf_url": _extract_pdf_url_from_html(text, final_url),
            "doi": _extract_doi(text, final_url),
        }

    cleaned = re.sub(r"\s+", " ", text).strip()
    return {
        "url": final_url,
        "landing_page_url": final_url,
        "title": "",
        "publication": urlparse(final_url).netloc,
        "author": "",
        "published": "",
        "description": "",
        "text": cleaned,
        "content_type": content_type,
        "byte_count": len(body),
        "pdf_url": final_url if final_url.lower().endswith(".pdf") else "",
        "doi": _extract_doi(cleaned, final_url),
    }


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", _clean_text(value)).strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


def _coerce_string_list(value: Any) -> list[str]:
    return _dedupe_strings([_clean_text(item) for item in to_array(value) if _clean_text(item)])


def _build_query_phrase(*parts: str) -> str:
    return re.sub(r"\s+", " ", " ".join(_clean_text(part) for part in parts if _clean_text(part))).strip()


def _heuristic_query_pack(payload: dict[str, Any], *, semantic_enabled: bool) -> dict[str, Any]:
    draft_tag = _clean_text(payload.get("draft_tag"))
    resolution = _clean_text(payload.get("resolution"))
    emphasis = _clean_text(payload.get("emphasis"))
    literal_query = _build_query_phrase(draft_tag, resolution, emphasis)
    must_have_terms = sorted(_score_terms(draft_tag or literal_query))[:8]
    avoid_terms = ["podcast", "news", "press release", "summary", "overview", "blog"]

    if not semantic_enabled:
        return {
            "intent_claim": draft_tag or literal_query,
            "literal_query": literal_query,
            "semantic_queries": [literal_query] if literal_query else [],
            "academic_queries": [_build_query_phrase(literal_query, "study evidence paper pdf doi")],
            "think_tank_queries": [_build_query_phrase(literal_query, "report analysis policy brief")],
            "fallback_web_queries": [literal_query],
            "must_have_terms": must_have_terms,
            "avoid_terms": avoid_terms,
            "explanation": "Literal search mode keeps the tag close to the original wording and adds light evidence-oriented query templates.",
        }

    intent_claim = draft_tag or literal_query
    semantic_queries = _dedupe_strings(
        [
            literal_query,
            _build_query_phrase(intent_claim, "evidence"),
            _build_query_phrase(intent_claim, "causes effects"),
            _build_query_phrase(intent_claim, "study report analysis"),
            _build_query_phrase(emphasis, intent_claim, resolution),
        ]
    )
    return {
        "intent_claim": intent_claim,
        "literal_query": literal_query,
        "semantic_queries": semantic_queries,
        "academic_queries": _dedupe_strings(
            [
                _build_query_phrase(intent_claim, "study evidence paper pdf doi"),
                _build_query_phrase(intent_claim, "journal article abstract"),
                _build_query_phrase(intent_claim, resolution, "working paper"),
            ]
        ),
        "think_tank_queries": _dedupe_strings(
            [
                _build_query_phrase(intent_claim, "report analysis"),
                _build_query_phrase(intent_claim, emphasis, "policy brief"),
            ]
        ),
        "fallback_web_queries": _dedupe_strings(
            [
                literal_query,
                _build_query_phrase(intent_claim, "evidence"),
                _build_query_phrase(intent_claim, emphasis),
            ]
        ),
        "must_have_terms": must_have_terms,
        "avoid_terms": avoid_terms,
        "explanation": "Heuristic semantic mode expands the tag into meaning-adjacent evidence, causation, and report-oriented search strings without changing the claim.",
    }


def _build_query_refinement_prompt(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": "Refine a debate draft tag into meaning-based research queries.",
        "requirements": [
            "Return strict JSON only.",
            "Interpret the meaning of the draft_tag rather than searching only for its exact wording.",
            "Preserve the same argument claim; do not broaden it into a different argument.",
            "Generate search strings that can find papers, think-tank reports, and strong public-web evidence about the same claim.",
            "Prefer causal, mechanism, impact, or comparison language when it helps find better evidence.",
            "Include must_have_terms that should stay close to the claim and avoid_terms that reduce low-quality summary/news results.",
            "Keep each query concise enough for a search engine.",
        ],
        "input": {
            "draft_tag": _clean_text(payload.get("draft_tag")),
            "resolution": _clean_text(payload.get("resolution")),
            "side": _normalize_side(_clean_text(payload.get("side"))),
            "emphasis": _clean_text(payload.get("emphasis")),
        },
        "output_schema": {
            "intent_claim": "string",
            "literal_query": "string",
            "semantic_queries": ["string"],
            "academic_queries": ["string"],
            "think_tank_queries": ["string"],
            "fallback_web_queries": ["string"],
            "must_have_terms": ["string"],
            "avoid_terms": ["string"],
            "explanation": "string",
        },
    }


def _normalize_query_pack(raw: dict[str, Any], payload: dict[str, Any], *, semantic_enabled: bool) -> dict[str, Any]:
    heuristic = _heuristic_query_pack(payload, semantic_enabled=semantic_enabled)
    return {
        "intent_claim": _clean_text(raw.get("intent_claim")) or heuristic["intent_claim"],
        "literal_query": _clean_text(raw.get("literal_query")) or heuristic["literal_query"],
        "semantic_queries": _coerce_string_list(raw.get("semantic_queries")) or heuristic["semantic_queries"],
        "academic_queries": _coerce_string_list(raw.get("academic_queries")) or heuristic["academic_queries"],
        "think_tank_queries": _coerce_string_list(raw.get("think_tank_queries")) or heuristic["think_tank_queries"],
        "fallback_web_queries": _coerce_string_list(raw.get("fallback_web_queries")) or heuristic["fallback_web_queries"],
        "must_have_terms": _coerce_string_list(raw.get("must_have_terms")) or heuristic["must_have_terms"],
        "avoid_terms": _coerce_string_list(raw.get("avoid_terms")) or heuristic["avoid_terms"],
        "explanation": _clean_text(raw.get("explanation")) or heuristic["explanation"],
    }


def _refine_query_pack(payload: dict[str, Any]) -> tuple[dict[str, Any], str, bool, str]:
    semantic_enabled = _parse_bool(payload.get("semantic_search_enabled"), SEMANTIC_SEARCH_DEFAULT)
    search_mode = "semantic" if semantic_enabled else "literal"
    provided = payload.get("query_pack") if isinstance(payload.get("query_pack"), dict) else {}
    if provided:
        return _normalize_query_pack(provided, payload, semantic_enabled=semantic_enabled), search_mode, False, "provided"

    if not _clean_text(payload.get("draft_tag")):
        heuristic = _heuristic_query_pack(payload, semantic_enabled=semantic_enabled)
        return heuristic, search_mode, False, "heuristic"

    if semantic_enabled:
        prompt = _build_query_refinement_prompt(payload)
        for provider in _provider_preference(payload):
            if provider == "fallback":
                break
            try:
                refined = _call_provider_json(provider, prompt)
                return _normalize_query_pack(refined, payload, semantic_enabled=True), "semantic", True, provider
            except Exception:
                continue

    heuristic = _heuristic_query_pack(payload, semantic_enabled=semantic_enabled)
    return heuristic, search_mode, False, "heuristic"


def _research_query(payload: dict[str, Any]) -> str:
    pieces = [
        _clean_text(payload.get("draft_tag")),
        _clean_text(payload.get("resolution")),
        _clean_text(payload.get("emphasis")),
    ]
    query = " ".join(piece for piece in pieces if piece)
    return re.sub(r"\s+", " ", query).strip()


def _is_academic_host(host: str) -> bool:
    host = host.lower()
    if not host:
        return False
    return host.endswith(".edu") or any(domain in host for domain in ACADEMIC_SEARCH_DOMAINS)


def _is_think_tank_host(host: str) -> bool:
    host = host.lower()
    if not host:
        return False
    return any(domain in host for domain in THINK_TANK_SEARCH_DOMAINS)


def _normalized_title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean_text(title).lower()).strip()


def _summary_signals(candidate: dict[str, Any]) -> list[str]:
    haystack = " ".join(
        [
            _clean_text(candidate.get("title")).lower(),
            _clean_text(candidate.get("url")).lower(),
            _clean_text(candidate.get("description")).lower(),
        ]
    )
    signals: list[str] = []
    for token in ("news", "blog", "press", "release", "summary", "overview", "podcast", "insight", "magazine"):
        if token in haystack:
            signals.append(token)
    return signals


def _paper_signals(candidate: dict[str, Any]) -> list[str]:
    text = _clean_text(candidate.get("text"))
    title = _clean_text(candidate.get("title"))
    url = _clean_text(candidate.get("url"))
    signals: list[str] = []
    doi = _clean_text(candidate.get("doi"))
    pdf_url = _clean_text(candidate.get("pdf_url"))
    if doi:
        signals.append("doi")
    if pdf_url:
        signals.append("pdf")
    lower_text = text.lower()
    lower_url = url.lower()
    if any(marker in lower_text for marker in ("abstract", "introduction", "method", "results", "discussion", "references")):
        signals.append("paper_sections")
    if "arxiv.org" in lower_url:
        signals.append("arxiv")
    if "ssrn.com" in lower_url:
        signals.append("ssrn")
    if "nber.org" in lower_url or "working paper" in f"{title} {text}".lower():
        signals.append("working_paper")
    if "pubmed.ncbi.nlm.nih.gov" in lower_url:
        signals.append("pubmed")
    if re.search(r"\b(vol\.?|volume|issue|journal)\b", f"{title} {text}", re.I):
        signals.append("journal_metadata")
    return _dedupe_strings(signals)


def _classify_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    host = _hostname(candidate.get("url", ""))
    title = _clean_text(candidate.get("title"))
    text = _clean_text(candidate.get("text"))
    summary_signals = _summary_signals(candidate)
    paper_signals = _paper_signals(candidate)
    paper_confidence = 0.0
    if paper_signals:
        paper_confidence += min(0.75, 0.16 * len(paper_signals))
    if len(text) > 3000:
        paper_confidence += 0.12
    if _is_academic_host(host):
        paper_confidence += 0.12
    if summary_signals:
        paper_confidence -= min(0.4, 0.1 * len(summary_signals))
    paper_confidence = max(0.0, min(1.0, paper_confidence))

    source_class = "general_web"
    if _is_think_tank_host(host):
        source_class = "think_tank"
    if _is_academic_host(host) or paper_signals:
        source_class = "peer_reviewed"
        joined = " ".join(paper_signals).lower()
        if "arxiv" in joined or "ssrn" in joined:
            source_class = "preprint"
        elif "working_paper" in joined:
            source_class = "working_paper"
    if summary_signals and not paper_signals:
        source_class = "summary_or_news"

    paper_verified = source_class in {"peer_reviewed", "preprint", "working_paper"} and paper_confidence >= 0.45
    return {
        "source_class": source_class,
        "paper_verified": paper_verified,
        "paper_confidence": round(paper_confidence, 3),
        "paper_signals": paper_signals,
        "summary_signals": summary_signals,
        "summary_risk": round(min(1.0, len(summary_signals) * 0.2), 3),
    }


def _search_web_domains(query: str, limit: int, domains: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for domain in domains:
        filtered_query = _build_query_phrase(f"site:{domain}", query)
        for item in _search_web(filtered_query, min(limit, 6)):
            url = _clean_text(item.get("url"))
            host = _hostname(url)
            if not host or (host != domain and not host.endswith(f".{domain}")):
                continue
            if not url or url in seen:
                continue
            seen.add(url)
            results.append({**item, "seed_query": filtered_query, "seed_domain": domain})
            if len(results) >= limit:
                return results
    return results


def _collect_discovered_sources(query_pack: dict[str, Any], semantic_enabled: bool) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    discovered = {"academic": [], "think_tank": [], "general_web": []}
    executed_queries: list[dict[str, Any]] = []

    academic_queries = _coerce_string_list(query_pack.get("academic_queries"))
    think_tank_queries = _coerce_string_list(query_pack.get("think_tank_queries"))
    fallback_queries = _coerce_string_list(query_pack.get("fallback_web_queries"))
    literal_query = _clean_text(query_pack.get("literal_query"))

    if not semantic_enabled and literal_query:
        academic_queries = [_build_query_phrase(literal_query, "study evidence paper")]
        think_tank_queries = [_build_query_phrase(literal_query, "report analysis")]
        fallback_queries = [literal_query]

    for query in academic_queries[:3]:
        executed_queries.append({"stage": "academic", "query": query})
        discovered["academic"].extend(_search_web_domains(query, 8, ACADEMIC_SEARCH_DOMAINS))
    for query in think_tank_queries[:2]:
        executed_queries.append({"stage": "think_tank", "query": query})
        discovered["think_tank"].extend(_search_web_domains(query, 6, THINK_TANK_SEARCH_DOMAINS))
    for query in fallback_queries[:3]:
        executed_queries.append({"stage": "general_web", "query": query})
        discovered["general_web"].extend([{**item, "seed_query": query} for item in _search_web(query, 8)])

    return discovered, executed_queries

def _missing_source_fields(payload: dict[str, Any]) -> list[str]:
    fields = {
        "article_text": payload.get("article_text"),
        "source_title": payload.get("source_title"),
        "source_author": payload.get("source_author"),
        "source_date": payload.get("source_date"),
        "source_url": payload.get("source_url"),
        "source_publication": payload.get("source_publication"),
    }
    return [name for name, value in fields.items() if not _clean_text(value)]


def _domain_reputation_score(host: str) -> float:
    if not host:
        return 0.35
    if host.endswith(".gov") or host.endswith(".edu"):
        return 0.95
    if host.endswith(".org"):
        return 0.76
    reputable_substrings = (
        "reuters.com",
        "apnews.com",
        "rand.org",
        "brookings.edu",
        "foreignaffairs.com",
        "cfr.org",
        "imf.org",
        "worldbank.org",
        "nber.org",
        "nature.com",
        "science.org",
        "cambridge.org",
        "routledge.com",
        "jstor.org",
    )
    if any(part in host for part in reputable_substrings):
        return 0.84
    if any(part in host for part in ("substack.com", "blogspot.", "medium.com", "wordpress.com")):
        return 0.38
    return 0.58


def _candidate_metrics(candidate: dict[str, Any], query_terms: set[str], phrase: str) -> dict[str, Any]:
    title = _clean_text(candidate.get("title")).lower()
    description = _clean_text(candidate.get("description")).lower()
    text = _clean_text(candidate.get("text")).lower()
    host = _hostname(candidate.get("url", ""))
    source_class = _clean_text(candidate.get("source_class"))
    paper_verified = bool(candidate.get("paper_verified"))
    paper_confidence = float(candidate.get("paper_confidence", 0.0) or 0.0)
    summary_risk = float(candidate.get("summary_risk", 0.0) or 0.0)

    topic_points = 0.0
    for term in query_terms:
        if term in title:
            topic_points += 4
        if term in description:
            topic_points += 2
        if term in text:
            topic_points += 1
    if phrase and phrase in title:
        topic_points += 12
    if phrase and phrase in text:
        topic_points += 6

    quote_points = 0.0
    quote_points += min(len(text) / 1000.0, 8.0)
    if len(text) < 300:
        quote_points -= 3
    if re.search(r"\b(percent|million|billion|study|report|analysis|data|evidence|found|concludes|shows)\b", text, re.I):
        quote_points += 3.5
    if re.search(r"\b(because|therefore|causes|results in|leads to|increases|decreases|hurts|benefits)\b", text, re.I):
        quote_points += 2.5

    credibility_points = 0.0
    notes: list[str] = []
    domain_score = _domain_reputation_score(host)
    credibility_points += domain_score * 12
    if host:
        notes.append(f"Domain reputation baseline from {host}.")
    if _clean_text(candidate.get("author")):
        credibility_points += 3
        notes.append("Named author present.")
    if _clean_text(candidate.get("published")):
        credibility_points += 2
        notes.append("Publication date present.")
    if _clean_text(candidate.get("publication")):
        credibility_points += 2
        notes.append("Publication or outlet metadata present.")
    if str(candidate.get("url", "")).startswith("https://"):
        credibility_points += 1
    if paper_verified:
        credibility_points += 5
        notes.append("Verified as a likely full paper rather than a summary page.")
    elif source_class in {"peer_reviewed", "preprint", "working_paper"}:
        credibility_points += max(0.0, paper_confidence * 3.0)
    if source_class == "think_tank":
        credibility_points += 2
        notes.append("Think-tank or policy-report source.")
    if summary_risk:
        credibility_points -= min(6.0, summary_risk * 8.0)
        notes.append("Summary/news signals reduce confidence that this is the primary evidence source.")
    if _clean_text(candidate.get("fetch_error")):
        credibility_points -= 10
        notes.append("Fetch failed or source content was not extracted cleanly.")

    topical_fit_score = max(0.0, min(1.0, topic_points / 30.0))
    quote_strength_score = max(0.0, min(1.0, (quote_points + 3.0) / 18.0))
    credibility_score = max(0.0, min(1.0, credibility_points / 20.0))
    paper_score = max(0.0, min(1.0, paper_confidence))
    overall_score = round((topical_fit_score * 0.45) + (quote_strength_score * 0.22) + (credibility_score * 0.18) + (paper_score * 0.15), 4)
    return {
        "topical_fit_score": topical_fit_score,
        "quote_strength_score": quote_strength_score,
        "credibility_score": credibility_score,
        "paper_score": paper_score,
        "credibility_notes": " ".join(notes).strip(),
        "score": overall_score,
    }


def _candidate_snippet(candidate: dict[str, Any], max_chars: int = SOURCE_SELECTION_SNIPPET_CHARS) -> str:
    return _truncate(
        _clean_text(candidate.get("description"))
        or _clean_text(candidate.get("text")),
        max_chars,
    )


def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": int(candidate.get("index", 0) or 0),
        "source_id": _clean_text(candidate.get("source_id")),
        "engine": candidate.get("engine", ""),
        "title": _clean_text(candidate.get("title")),
        "url": _clean_text(candidate.get("url")),
        "domain": _hostname(candidate.get("url", "")),
        "author": _clean_text(candidate.get("author")),
        "publication": _clean_text(candidate.get("publication")),
        "date": _clean_text(candidate.get("published")),
        "score": round(float(candidate.get("score", 0.0)), 2),
        "overall_score": round(float(candidate.get("score", 0.0)), 3),
        "topical_fit_score": round(float(candidate.get("topical_fit_score", 0.0)), 3),
        "quote_strength_score": round(float(candidate.get("quote_strength_score", 0.0)), 3),
        "credibility_score": round(float(candidate.get("credibility_score", 0.0)), 3),
        "paper_score": round(float(candidate.get("paper_score", 0.0)), 3),
        "credibility_notes": _clean_text(candidate.get("credibility_notes")),
        "content_type": _clean_text(candidate.get("content_type")),
        "byte_count": int(candidate.get("byte_count", 0) or 0),
        "source_class": _clean_text(candidate.get("source_class")),
        "paper_verified": bool(candidate.get("paper_verified")),
        "paper_confidence": round(float(candidate.get("paper_confidence", 0.0)), 3),
        "doi": _clean_text(candidate.get("doi")),
        "pdf_url": _clean_text(candidate.get("pdf_url")),
        "paper_signals": _coerce_string_list(candidate.get("paper_signals")),
        "summary_signals": _coerce_string_list(candidate.get("summary_signals")),
        "fetch_error": _clean_text(candidate.get("fetch_error")),
        "snippet": _candidate_snippet(candidate),
    }


def _client_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        **_public_candidate(candidate),
        "text": _truncate(_clean_text(candidate.get("text")), min(MODEL_INPUT_MAX_CHARS, 12000)),
        "description": _clean_text(candidate.get("description")),
        "published": _clean_text(candidate.get("published")),
        "seed_query": _clean_text(candidate.get("seed_query")),
        "seed_domain": _clean_text(candidate.get("seed_domain")),
        "pool_bucket": _clean_text(candidate.get("pool_bucket")),
    }


def _candidate_pool_bucket(candidate: dict[str, Any]) -> str:
    source_class = _clean_text(candidate.get("source_class"))
    if bool(candidate.get("paper_verified")) or source_class in {"peer_reviewed", "preprint", "working_paper"}:
        return "academic"
    if source_class == "think_tank":
        return "think_tank"
    return "general_web"


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(candidate.get("score", 0.0) or 0.0),
        float(candidate.get("paper_confidence", 0.0) or 0.0),
        float(candidate.get("quote_strength_score", 0.0) or 0.0),
        float(candidate.get("credibility_score", 0.0) or 0.0),
    )


def _select_mixed_candidate_pool(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(candidates, key=_candidate_sort_key, reverse=True)
    selected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()

    def take_from_bucket(bucket_name: str, limit: int) -> None:
        for candidate in ranked:
            if len([item for item in selected if item.get("pool_bucket") == bucket_name]) >= limit:
                break
            if candidate.get("pool_bucket") != bucket_name:
                continue
            url_key = _normalize_web_url(candidate.get("url", ""))
            title_key = _normalized_title_key(candidate.get("title", ""))
            if url_key and url_key in seen_urls:
                continue
            if title_key and title_key in seen_titles:
                continue
            if url_key:
                seen_urls.add(url_key)
            if title_key:
                seen_titles.add(title_key)
            selected.append(candidate)

    take_from_bucket("academic", ACADEMIC_BUCKET_TARGET)
    take_from_bucket("think_tank", THINK_TANK_BUCKET_TARGET)
    take_from_bucket("general_web", WEB_BUCKET_TARGET)

    for candidate in ranked:
        if len(selected) >= MIXED_SOURCE_POOL_SIZE:
            break
        url_key = _normalize_web_url(candidate.get("url", ""))
        title_key = _normalized_title_key(candidate.get("title", ""))
        if url_key and url_key in seen_urls:
            continue
        if title_key and title_key in seen_titles:
            continue
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        selected.append(candidate)

    return [{**item, "source_id": f"S{index + 1}", "index": index + 1} for index, item in enumerate(selected[:MIXED_SOURCE_POOL_SIZE])]


def _research_sources(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = _request_id(payload)
    article_text = _clean_text(payload.get("article_text"))
    source_url = _normalize_web_url(_clean_text(payload.get("source_url")))
    draft_tag = _clean_text(payload.get("draft_tag"))
    semantic_enabled = _parse_bool(payload.get("semantic_search_enabled"), SEMANTIC_SEARCH_DEFAULT)
    query_pack, search_mode, query_refinement_used, query_refinement_provider = _refine_query_pack(payload)
    query = _clean_text(query_pack.get("literal_query")) or _research_query(payload)
    missing_fields = _missing_source_fields(payload)
    can_research = bool(draft_tag or source_url)
    blocked_domains = _parse_domain_blacklist(payload.get("domain_blacklist"))
    executed_queries: list[dict[str, Any]] = []
    intent_phrase = _clean_text(query_pack.get("intent_claim")) or draft_tag or query
    query_terms = _score_terms(" ".join([intent_phrase, " ".join(_coerce_string_list(query_pack.get("must_have_terms")))]))
    _log_event(
        logging.INFO,
        "research_start",
        request_id=request_id,
        search_mode=search_mode,
        semantic_enabled=semantic_enabled,
        draft_tag=draft_tag,
        source_url=source_url,
        has_article_text=bool(article_text),
        blocked_domains=blocked_domains,
    )
    _log_event(
        logging.INFO,
        "research_query_pack",
        request_id=request_id,
        query=query,
        query_refinement_used=query_refinement_used,
        query_refinement_provider=query_refinement_provider,
        intent_claim=intent_phrase,
    )

    if source_url and _domain_is_blocked(source_url, blocked_domains):
        raise ValueError(f"source_url is blocked by the current domain blacklist: {source_url}")

    if article_text and (not missing_fields or not can_research):
        provided_selected = {
            "source_id": _clean_text(payload.get("source_id")) or "S1",
            "title": _clean_text(payload.get("source_title")),
            "publication": _clean_text(payload.get("source_publication")),
            "author": _clean_text(payload.get("source_author")),
            "published": _clean_text(payload.get("source_date")),
            "url": source_url or _clean_text(payload.get("source_url")),
            "text": article_text,
            "description": "",
            "engine": "provided",
        }
        provided_selected.update(_classify_candidate(provided_selected))
        provided_selected.update(_candidate_metrics(provided_selected, query_terms, intent_phrase.lower()))
        return {
            "used": False,
            "query": query,
            "search_mode": search_mode,
            "query_pack": query_pack,
            "query_refinement_used": query_refinement_used,
            "query_refinement_provider": query_refinement_provider,
            "executed_queries": executed_queries,
            "sources": [_public_candidate(provided_selected)],
            "candidates": [_client_candidate(provided_selected)],
            "selected": {
                **_public_candidate(provided_selected),
                "text": _truncate(article_text, 4000),
            },
            "article_text": article_text,
            "_candidates": [provided_selected],
            "missing_fields": missing_fields,
            "blocked_domains": blocked_domains,
        }

    discovered_by_bucket = {"academic": [], "think_tank": [], "general_web": []}
    prefetched_candidates: list[dict[str, Any]] = []
    if article_text:
        provided_candidate = {
            "engine": "provided_text",
            "title": _clean_text(payload.get("source_title")),
            "publication": _clean_text(payload.get("source_publication")),
            "author": _clean_text(payload.get("source_author")),
            "published": _clean_text(payload.get("source_date")),
            "url": source_url,
            "text": article_text,
            "description": "",
            "content_type": "text/plain",
            "byte_count": len(article_text.encode("utf-8")),
        }
        provided_candidate.update(_classify_candidate(provided_candidate))
        provided_candidate["pool_bucket"] = _candidate_pool_bucket(provided_candidate)
        prefetched_candidates.append(provided_candidate)
    if source_url:
        discovered_by_bucket["general_web"].append(
            {
                "engine": "provided",
                "title": _clean_text(payload.get("source_title")),
                "url": source_url,
                "query": query,
                "seed_query": query,
                "discovered_stage": "provided",
            }
        )

    if query or semantic_enabled:
        discovered_search, executed_queries = _collect_discovered_sources(query_pack, semantic_enabled)
        for bucket_name, items in discovered_search.items():
            discovered_by_bucket[bucket_name].extend(items)
        _log_event(
            logging.INFO,
            "research_discovered",
            request_id=request_id,
            academic=len(discovered_by_bucket["academic"]),
            think_tank=len(discovered_by_bucket["think_tank"]),
            general_web=len(discovered_by_bucket["general_web"]),
            executed_queries=executed_queries,
        )
    elif source_url:
        pass
    else:
        raise ValueError("article_text, source_url, or draft_tag is required")

    discovered: list[dict[str, Any]] = []
    for bucket_name, items in discovered_by_bucket.items():
        for item in items:
            if _domain_is_blocked(item.get("url", ""), blocked_domains):
                continue
            discovered.append({**item, "discovered_bucket": bucket_name})
    _log_event(
        logging.INFO,
        "research_filtered_discovered",
        request_id=request_id,
        discovered=len(discovered),
        blocked_domains=blocked_domains,
    )

    fetched: list[dict[str, Any]] = list(prefetched_candidates)
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for item in prefetched_candidates:
        url_key = _normalize_web_url(item.get("url", ""))
        title_key = _normalized_title_key(item.get("title", ""))
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
    for item in discovered:
        url = _normalize_web_url(item.get("url", ""))
        if not url or url in seen_urls:
            continue
        title_key = _normalized_title_key(item.get("title", ""))
        if title_key and title_key in seen_titles:
            continue
        seen_urls.add(url)
        if title_key:
            seen_titles.add(title_key)
        try:
            fetched_item = _fetch_article(url)
        except Exception as exc:
            item = {
                **item,
                "fetch_error": str(exc),
                "score": -999,
                "text": "",
                "content_type": "",
            }
            item.update(_classify_candidate(item))
            item["pool_bucket"] = _candidate_pool_bucket(item)
            fetched.append(item)
            continue
        item = {
            **item,
            **fetched_item,
        }
        item.update(_classify_candidate(item))
        item["pool_bucket"] = _candidate_pool_bucket(item)
        fetched.append(item)

    if not fetched:
        _log_event(
            logging.WARNING,
            "research_no_fetchable_sources",
            request_id=request_id,
            discovered=len(discovered),
            query=query,
            search_mode=search_mode,
        )
        raise ResearchError("No fetchable sources found")

    phrase = intent_phrase.lower()
    for item in fetched:
        item.update(_candidate_metrics(item, query_terms, phrase))
    mixed_pool = _select_mixed_candidate_pool(fetched)
    if not mixed_pool:
        _log_event(
            logging.WARNING,
            "research_no_usable_candidates",
            request_id=request_id,
            fetched=len(fetched),
            query=query,
            search_mode=search_mode,
        )
        raise ResearchError("No usable candidate sources found after filtering")
    selected = mixed_pool[0]
    selected_text = _clean_text(selected.get("text"))
    if not selected_text and selected.get("description"):
        selected_text = _clean_text(selected.get("description"))
    if not selected_text and intent_phrase:
        selected_text = intent_phrase
    _log_event(
        logging.INFO,
        "research_complete",
        request_id=request_id,
        fetched=len(fetched),
        mixed_pool=len(mixed_pool),
        selected_source_id=selected.get("source_id"),
        selected_title=_clean_text(selected.get("title")),
        selected_url=_clean_text(selected.get("url")),
        selected_bucket=_clean_text(selected.get("pool_bucket")),
    )

    return {
        "used": True,
        "query": query,
        "search_mode": search_mode,
        "query_pack": query_pack,
        "query_refinement_used": query_refinement_used,
        "query_refinement_provider": query_refinement_provider,
        "executed_queries": executed_queries,
        "sources": [_public_candidate(item) for item in mixed_pool],
        "candidates": [_client_candidate(item) for item in mixed_pool],
        "selected": {
            **_public_candidate(selected),
            "engine": selected.get("engine", ""),
            "title": _clean_text(selected.get("title") or payload.get("source_title")),
            "publication": _clean_text(selected.get("publication") or payload.get("source_publication")),
            "author": _clean_text(selected.get("author") or payload.get("source_author")),
            "date": _clean_text(selected.get("published") or payload.get("source_date")),
            "url": _clean_text(selected.get("url") or source_url or payload.get("source_url")),
            "text": _truncate(selected_text, 4000),
        },
        "article_text": selected_text,
        "_candidates": mixed_pool,
        "missing_fields": missing_fields,
        "blocked_domains": blocked_domains,
    }


def _split_sentences(text: str) -> list[str]:
    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])", text.replace("\r", " "))
    sentences = [chunk.strip() for chunk in raw if chunk.strip()]
    if sentences:
        return sentences
    return [line.strip() for line in text.splitlines() if line.strip()]


def _word_tokens(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z0-9']+", text)]


def _keyword_boost(text: str, emphasis: str, resolution: str, side: str) -> int:
    haystack = f"{text} {emphasis} {resolution} {side}".lower()
    score = 0
    for keyword in _word_tokens(emphasis) + _word_tokens(resolution):
        if keyword and keyword not in STOPWORDS and keyword in haystack:
            score += 2
    if side == "pro":
        for token in ("should", "must", "increase", "benefit", "solve", "improve"):
            if token in haystack:
                score += 1
    elif side == "con":
        for token in ("risk", "harm", "cost", "worsen", "limit", "prevent"):
            if token in haystack:
                score += 1
    return score


def _sentence_score(sentence: str, emphasis: str, resolution: str, side: str) -> float:
    tokens = [token for token in _word_tokens(sentence) if token not in STOPWORDS]
    if not tokens:
        return 0.0
    freq = Counter(tokens)
    score = sum(freq.values())
    score += 0.5 * len({token for token in tokens if len(token) > 6})
    score += 1.5 * _keyword_boost(sentence, emphasis, resolution, side)
    if len(sentence) > 300:
        score -= 0.5
    if re.search(r"\b(according to|reports?|study|data|analysis|research)\b", sentence, re.I):
        score += 2
    if re.search(r"\b(percent|million|billion|increase|decrease|rise|drop|cost)\b", sentence, re.I):
        score += 1.5
    return score


def _paragraphs(text: str) -> list[str]:
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n+", text.replace("\r", "\n")) if chunk.strip()]
    if chunks:
        return chunks
    return [line.strip() for line in text.splitlines() if line.strip()]


def _truncate(text: str, max_chars: int = 360) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def _build_citation(source: dict[str, Any]) -> str:
    bits = [
        _clean_text(source.get("author")),
        _clean_text(source.get("date")),
        _clean_text(source.get("title")),
        _clean_text(source.get("url")),
    ]
    return ", ".join(bit for bit in bits if bit)


def _build_fallback_cards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    article_text = _clean_text(
        payload.get("article_text")
        or payload.get("draft_tag")
        or payload.get("resolution")
        or payload.get("source_title")
        or payload.get("source_url")
        or "No source text available"
    )
    resolution = _clean_text(payload.get("resolution"))
    side = _normalize_side(_clean_text(payload.get("side")))
    emphasis = _clean_text(payload.get("emphasis") or payload.get("draft_tag"))
    source = _build_card_source(payload)
    date_accessed = _today_accessed()
    desired_cards = _normalize_desired_cards(payload.get("desired_cards"))

    paragraphs = _paragraphs(article_text)
    sentences = _split_sentences(article_text)
    scored_sentences = sorted(
        ((idx, sentence, _sentence_score(sentence, emphasis, resolution, side)) for idx, sentence in enumerate(sentences)),
        key=lambda item: (-item[2], item[0]),
    )
    used_indices: set[int] = set()
    cards: list[dict[str, Any]] = []

    for rank, (idx, sentence, _score) in enumerate(scored_sentences[:desired_cards]):
        if idx in used_indices:
            continue
        used_indices.add(idx)
        nearby = [sentence]
        if idx > 0:
            nearby.insert(0, sentences[idx - 1])
        if idx + 1 < len(sentences):
            nearby.append(sentences[idx + 1])
        full_context = _truncate(next((para for para in paragraphs if sentence in para), " ".join(nearby)), 2200)
        underlined_spans = _normalize_span_list([{"text": _truncate(sentence, 520), "reason": "Best fallback warrant from source text."}], full_context)
        highlighted_spans = [dict(span) for span in underlined_spans[:1]]
        highlighted_text = _span_text(highlighted_spans)
        tag_line = _truncate(
            _clean_text(payload.get("draft_tag")) or " - ".join(bit for bit in [resolution or "Debate card", f"Point {rank + 1}", emphasis] if bit),
            180,
        )
        short_citation = _build_short_citation(source)
        full_citation = _build_full_citation(source, date_accessed)
        cite_line = _build_cite_line(short_citation, full_citation)
        card = {
            "tag_line": tag_line,
            "short_citation": short_citation,
            "full_citation": full_citation,
            "cite_line": cite_line,
            "verbal_citation": _build_verbal_citation(source),
            "author_qualifications": _clean_text(source.get("author_qualifications")),
            "underlined_spans": underlined_spans,
            "highlighted_spans": highlighted_spans,
            "underlined_text": _span_text(underlined_spans),
            "full_context": full_context,
            "quoted_text": highlighted_text,
            "exact_excerpt": highlighted_text,
            "highlighted_text": highlighted_text,
            "date_accessed": date_accessed,
            "source_url": _clean_text(source.get("url")),
            "claim": _truncate(
                f"{emphasis or 'This card'} supports the {side} position.",
                240,
            ),
            "warrant": _truncate(
                f"This passage supports the {side} position because it connects to {resolution or 'the resolution'}.",
                240,
            ),
            "impact": _truncate(
                f"The card is prioritized for {emphasis or 'the core topic'} and should be usable as a debate block.",
                240,
            ),
            "title": tag_line,
            "tag": tag_line,
            "citation": full_citation,
            "card_text": full_context or highlighted_text,
            "body": full_context,
            "evidence": full_context or highlighted_text,
            "source": source,
            "excerpt": highlighted_text,
            "highlighted_excerpt": highlighted_text,
        }
        card["formatted_card"] = _build_formatted_card(card)
        cards.append(card)

    if not cards and article_text:
        excerpt = _truncate(article_text, 900)
        tag_line = _truncate(_clean_text(payload.get("draft_tag")) or resolution or "Debate card", 180)
        short_citation = _build_short_citation(source)
        full_citation = _build_full_citation(source, date_accessed)
        cite_line = _build_cite_line(short_citation, full_citation)
        underlined_spans = _normalize_span_list([{"text": excerpt, "reason": "Fallback excerpt from source text."}], excerpt)
        highlighted_spans = [dict(span) for span in underlined_spans[:1]]
        card = {
            "tag_line": tag_line,
            "short_citation": short_citation,
            "full_citation": full_citation,
            "cite_line": cite_line,
            "verbal_citation": _build_verbal_citation(source),
            "author_qualifications": _clean_text(source.get("author_qualifications")),
            "underlined_spans": underlined_spans,
            "highlighted_spans": highlighted_spans,
            "underlined_text": _span_text(underlined_spans),
            "full_context": excerpt,
            "quoted_text": excerpt,
            "exact_excerpt": excerpt,
            "highlighted_text": _span_text(highlighted_spans),
            "date_accessed": date_accessed,
            "source_url": _clean_text(source.get("url")),
            "claim": f"{emphasis or 'This card'} supports the {side} position.",
            "warrant": f"The article gives material relevant to the {side} side.",
            "impact": f"Use this as a general card on {emphasis or 'the topic'}.",
            "title": tag_line,
            "tag": tag_line,
            "citation": full_citation,
            "card_text": excerpt,
            "body": excerpt,
            "evidence": excerpt,
            "source": source,
            "excerpt": excerpt,
            "highlighted_excerpt": excerpt,
        }
        card["formatted_card"] = _build_formatted_card(card)
        cards.append(card)

    return cards[:desired_cards]


def _extract_text_from_response(response_json: dict[str, Any]) -> str:
    output_text = response_json.get("output_text")
    if output_text is not None:
        text = _text_from_value(output_text)
        if text:
            return text

    chunks: list[str] = []
    for output_item in response_json.get("output", []) or []:
        content = output_item.get("content", []) if isinstance(output_item, dict) else []
        for block in content:
            text = _text_from_value(block)
            if text:
                chunks.append(text)
    return "".join(chunks).strip()


def _parse_json_text(text: str) -> dict[str, Any]:
    if not text:
        raise ValueError("Empty model response")
    candidate = text.strip()
    candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
    candidate = re.sub(r"\s*```$", "", candidate)
    if candidate.startswith("{") and candidate.endswith("}"):
        return json.loads(candidate)
    start = candidate.find("{")
    if start < 0:
        raise ValueError("Model response did not contain JSON")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(candidate)):
        char = candidate[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(candidate[start : index + 1])
    raise ValueError("Model response contained incomplete JSON")


def _normalize_validation_issues(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_clean_text(item) for item in value if _clean_text(item)]
    if isinstance(value, dict):
        return [_clean_text(item) for item in value.values() if _clean_text(item)]
    text = _clean_text(value)
    return [text] if text else []


def _normalize_validation_meta(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = {"notes": value}
    if not isinstance(value, dict):
        return {}

    notes = _clean_text(
        value.get("notes")
        or value.get("summary")
        or value.get("feedback")
        or value.get("commentary")
        or value.get("explanation")
    )
    status = _clean_text(value.get("status") or value.get("result"))
    useful = value.get("useful")
    revised = value.get("revised")
    passed = value.get("passed")
    confidence = value.get("confidence")

    normalized: dict[str, Any] = {}
    if useful is not None:
        normalized["useful"] = bool(useful)
    if revised is not None:
        normalized["revised"] = bool(revised)
    if passed is not None:
        normalized["passed"] = bool(passed)
    if notes:
        normalized["notes"] = notes
    if status:
        normalized["status"] = status
    issues = _normalize_validation_issues(value.get("issues") or value.get("problems") or value.get("concerns"))
    if issues:
        normalized["issues"] = issues
    source_checks = _normalize_validation_issues(value.get("source_checks") or value.get("sourceChecks") or value.get("checks"))
    if source_checks:
        normalized["source_checks"] = source_checks
    if isinstance(confidence, (int, float)):
        normalized["confidence"] = confidence
    for key in ("tag_fit", "span_grounding", "source_choice"):
        detail = _clean_text(value.get(key))
        if detail:
            normalized[key] = detail
    return normalized


def _merge_validation_meta(*values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    issue_bucket: list[str] = []
    source_check_bucket: list[str] = []

    for value in values:
        candidate = _normalize_validation_meta(value)
        if not candidate:
            continue
        for key in ("useful", "revised", "passed", "notes", "status", "confidence", "tag_fit", "span_grounding", "source_choice"):
            if key in candidate:
                merged[key] = candidate[key]
        for item in candidate.get("issues", []):
            cleaned = _clean_text(item)
            if cleaned and cleaned not in issue_bucket:
                issue_bucket.append(cleaned)
        for item in candidate.get("source_checks", []):
            cleaned = _clean_text(item)
            if cleaned and cleaned not in source_check_bucket:
                source_check_bucket.append(cleaned)

    if issue_bucket:
        merged["issues"] = issue_bucket
    if source_check_bucket:
        merged["source_checks"] = source_check_bucket
    return merged


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", _clean_text(text)).strip()


def _token_overlap_ratio(left: str, right: str) -> float:
    left_tokens = _score_terms(left)
    right_tokens = _score_terms(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    return len(overlap) / max(1, len(left_tokens))


def _build_source_grounding_validation(card: dict[str, Any], article_text: str) -> dict[str, Any]:
    article_text = _clean_text(article_text)
    normalized_article = _normalize_space(article_text)
    full_context = _clean_text(card.get("full_context") or card.get("body"))
    underlined_spans = _normalize_span_list(card.get("underlined_spans") or card.get("underlinedSpans"), full_context)
    highlighted_spans = _normalize_span_list(card.get("highlighted_spans") or card.get("highlightedSpans"), full_context)
    highlighted_text = _span_text(highlighted_spans) or _clean_text(card.get("highlighted_text") or card.get("excerpt"))

    issues: list[str] = []
    source_checks: list[str] = []
    useful = True
    passed = True

    normalized_context = _normalize_space(full_context)
    if underlined_spans:
        bad_underlines = []
        for span in underlined_spans:
            span_text = _normalize_space(span.get("text"))
            if normalized_article and span_text and span_text in normalized_article:
                continue
            bad_underlines.append(_clean_text(span.get("text")))
        if bad_underlines:
            useful = False
            passed = False
            issues.append("Some underlined spans do not map cleanly onto the source article.")
        else:
            source_checks.append("All underlined spans map directly onto the source article text.")
    else:
        useful = False
        passed = False
        issues.append("Card is missing underlined_spans.")

    if full_context:
        source_checks.append("Card includes full_context.")
    else:
        useful = False
        passed = False
        issues.append("Card is missing full_context.")

    if highlighted_spans:
        bad_highlights = []
        if underlined_spans:
            underlined_ranges = [
                (span.get("start"), span.get("end"))
                for span in underlined_spans
                if isinstance(span.get("start"), int) and isinstance(span.get("end"), int)
            ]
        else:
            underlined_ranges = []
        for span in highlighted_spans:
            span_text = _normalize_space(span.get("text"))
            start = span.get("start")
            end = span.get("end")
            if normalized_context and span_text and span_text in normalized_context:
                if underlined_ranges and isinstance(start, int) and isinstance(end, int):
                    inside = any(isinstance(u_start, int) and isinstance(u_end, int) and u_start <= start and end <= u_end for u_start, u_end in underlined_ranges)
                    if not inside:
                        bad_highlights.append(_clean_text(span.get("text")))
                continue
            bad_highlights.append(_clean_text(span.get("text")))
        if bad_highlights:
            useful = False
            passed = False
            issues.append("Some highlighted spans are not grounded in full_context or are not inside underlined support.")
        else:
            source_checks.append("All highlighted spans appear inside full_context.")
    elif highlighted_text:
        normalized_highlight = _normalize_space(highlighted_text)
        if normalized_highlight and normalized_highlight in normalized_context:
            source_checks.append("highlighted_text appears inside the source context.")
        else:
            useful = False
            passed = False
            issues.append("highlighted_text is not grounded in the returned quote/context.")
    else:
        useful = False
        passed = False
        issues.append("Card is missing highlighted_spans.")

    notes = "Source grounding checks passed." if not issues else "Source grounding checks found fidelity problems."
    result: dict[str, Any] = {
        "useful": useful,
        "passed": passed,
        "notes": notes,
    }
    if issues:
        result["issues"] = issues
    if source_checks:
        result["source_checks"] = source_checks
    return result


def _extract_validation_meta(parsed: dict[str, Any]) -> dict[str, Any]:
    validation = _normalize_validation_meta(parsed.get("validation"))
    if validation:
        return validation

    cards = parsed.get("cards")
    if isinstance(cards, list) and cards and isinstance(cards[0], dict):
        validation = _normalize_validation_meta(cards[0].get("validation"))
        if validation:
            return validation

    notes = _clean_text(
        parsed.get("validation_notes")
        or parsed.get("notes")
        or parsed.get("review")
        or parsed.get("feedback")
        or parsed.get("commentary")
    )
    issues = _normalize_validation_issues(parsed.get("issues") or parsed.get("problems") or parsed.get("concerns"))
    if notes or issues:
        result: dict[str, Any] = {}
        if notes:
            result["notes"] = notes
        if issues:
            result["issues"] = issues
        return result
    return {}


def _validation_is_weak(validation: dict[str, Any] | None) -> bool:
    if not validation:
        return False

    if validation.get("useful") is False or validation.get("passed") is False:
        return True

    text = " ".join(
        _clean_text(part)
        for part in [
            validation.get("notes"),
            validation.get("status"),
            " ".join(to_array(validation.get("issues"))),
            " ".join(to_array(validation.get("source_checks"))),
        ]
    ).lower()
    weak_terms = [
        "weak",
        "unsupported",
        "irrelevant",
        "duplicate",
        "too broad",
        "thin",
        "not useful",
        "bad source",
        "source weak",
        "needs better source",
        "does not map cleanly",
        "missing underlined_spans",
        "missing highlighted_spans",
        "missing full_context",
        "not grounded",
    ]
    return any(term in text for term in weak_terms)


def _build_source_selection_prompt(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "task": "Choose the best source from a mixed candidate pool for cutting one debate card.",
        "requirements": [
            "Return strict JSON only.",
            "Rank the candidates by which source is most likely to produce a strong, specific, usable debate card.",
            "Assume the candidate list is a deliberately mixed pool of academic, think-tank, and high-quality general-web sources.",
            "Prefer sources with clear, quotable evidence and a direct connection to the draft tag, resolution, side, and emphasis.",
            "Use query_pack as the semantic research context. Choose the source that best proves the meaning of the tag, not merely the source that repeats the same surface words.",
            "Separate source usefulness from source credibility.",
            "Usefulness means the source contains precise, quotable evidence for the draft tag. Credibility means institutional or author reliability, recency, primary or academic status, and absence of obvious SEO, promo, or aggregator weakness.",
            "Prefer verified papers when they directly support the claim, but do not force a paper choice if a think-tank or web source more directly proves the tag.",
            "Reject summary pages about papers, prestige-only sources that are too generic, and sources that use similar words while proving a different claim.",
            "Do not let generic domain authority beat topical usefulness if the more credible source does not actually prove the tag.",
            "Avoid ranking weak, generic, duplicated, or irrelevant sources highly.",
            "Return selected_indices as a ranked list of 1-based candidate indices.",
        ],
        "input": {
            "draft_tag": _clean_text(payload.get("draft_tag")),
            "resolution": _clean_text(payload.get("resolution")),
            "side": _normalize_side(_clean_text(payload.get("side"))),
            "emphasis": _clean_text(payload.get("emphasis")),
            "search_mode": "semantic" if _parse_bool(payload.get("semantic_search_enabled"), SEMANTIC_SEARCH_DEFAULT) else "literal",
            "query_pack": payload.get("query_pack") if isinstance(payload.get("query_pack"), dict) else {},
            "domain_blacklist": _parse_domain_blacklist(payload.get("domain_blacklist")),
            "candidates": [
                {
                    "source_id": _clean_text(candidate.get("source_id") or f"S{index + 1}"),
                    "index": index + 1,
                    "title": _clean_text(candidate.get("title")),
                    "author": _clean_text(candidate.get("author")),
                    "publication": _clean_text(candidate.get("publication")),
                    "date": _clean_text(candidate.get("published")),
                    "url": _clean_text(candidate.get("url")),
                    "overall_score": round(float(candidate.get("score", 0.0)), 3),
                    "topical_fit_score": round(float(candidate.get("topical_fit_score", 0.0)), 3),
                    "quote_strength_score": round(float(candidate.get("quote_strength_score", 0.0)), 3),
                    "credibility_score": round(float(candidate.get("credibility_score", 0.0)), 3),
                    "paper_score": round(float(candidate.get("paper_score", 0.0)), 3),
                    "credibility_notes": _clean_text(candidate.get("credibility_notes")),
                    "source_class": _clean_text(candidate.get("source_class")),
                    "paper_verified": bool(candidate.get("paper_verified")),
                    "paper_confidence": round(float(candidate.get("paper_confidence", 0.0)), 3),
                    "doi": _clean_text(candidate.get("doi")),
                    "pdf_url": _clean_text(candidate.get("pdf_url")),
                    "paper_signals": _coerce_string_list(candidate.get("paper_signals")),
                    "summary_signals": _coerce_string_list(candidate.get("summary_signals")),
                    "snippet": _candidate_snippet(candidate),
                }
                for index, candidate in enumerate(candidates)
            ],
        },
        "output_schema": {
            "selected_indices": [1, 2, 3],
            "notes": "string",
            "source_assessments": [
                {
                    "source_id": "string",
                    "index": 1,
                    "usefulness_score": "number",
                    "credibility_score": "number",
                    "quote_strength_score": "number",
                    "topical_fit_score": "number",
                    "paper_confidence": "number",
                    "reason": "string",
                    "risk": "string",
                    "best_quote_hint": "string",
                }
            ],
        },
    }


def _parse_selected_candidate_indices(parsed: dict[str, Any], total_candidates: int) -> list[int]:
    selection = parsed.get("selection") if isinstance(parsed.get("selection"), dict) else {}
    zero_based = False
    raw_indices = parsed.get("selected_indices") or parsed.get("ranked_indices") or parsed.get("candidate_indices") or selection.get("selected_indices") or []
    if not raw_indices:
        raw_indices = selection.get("ordered_indices") or selection.get("ranked_indices") or []
        zero_based = bool(raw_indices)
    if not isinstance(raw_indices, list):
        raw_indices = [
            parsed.get("selected_index")
            if parsed.get("selected_index") is not None
            else selection.get("best_index")
        ]
        zero_based = parsed.get("selected_index") is None and selection.get("best_index") is not None

    indices: list[int] = []
    for raw in raw_indices:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if zero_based and 0 <= value < total_candidates:
            value += 1
        if 1 <= value <= total_candidates and value not in indices:
            indices.append(value)
    return indices


def _call_chat_completion_json(
    *,
    url: str,
    model: str,
    prompt: dict[str, Any],
    api_key: str = "",
    timeout: int = 60,
) -> dict[str, Any]:
    data = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return strict JSON only.",
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt, ensure_ascii=True),
                },
            ],
            "temperature": 0.2,
            "max_tokens": min(MODEL_OUTPUT_TOKENS, 2500),
        }
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with _open_http_request(req, timeout=timeout) as resp:
        response_json = json.loads(resp.read().decode("utf-8"))

    choices = response_json.get("choices") if isinstance(response_json, dict) else None
    if not isinstance(choices, list) or not choices:
        raise ValueError("Chat completion response missing choices")
    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
    text = _text_from_value(message.get("content") or first_choice.get("text"))
    return _parse_json_text(text)


def _call_openai_json_prompt(prompt: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    data = json.dumps(
        {
            "model": os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
            "input": json.dumps(prompt, ensure_ascii=True),
            "temperature": 0.2,
            "max_output_tokens": min(MODEL_OUTPUT_TOKENS, 2500),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with _open_http_request(req, timeout=60) as resp:
        response_json = json.loads(resp.read().decode("utf-8"))
    return _parse_json_text(_extract_text_from_response(response_json))


def _extract_bedrock_text(response_json: dict[str, Any]) -> str:
    output = response_json.get("output") if isinstance(response_json.get("output"), dict) else {}
    message = output.get("message") if isinstance(output.get("message"), dict) else {}
    content = message.get("content")
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                text = _clean_text(block.get("text"))
                if text:
                    parts.append(text)
    return "\n".join(parts).strip()


def _call_bedrock_converse_request(*, system_text: str, user_text: str, timeout: int) -> dict[str, Any]:
    url = _resolve_bedrock_url()
    model = _resolve_bedrock_model_id()
    api_key = _bedrock_api_key()
    if not url or not model:
        raise RuntimeError("BEDROCK_REGION or BEDROCK_BASE_URL and BEDROCK_MODEL or BEDROCK_INFERENCE_PROFILE must be set")
    if not api_key:
        raise RuntimeError("BEDROCK_API_KEY or AWS_BEARER_TOKEN_BEDROCK must be set")

    request_body = {
        "messages": [
            {
                "role": "user",
                "content": [{"text": user_text}],
            }
        ],
        "system": [{"text": system_text}],
        "inferenceConfig": {
            "temperature": 0.2,
            "maxTokens": MODEL_OUTPUT_TOKENS,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(request_body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with _open_http_request(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        lower_body = error_body.lower()
        if exc.code == 429 or "too many tokens per day" in lower_body or "throttl" in lower_body or "quota" in lower_body:
            raise ProviderQuotaError(f"Bedrock quota limit reached: {error_body}") from exc
        if "inference profile" in error_body.lower():
            raise ProviderAccessError(
                "Bedrock rejected the model ID for on-demand invocation. "
                "Use BEDROCK_INFERENCE_PROFILE or set BEDROCK_MODEL to an inference profile such as "
                "'us.meta.llama4-scout-17b-instruct-v1:0'."
            ) from exc
        raise ProviderAccessError(f"Bedrock request failed ({exc.code}): {error_body}") from exc


def _call_bedrock_json_prompt(prompt: dict[str, Any]) -> dict[str, Any]:
    response_json = _call_bedrock_converse_request(
        system_text="Return strict JSON only.",
        user_text=json.dumps(prompt, ensure_ascii=True),
        timeout=BEDROCK_TIMEOUT,
    )
    text = _extract_bedrock_text(response_json)
    return _parse_json_text(text)


def _call_ollama_json_prompt(prompt: dict[str, Any]) -> dict[str, Any]:
    model = OLLAMA_MODEL or os.getenv("LOCAL_MODEL", "").strip() or "llama3.1"
    data = json.dumps(
        {
            "model": model,
            "stream": False,
            "format": "json",
            "messages": [
                {
                    "role": "system",
                    "content": "Return strict JSON only.",
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt, ensure_ascii=True),
                },
            ],
            "options": {
                "temperature": 0.2,
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with _open_http_request(req, timeout=OLLAMA_TIMEOUT) as resp:
        response_json = json.loads(resp.read().decode("utf-8"))
    message = response_json.get("message") if isinstance(response_json, dict) else None
    text = _text_from_value(message.get("content") if isinstance(message, dict) else response_json.get("response"))
    return _parse_json_text(text)


def _call_provider_json(provider: str, prompt: dict[str, Any]) -> dict[str, Any]:
    if provider == "bedrock":
        return _call_bedrock_json_prompt(prompt)
    if provider == "ollama":
        return _call_ollama_json_prompt(prompt)
    if provider == "chatgpt_bridge":
        return _call_chat_completion_json(
            url=_resolve_chatgpt_bridge_url(),
            model=CHATGPT_BRIDGE_MODEL,
            prompt=prompt,
            api_key=CHATGPT_BRIDGE_API_KEY,
            timeout=CHATGPT_BRIDGE_TIMEOUT,
        )
    if provider == "openai_compat":
        return _call_chat_completion_json(
            url=_resolve_openai_compat_url(),
            model=OPENAI_COMPAT_MODEL,
            prompt=prompt,
            api_key=OPENAI_COMPAT_API_KEY,
            timeout=60,
        )
    if provider == "openai":
        return _call_openai_json_prompt(prompt)
    raise RuntimeError("Unsupported provider for JSON prompt")


def _select_source_order_with_ai(provider: str, payload: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not candidates:
        return [], {"used_ai_selection": False}

    prompt = _build_source_selection_prompt(payload, candidates)
    parsed = _call_provider_json(provider, prompt)
    selected_indices = _parse_selected_candidate_indices(parsed, len(candidates))
    ordered: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for index in selected_indices:
        candidate = candidates[index - 1]
        url = _clean_text(candidate.get("url"))
        if url and url not in seen_urls:
            ordered.append(candidate)
            seen_urls.add(url)

    for candidate in candidates:
        url = _clean_text(candidate.get("url"))
        if url and url in seen_urls:
            continue
        ordered.append(candidate)
        if url:
            seen_urls.add(url)

    return ordered, {
        "used_ai_selection": True,
        "selection_notes": _clean_text(parsed.get("notes") or parsed.get("reasoning")),
        "selected_indices": selected_indices,
        "source_assessments": parsed.get("source_assessments") if isinstance(parsed.get("source_assessments"), list) else [],
    }


def _default_validation_meta(
    *,
    notes: str,
    revised: bool,
    useful: bool = True,
    passed: bool | None = None,
    issues: list[str] | None = None,
    source_checks: list[str] | None = None,
) -> dict[str, Any]:
    meta = {
        "useful": useful,
        "revised": revised,
        "notes": _clean_text(notes),
    }
    if passed is not None:
        meta["passed"] = passed
    normalized_issues = [issue for issue in (issues or []) if _clean_text(issue)]
    if normalized_issues:
        meta["issues"] = normalized_issues
    normalized_source_checks = [check for check in (source_checks or []) if _clean_text(check)]
    if normalized_source_checks:
        meta["source_checks"] = normalized_source_checks
    return meta


def _call_provider_stage(
    provider: str,
    payload: dict[str, Any],
    *,
    stage: str = "cut",
    candidate_card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if provider == "bedrock":
        return _call_bedrock(payload, stage=stage, candidate_card=candidate_card)
    if provider == "ollama":
        return _call_ollama(payload, stage=stage, candidate_card=candidate_card)
    if provider == "chatgpt_bridge":
        return _call_chatgpt_bridge(payload, stage=stage, candidate_card=candidate_card)
    if provider == "openai_compat":
        return _call_openai_compat(payload, stage=stage, candidate_card=candidate_card)
    if provider == "openai":
        return _call_openai(payload, stage=stage, candidate_card=candidate_card)
    raise RuntimeError("Fallback provider selected")


def _call_chat_completion_provider(
    *,
    provider: str,
    url: str,
    model: str,
    payload: dict[str, Any],
    api_key: str = "",
    timeout: int = 60,
    stage: str = "cut",
    candidate_card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt = _build_prompt(payload, stage=stage, candidate_card=candidate_card)
    request_body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You cut and validate debate cards. Return strict JSON only, matching the schema provided by the user."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=True),
            },
        ],
        "temperature": 0.2,
        "max_tokens": MODEL_OUTPUT_TOKENS,
    }
    data = json.dumps(request_body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers=headers,
    )

    with _open_http_request(req, timeout=timeout) as resp:
        response_json = json.loads(resp.read().decode("utf-8"))

    choices = response_json.get("choices") if isinstance(response_json, dict) else None
    if not isinstance(choices, list) or not choices:
        raise ValueError("Chat completion response missing choices")
    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
    text = _text_from_value(message.get("content") or first_choice.get("text"))
    parsed = _parse_json_text(text)
    normalized_cards = _normalize_model_cards(parsed.get("cards"), 1)
    return {
        "cards": normalized_cards,
        "validation": _extract_validation_meta(parsed),
        "meta": {
            "used_ai": True,
            "mode": "ai",
            "provider": provider,
            "model": model,
            "stage": stage,
            "experimental": provider == "chatgpt_bridge",
        },
    }


def _call_openai(payload: dict[str, Any], *, stage: str = "cut", candidate_card: dict[str, Any] | None = None) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    prompt = _build_prompt(payload, stage=stage, candidate_card=candidate_card)
    request_body = {
        "model": os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        "input": json.dumps(prompt, ensure_ascii=True),
        "temperature": 0.2,
        "max_output_tokens": MODEL_OUTPUT_TOKENS,
    }
    data = json.dumps(request_body).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    with _open_http_request(req, timeout=60) as resp:
        response_json = json.loads(resp.read().decode("utf-8"))

    text = _extract_text_from_response(response_json)
    parsed = _parse_json_text(text)
    normalized_cards = _normalize_model_cards(parsed.get("cards"), 1)
    return {
        "cards": normalized_cards,
        "validation": _extract_validation_meta(parsed),
        "meta": {
            "used_ai": True,
            "mode": "ai",
            "provider": "openai",
            "model": request_body["model"],
            "stage": stage,
        },
    }


def _call_ollama(payload: dict[str, Any], *, stage: str = "cut", candidate_card: dict[str, Any] | None = None) -> dict[str, Any]:
    model = OLLAMA_MODEL or os.getenv("LOCAL_MODEL", "").strip() or "llama3.1"
    prompt = _build_prompt(payload, stage=stage, candidate_card=candidate_card)
    request_body = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You cut debate cards. Return strict JSON only, matching the schema provided by the user."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=True),
            },
        ],
        "options": {
            "temperature": 0.2,
            "num_predict": MODEL_OUTPUT_TOKENS,
        },
    }
    data = json.dumps(request_body).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    with _open_http_request(req, timeout=OLLAMA_TIMEOUT) as resp:
        response_json = json.loads(resp.read().decode("utf-8"))

    text = ""
    message = response_json.get("message") if isinstance(response_json, dict) else None
    if isinstance(message, dict):
        text = _text_from_value(message.get("content"))
    if not text and isinstance(response_json, dict):
        text = _text_from_value(response_json.get("response"))

    parsed = _parse_json_text(text)
    normalized_cards = _normalize_model_cards(parsed.get("cards"), 1)
    return {
        "cards": normalized_cards,
        "validation": _extract_validation_meta(parsed),
        "meta": {
            "used_ai": True,
            "mode": "ai",
            "provider": "ollama",
            "model": model,
            "stage": stage,
        },
    }


def _call_bedrock(payload: dict[str, Any], *, stage: str = "cut", candidate_card: dict[str, Any] | None = None) -> dict[str, Any]:
    prompt = _build_prompt(payload, stage=stage, candidate_card=candidate_card)
    resolved_model = _resolve_bedrock_model_id()
    response_json = _call_bedrock_converse_request(
        system_text="You cut and validate debate cards. Return strict JSON only, matching the schema provided by the user.",
        user_text=json.dumps(prompt, ensure_ascii=True),
        timeout=BEDROCK_TIMEOUT,
    )
    text = _extract_bedrock_text(response_json)
    parsed = _parse_json_text(text)
    normalized_cards = _normalize_model_cards(parsed.get("cards"), 1)
    return {
        "cards": normalized_cards,
        "validation": _extract_validation_meta(parsed),
        "meta": {
            "used_ai": True,
            "mode": "ai",
            "provider": "bedrock",
            "model": resolved_model,
            "stage": stage,
        },
    }


def _call_openai_compat(payload: dict[str, Any], *, stage: str = "cut", candidate_card: dict[str, Any] | None = None) -> dict[str, Any]:
    url = _resolve_openai_compat_url()
    model = OPENAI_COMPAT_MODEL
    if not url or not model:
        raise RuntimeError("OPENAI_COMPAT_BASE_URL and OPENAI_COMPAT_MODEL must be set")

    return _call_chat_completion_provider(
        provider="openai_compat",
        url=url,
        model=model,
        payload=payload,
        api_key=OPENAI_COMPAT_API_KEY,
        timeout=60,
        stage=stage,
        candidate_card=candidate_card,
    )


def _call_chatgpt_bridge(
    payload: dict[str, Any],
    *,
    stage: str = "cut",
    candidate_card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = _resolve_chatgpt_bridge_url()
    model = CHATGPT_BRIDGE_MODEL
    if not url or not model:
        raise RuntimeError("CHATGPT_BRIDGE_BASE_URL and CHATGPT_BRIDGE_MODEL must be set")

    return _call_chat_completion_provider(
        provider="chatgpt_bridge",
        url=url,
        model=model,
        payload=payload,
        api_key=CHATGPT_BRIDGE_API_KEY,
        timeout=CHATGPT_BRIDGE_TIMEOUT,
        stage=stage,
        candidate_card=candidate_card,
    )


def _cut_cards(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = _request_id(payload)
    research_error = ""
    supplied_research = payload.get("research_meta") if isinstance(payload.get("research_meta"), dict) else {}
    if supplied_research:
        research_meta = dict(supplied_research)
        research_error = _clean_text(research_meta.get("error"))
    else:
        try:
            research_meta = _research_sources(payload)
        except Exception as exc:
            research_error = str(exc)
            query_pack, search_mode, query_refinement_used, query_refinement_provider = _refine_query_pack(payload)
            research_meta = {
                "used": False,
                "query": _clean_text(query_pack.get("literal_query")) or _research_query(payload),
                "search_mode": search_mode,
                "query_pack": query_pack,
                "query_refinement_used": query_refinement_used,
                "query_refinement_provider": query_refinement_provider,
                "executed_queries": [],
                "sources": [],
                "selected": {},
                "article_text": _clean_text(payload.get("article_text") or payload.get("draft_tag") or payload.get("resolution")),
                "error": research_error,
                "_candidates": [],
                "candidates": [],
            }

    candidate_pool = list(research_meta.pop("_candidates", []) or research_meta.get("candidates") or [])
    public_research_meta = dict(research_meta)
    payload = dict(payload)
    if not isinstance(payload.get("query_pack"), dict) or not payload.get("query_pack"):
        payload["query_pack"] = research_meta.get("query_pack") if isinstance(research_meta.get("query_pack"), dict) else {}
    if payload.get("semantic_search_enabled") is None:
        payload["semantic_search_enabled"] = _clean_text(research_meta.get("search_mode")).lower() != "literal"
    payload["article_text"] = _clean_text(research_meta.get("article_text") or payload.get("article_text"))
    selected_source = research_meta.get("selected") if isinstance(research_meta.get("selected"), dict) else {}
    if selected_source:
        payload["source_title"] = payload.get("source_title") or selected_source.get("title", "")
        payload["source_author"] = payload.get("source_author") or selected_source.get("author", "")
        payload["source_date"] = payload.get("source_date") or selected_source.get("date", "")
        payload["source_publication"] = payload.get("source_publication") or selected_source.get("publication", "")
        payload["source_url"] = payload.get("source_url") or selected_source.get("url", "")

    base_meta = {
        "resolution": _clean_text(payload.get("resolution")),
        "side": _normalize_side(_clean_text(payload.get("side"))),
        "source_title": _clean_text(payload.get("source_title")),
        "source_author": _clean_text(payload.get("source_author")),
        "source_date": _clean_text(payload.get("source_date")),
        "source_publication": _clean_text(payload.get("source_publication")),
        "source_url": _clean_text(payload.get("source_url")),
        "desired_cards": _normalize_desired_cards(payload.get("desired_cards")),
        "emphasis": _clean_text(payload.get("emphasis")),
        "draft_tag": _clean_text(payload.get("draft_tag")),
        "domain_blacklist": _parse_domain_blacklist(payload.get("domain_blacklist")),
    }
    if research_error:
        base_meta["research_error"] = research_error

    errors: list[str] = []
    provider_chain = _provider_preference(payload)
    strict_provider_mode = _strict_provider_mode(payload)
    for provider in provider_chain:
        if provider == "fallback":
            break
        try:
            _log_event(logging.INFO, "cut_provider_start", request_id=request_id, provider=provider, candidate_pool=len(candidate_pool))
            ordered_candidates = candidate_pool
            selection_meta = {
                "used_ai_selection": False,
                "selected_indices": [],
                "selection_notes": "",
            }
            selection_errors: list[str] = []
            if ordered_candidates:
                try:
                    ordered_candidates, selection_meta = _select_source_order_with_ai(provider, payload, ordered_candidates[:SEARCH_RESULTS])
                    _log_event(
                        logging.INFO,
                        "cut_source_selection",
                        request_id=request_id,
                        provider=provider,
                        selected_indices=selection_meta.get("selected_indices"),
                        used_ai_selection=selection_meta.get("used_ai_selection"),
                    )
                except ProviderAccessError:
                    raise
                except Exception as selection_exc:
                    selection_errors.append(f"{provider} source_select: {selection_exc}")
                    _log_event(logging.WARNING, "cut_source_selection_failed", request_id=request_id, provider=provider, error=str(selection_exc))

            attempts = ordered_candidates[: max(1, min(SOURCE_RETRY_LIMIT, len(ordered_candidates)))] if ordered_candidates else []
            if not attempts:
                attempts = [
                    {
                        "title": payload.get("source_title") or selected_source.get("title", ""),
                        "author": payload.get("source_author") or selected_source.get("author", ""),
                        "published": payload.get("source_date") or selected_source.get("date", ""),
                        "publication": payload.get("source_publication") or selected_source.get("publication", ""),
                        "url": payload.get("source_url") or selected_source.get("url", ""),
                        "text": payload.get("article_text") or research_meta.get("article_text", ""),
                    }
                ]

            attempt_errors: list[str] = []
            for attempt_index, candidate in enumerate(attempts, start=1):
                attempt_payload = dict(payload)
                attempt_text = _clean_text(candidate.get("text")) or _clean_text(candidate.get("description")) or attempt_payload.get("article_text", "")
                attempt_payload["article_text"] = attempt_text
                attempt_payload["source_title"] = _clean_text(candidate.get("title")) or attempt_payload.get("source_title", "")
                attempt_payload["source_author"] = _clean_text(candidate.get("author")) or attempt_payload.get("source_author", "")
                attempt_payload["source_date"] = _clean_text(candidate.get("published")) or attempt_payload.get("source_date", "")
                attempt_payload["source_publication"] = _clean_text(candidate.get("publication")) or attempt_payload.get("source_publication", "")
                attempt_payload["source_url"] = _clean_text(candidate.get("url")) or attempt_payload.get("source_url", "")
                attempt_payload["source_id"] = _clean_text(candidate.get("source_id") or f"S{attempt_index}")
                attempt_payload["credibility_score"] = float(candidate.get("credibility_score", 0.0)) if isinstance(candidate.get("credibility_score"), (int, float)) else 0.0
                attempt_payload["credibility_notes"] = _clean_text(candidate.get("credibility_notes"))
                attempt_payload["candidate_sources"] = ordered_candidates[: min(MIXED_SOURCE_POOL_SIZE, len(ordered_candidates))]
                attempt_payload["source_selection"] = {
                    **selection_meta,
                    "current_attempt_index": attempt_index,
                    "current_source_id": _clean_text(candidate.get("source_id") or f"S{attempt_index}"),
                }
                _log_event(
                    logging.INFO,
                    "cut_attempt_start",
                    request_id=request_id,
                    provider=provider,
                    attempt_index=attempt_index,
                    source_id=attempt_payload["source_id"],
                    source_title=attempt_payload["source_title"],
                    source_url=attempt_payload["source_url"],
                )

                cut_result = _call_provider_stage(provider, attempt_payload, stage="cut")
                final_card = cut_result["cards"][0]
                validation_completed = False
                validation_errors: list[str] = []
                validation_meta = _default_validation_meta(
                    notes="Awaiting separate validation call.",
                    revised=False,
                    useful=True,
                    passed=True,
                )

                try:
                    validation_result = _call_provider_stage(
                        provider,
                        attempt_payload,
                        stage="validate",
                        candidate_card=final_card,
                    )
                    final_card = validation_result["cards"][0]
                    validation_completed = True
                    validation_meta = validation_result.get("validation") or _extract_validation_meta(validation_result)
                    revised = final_card.get("formatted_card") != cut_result["cards"][0].get("formatted_card")
                    if not validation_meta:
                        validation_meta = _default_validation_meta(
                            notes="Validation pass completed without explicit notes.",
                            revised=revised,
                            useful=True,
                            passed=True,
                        )
                    else:
                        validation_meta.setdefault("revised", revised)
                        validation_meta.setdefault("useful", True)
                        validation_meta.setdefault("passed", True)
                except ProviderAccessError:
                    raise
                except Exception as validation_exc:
                    validation_errors.append(f"{provider} validate: {validation_exc}")
                    _log_event(logging.WARNING, "cut_validation_failed", request_id=request_id, provider=provider, attempt_index=attempt_index, error=str(validation_exc))
                    validation_meta = _default_validation_meta(
                        notes=f"Validation pass failed: {validation_exc}",
                        revised=False,
                        useful=False,
                        passed=False,
                        issues=["Returning the initial cut because the validation pass failed."],
                    )

                grounding_meta = _build_source_grounding_validation(final_card, attempt_payload.get("article_text", ""))
                validation_meta = _merge_validation_meta(validation_meta, grounding_meta)
                final_card["validation"] = validation_meta
                if _validation_is_weak(validation_meta):
                    note = _clean_text(validation_meta.get("notes")) or "Validation marked the card as not useful."
                    attempt_errors.append(f"{provider} source_attempt_{attempt_index}: {note}")
                    _log_event(logging.INFO, "cut_attempt_rejected", request_id=request_id, provider=provider, attempt_index=attempt_index, reason=note)
                    continue

                result = {
                    "cards": [final_card],
                    "meta": {
                        **cut_result.get("meta", {}),
                        **base_meta,
                        "fallback_used": False,
                        "card_count": 1,
                        "provider": provider,
                        "research": {
                            **public_research_meta,
                            "selected": {
                                "engine": candidate.get("engine", ""),
                                "title": _clean_text(candidate.get("title")) or attempt_payload.get("source_title", ""),
                                "publication": _clean_text(candidate.get("publication")) or attempt_payload.get("source_publication", ""),
                                "author": _clean_text(candidate.get("author")) or attempt_payload.get("source_author", ""),
                                "date": _clean_text(candidate.get("published")) or attempt_payload.get("source_date", ""),
                                "url": _clean_text(candidate.get("url")) or attempt_payload.get("source_url", ""),
                                "source_id": _clean_text(candidate.get("source_id") or f"S{attempt_index}"),
                                "credibility_score": round(float(candidate.get("credibility_score", 0.0)), 3),
                                "credibility_notes": _clean_text(candidate.get("credibility_notes")),
                                "text": _truncate(attempt_text, 4000),
                            },
                            "source_selection": selection_meta,
                        },
                        "validation_ran": True,
                        "validation_completed": validation_completed,
                        "validation_separate_call": True,
                        "validation_provider": provider,
                        "validation": validation_meta,
                        "source_attempts": attempt_index,
                    },
                }
                provider_errors = [*errors, *selection_errors, *attempt_errors, *validation_errors]
                if provider_errors:
                    result["meta"]["provider_errors"] = provider_errors
                _log_event(logging.INFO, "cut_complete", request_id=request_id, provider=provider, attempt_index=attempt_index, source_id=_clean_text(candidate.get("source_id") or f"S{attempt_index}"))
                return {"ok": True, **result}

            errors.extend([*selection_errors, *attempt_errors])
        except ProviderQuotaError as exc:
            errors.append(f"{provider}: {exc}")
            _log_event(logging.WARNING, "cut_provider_quota_failed", request_id=request_id, provider=provider, error=str(exc))
            if strict_provider_mode:
                raise
            continue
        except ProviderAccessError as exc:
            errors.append(f"{provider}: {exc}")
            _log_event(logging.WARNING, "cut_provider_access_failed", request_id=request_id, provider=provider, error=str(exc))
            if strict_provider_mode:
                raise
            continue
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            _log_event(logging.WARNING, "cut_provider_failed", request_id=request_id, provider=provider, error=str(exc))
            continue

    if strict_provider_mode and errors:
        raise ProviderAccessError("; ".join(errors))

    cards = _build_fallback_cards(payload)
    fallback_validation = _default_validation_meta(
        notes="Fallback cutter used a heuristic validation pass.",
        revised=False,
        useful=True,
        passed=True,
    )
    for card in cards:
        card["validation"] = fallback_validation
    return {
        "ok": True,
        "cards": cards,
        "meta": {
            **base_meta,
            "used_ai": False,
            "mode": "fallback",
            "provider": "fallback",
            "fallback_used": True,
            "fallback_reason": "; ".join(errors) if errors else "No provider configured",
            "provider_errors": errors,
            "card_count": len(cards),
            "research": public_research_meta,
            "validation_ran": True,
            "validation_completed": True,
            "validation_provider": "fallback",
            "validation": fallback_validation,
        },
    }


def _parse_queue_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[\r\n]+", _clean_text(value))

    tags: list[str] = []
    for raw in raw_items:
        tag = _clean_text(raw)
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= MAX_QUEUE_TAGS:
            break
    return tags


def _queue_cut_cards(payload: dict[str, Any]) -> dict[str, Any]:
    tags = _parse_queue_tags(payload.get("draft_tags") or payload.get("queue_tags") or payload.get("tags"))
    if not tags:
        raise ValueError("draft_tags is required for queue cuts")

    results: list[dict[str, Any]] = []
    saved_cards: list[dict[str, Any]] = []
    for index, tag in enumerate(tags, start=1):
        item_payload = dict(payload)
        item_payload["draft_tag"] = tag
        item_payload["prior_cards"] = list(saved_cards)
        try:
            result = _cut_cards(item_payload)
            cards = result.get("cards") if isinstance(result.get("cards"), list) else []
            if cards:
                saved_cards.extend(card for card in cards if isinstance(card, dict))
            result["queue_index"] = index
            result["draft_tag"] = tag
            results.append(result)
        except Exception as exc:
            results.append(
                {
                    "ok": False,
                    "queue_index": index,
                    "draft_tag": tag,
                    "error": str(exc),
                    "cards": [],
                }
            )

    return {
        "ok": True,
        "results": results,
        "cards": [item["cards"][0] for item in results if item.get("ok") and item.get("cards")],
        "meta": {
            "queue_count": len(tags),
            "completed_count": sum(1 for item in results if item.get("ok") and item.get("cards")),
            "failed_count": sum(1 for item in results if not item.get("ok")),
        },
    }


def _xml_text(text: str) -> str:
    return escape(text, {'"': "&quot;"})


def _slugify_filename(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", _clean_text(text)).strip("-._")
    return slug or "debate-cards"


def _w_run(
    text: str,
    *,
    bold: bool = False,
    underline: bool = False,
    highlight: str = "",
    color: str = "",
) -> str:
    cleaned = text or ""
    if not cleaned:
        return ""
    props = ['<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>']
    if bold:
        props.append("<w:b/>")
    if underline:
        props.append('<w:u w:val="single"/>')
    if highlight:
        props.append(f'<w:highlight w:val="{_xml_text(highlight)}"/>')
    if color:
        props.append(f'<w:color w:val="{_xml_text(color)}"/>')
    prop_xml = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    return f'<w:r>{prop_xml}<w:t xml:space="preserve">{_xml_text(cleaned)}</w:t></w:r>'


def _w_paragraph(
    runs: list[str],
    *,
    style: str = "",
    spacing_before: int = 0,
    spacing_after: int = 120,
    keep_next: bool = False,
) -> str:
    paragraph_props: list[str] = []
    if style:
        paragraph_props.append(f'<w:pStyle w:val="{_xml_text(style)}"/>')
    paragraph_props.append(f'<w:spacing w:before="{spacing_before}" w:after="{spacing_after}" w:line="276" w:lineRule="auto"/>')
    if keep_next:
        paragraph_props.append("<w:keepNext/>")
    prop_xml = f"<w:pPr>{''.join(paragraph_props)}</w:pPr>" if paragraph_props else ""
    body_xml = "".join(run for run in runs if run) or _w_run("")
    return f"<w:p>{prop_xml}{body_xml}</w:p>"


def _build_runs_from_spans(full_context: str, underlined_spans: list[dict[str, Any]], highlighted_spans: list[dict[str, Any]]) -> tuple[list[str], bool]:
    full_context = _clean_text(full_context)
    if not full_context:
        fallback_text = _span_text(highlighted_spans) or _span_text(underlined_spans)
        if not fallback_text:
            return [], False
        return [_w_run(fallback_text, bold=bool(highlighted_spans), underline=True, highlight="cyan" if highlighted_spans else "")], False

    underline_marks = [False] * len(full_context)
    highlight_marks = [False] * len(full_context)
    found_any = False

    for span in underlined_spans:
        start = span.get("start")
        end = span.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(full_context):
            found_any = True
            for index in range(start, end):
                underline_marks[index] = True

    for span in highlighted_spans:
        start = span.get("start")
        end = span.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(full_context):
            found_any = True
            for index in range(start, end):
                underline_marks[index] = True
                highlight_marks[index] = True

    if not found_any:
        fallback_text = _span_text(highlighted_spans) or _span_text(underlined_spans)
        return [_w_run(full_context)], bool(fallback_text and fallback_text != full_context)

    runs: list[str] = []
    chunk: list[str] = []
    current_state: tuple[bool, bool] | None = None

    for index, char in enumerate(full_context):
        state = (underline_marks[index], highlight_marks[index])
        if current_state is None:
            current_state = state
        if state != current_state:
            runs.append(
                _w_run(
                    "".join(chunk),
                    underline=current_state[0],
                    highlight="cyan" if current_state[1] else "",
                    bold=current_state[1],
                )
            )
            chunk = [char]
            current_state = state
        else:
            chunk.append(char)

    if chunk and current_state is not None:
        runs.append(
            _w_run(
                "".join(chunk),
                underline=current_state[0],
                highlight="cyan" if current_state[1] else "",
                bold=current_state[1],
            )
        )
    return runs, False


def _build_docx_card_blocks(card: dict[str, Any]) -> list[str]:
    tag_line = _clean_text(card.get("tag_line") or card.get("title"))
    cite_line = _clean_text(card.get("cite_line") or _build_cite_line(_clean_text(card.get("short_citation")), _clean_text(card.get("full_citation") or card.get("citation"))))
    full_context = _clean_text(card.get("full_context") or card.get("body"))
    underlined_spans = _normalize_span_list(card.get("underlined_spans") or card.get("underlinedSpans"), full_context)
    highlighted_spans = _normalize_span_list(card.get("highlighted_spans") or card.get("highlightedSpans"), full_context)

    blocks: list[str] = []
    if tag_line:
        blocks.append(_w_paragraph([_w_run(tag_line)], style="Heading4", spacing_before=240, spacing_after=40, keep_next=True))
    if cite_line:
        blocks.append(_w_paragraph([_w_run(cite_line)], spacing_after=40, keep_next=True))

    evidence_runs, needs_read_paragraph = _build_runs_from_spans(full_context, underlined_spans, highlighted_spans)
    if evidence_runs:
        blocks.append(_w_paragraph(evidence_runs, spacing_after=80))
    if needs_read_paragraph:
        blocks.append(
            _w_paragraph(
                [_w_run("[Highlighted read] ", bold=True), _w_run(_span_text(highlighted_spans) or _span_text(underlined_spans), bold=True, underline=True, highlight="cyan")],
                spacing_after=120,
            )
        )
    blocks.append(_w_paragraph([], spacing_after=140))
    return blocks


def _build_docx_bytes(cards: list[dict[str, Any]], title: str) -> bytes:
    document_body = "".join(
        block
        for card in cards
        if isinstance(card, dict)
        for block in _build_docx_card_blocks(card)
    )
    if not document_body:
        raise ValueError("At least one card is required to export a .docx file")

    document_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:w10="urn:schemas-microsoft-com:office:word" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml" mc:Ignorable="w14 w15">
  <w:body>
    {document_body}
    <w:sectPr>
      <w:pgSz w:w="12240" w:h="15840"/>
      <w:pgMar w:top="900" w:right="900" w:bottom="900" w:left="900" w:header="720" w:footer="720" w:gutter="0"/>
      <w:cols w:space="720"/>
      <w:docGrid w:linePitch="360"/>
    </w:sectPr>
  </w:body>
</w:document>'''

    styles_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault>
      <w:rPr>
        <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>
        <w:sz w:val="22"/>
        <w:szCs w:val="22"/>
      </w:rPr>
    </w:rPrDefault>
    <w:pPrDefault>
      <w:pPr>
        <w:spacing w:after="120" w:line="276" w:lineRule="auto"/>
      </w:pPr>
    </w:pPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/>
    <w:qFormat/>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading4">
    <w:name w:val="heading 4"/>
    <w:basedOn w:val="Normal"/>
    <w:next w:val="Normal"/>
    <w:qFormat/>
    <w:pPr>
      <w:spacing w:before="240" w:after="40"/>
    </w:pPr>
    <w:rPr>
      <w:b/>
      <w:sz w:val="22"/>
      <w:szCs w:val="22"/>
      <w:color w:val="111111"/>
    </w:rPr>
  </w:style>
</w:styles>'''

    content_types_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>'''

    package_rels_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''

    document_rels_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''

    core_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{_xml_text(title)}</dc:title>
  <dc:creator>AI Debate Card Cutter</dc:creator>
  <cp:lastModifiedBy>AI Debate Card Cutter</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{date.today().isoformat()}T00:00:00Z</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{date.today().isoformat()}T00:00:00Z</dcterms:modified>
</cp:coreProperties>'''

    app_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>AI Debate Card Cutter</Application>
</Properties>'''

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types_xml)
        docx.writestr("_rels/.rels", package_rels_xml)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/_rels/document.xml.rels", document_rels_xml)
        docx.writestr("word/styles.xml", styles_xml)
        docx.writestr("docProps/core.xml", core_xml)
        docx.writestr("docProps/app.xml", app_xml)
    return buffer.getvalue()


def _export_docx(payload: dict[str, Any]) -> tuple[bytes, str]:
    cards = [card for card in to_array(payload.get("cards")) if isinstance(card, dict)]
    if not cards:
        raise ValueError("cards is required for .docx export")
    normalized_cards = _normalize_model_cards(cards, len(cards))
    title = _clean_text(payload.get("title") or payload.get("draft_tag") or normalized_cards[0].get("tag_line") or "debate-cards")
    filename = f"{_slugify_filename(title)}.verbatim.docx"
    return _build_docx_bytes(normalized_cards, title), filename


class DebateCardHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("directory", str(ROOT))
        super().__init__(*args, **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        if self.path in {"/", ""}:
            index = ROOT / "index.html"
            if index.exists():
                self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:
        request_id = uuid4().hex[:10]
        try:
            payload = _normalize_payload(_read_json_body(self))
            payload["_request_id"] = request_id
            _log_event(
                logging.INFO,
                "request_start",
                request_id=request_id,
                path=self.path,
                draft_tag=_clean_text(payload.get("draft_tag")),
                has_article_text=bool(_clean_text(payload.get("article_text"))),
                source_url=_clean_text(payload.get("source_url")),
                semantic_search_enabled=_parse_bool(payload.get("semantic_search_enabled"), SEMANTIC_SEARCH_DEFAULT),
            )
            if self.path == "/api/research":
                research = dict(_research_sources(payload))
                research.pop("_candidates", None)
                _log_event(
                    logging.INFO,
                    "request_success",
                    request_id=request_id,
                    path=self.path,
                    selected_title=_clean_text((research.get("selected") or {}).get("title")) if isinstance(research.get("selected"), dict) else "",
                    source_count=len(to_array(research.get("sources"))),
                )
                _json_response(self, HTTPStatus.OK, {"ok": True, "request_id": request_id, "research": research})
                return
            if self.path == "/api/queue":
                result = _queue_cut_cards(payload)
                _log_event(logging.INFO, "request_success", request_id=request_id, path=self.path)
                _json_response(self, HTTPStatus.OK, {"request_id": request_id, **result})
                return
            if self.path == "/api/export/docx":
                body, filename = _export_docx(payload)
                _log_event(logging.INFO, "request_success", request_id=request_id, path=self.path, filename=filename)
                _binary_response(
                    self,
                    HTTPStatus.OK,
                    body,
                    content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    filename=filename,
                )
                return
            if self.path != "/api/cut":
                _json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"})
                return
            if not _clean_text(payload.get("article_text")) and not _clean_text(payload.get("draft_tag")) and not _clean_text(payload.get("source_url")):
                raise ValueError("article_text, draft_tag, or source_url is required")
            result = _cut_cards(payload)
            _log_event(logging.INFO, "request_success", request_id=request_id, path=self.path, card_count=len(to_array(result.get("cards"))))
            _json_response(self, HTTPStatus.OK, {"request_id": request_id, **result})
        except json.JSONDecodeError:
            _log_event(logging.WARNING, "request_error", request_id=request_id, path=self.path, error="Invalid JSON")
            _json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "request_id": request_id, "error": "Invalid JSON"})
        except ValueError as exc:
            _log_event(logging.WARNING, "request_error", request_id=request_id, path=self.path, error=str(exc))
            _json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "request_id": request_id, "error": str(exc)})
        except ResearchError as exc:
            _log_event(logging.WARNING, "research_error", request_id=request_id, path=self.path, error=str(exc))
            _json_response(self, HTTPStatus.BAD_GATEWAY, {"ok": False, "request_id": request_id, "error": str(exc)})
        except ProviderQuotaError as exc:
            _log_event(logging.WARNING, "provider_quota_error", request_id=request_id, path=self.path, error=str(exc))
            _json_response(self, HTTPStatus.TOO_MANY_REQUESTS, {"ok": False, "request_id": request_id, "error": str(exc)})
        except ProviderAccessError as exc:
            _log_event(logging.WARNING, "provider_access_error", request_id=request_id, path=self.path, error=str(exc))
            _json_response(self, HTTPStatus.BAD_GATEWAY, {"ok": False, "request_id": request_id, "error": str(exc)})
        except Exception as exc:
            LOGGER.exception("request_failed request_id=%s path=%s", request_id, self.path)
            ERROR_LOGGER.exception("request_failed request_id=%s path=%s", request_id, self.path)
            _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "request_id": request_id, "error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), DebateCardHandler)
    print(f"Serving on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
