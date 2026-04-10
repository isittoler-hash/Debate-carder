from __future__ import annotations

import json
import os
import re
import ssl
import sys
from datetime import date
import urllib.request
from collections import Counter
from html import unescape
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse


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
MAX_BODY_BYTES = 5 * 1024 * 1024
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.1")
OPENAI_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/responses")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "").strip()
OPENAI_COMPAT_BASE_URL = os.getenv("OPENAI_COMPAT_BASE_URL", "").rstrip("/")
OPENAI_COMPAT_PATH = os.getenv("OPENAI_COMPAT_PATH", "/chat/completions").strip() or "/chat/completions"
OPENAI_COMPAT_MODEL = os.getenv("OPENAI_COMPAT_MODEL", "").strip()
OPENAI_COMPAT_API_KEY = os.getenv("OPENAI_COMPAT_API_KEY", "").strip()
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
CHATGPT_BRIDGE_TIMEOUT = _env_int("CHATGPT_BRIDGE_TIMEOUT", 120)
SEARCH_RESULTS = _env_int("SEARCH_RESULTS", 50)
SOURCE_RETRY_LIMIT = _env_int("SOURCE_RETRY_LIMIT", 10)
SOURCE_SELECTION_SNIPPET_CHARS = _env_int("SOURCE_SELECTION_SNIPPET_CHARS", 220)
SEARCH_TIMEOUT = _env_int("SEARCH_TIMEOUT", 20)
FETCH_TIMEOUT = _env_int("FETCH_TIMEOUT", 20)
FETCH_MAX_BYTES = _env_int("FETCH_MAX_BYTES", 1500000)
MODEL_INPUT_MAX_CHARS = _env_int("MODEL_INPUT_MAX_CHARS", 24000)
SEARCH_ENGINE = os.getenv("SEARCH_ENGINE", "duckduckgo").strip().lower()
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)


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


def _json_response(handler: SimpleHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.end_headers()
    handler.wfile.write(body)


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


def to_array(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


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
    normalized["provider"] = _clean_text(payload.get("provider") or payload.get("model_provider"))
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


def _build_formatted_card(card: dict[str, Any]) -> str:
    lines = []
    tag_line = _clean_text(card.get("tag_line") or card.get("title"))
    cite_line = _clean_text(card.get("cite_line"))
    verbal_citation = _clean_text(card.get("verbal_citation"))
    full_context = _clean_text(card.get("full_context") or card.get("body"))
    read_text = _clean_text(card.get("read_text") or card.get("evidence"))

    if tag_line:
        lines.append(tag_line)
    if cite_line:
        lines.append(cite_line)
    if verbal_citation:
        lines.append(f"Verbal cite: {verbal_citation}")
    if full_context:
        lines.append(full_context)
    if read_text and read_text != full_context:
        lines.append("")
        lines.append(f"Read text: {read_text}")
    return "\n".join(lines).strip()


def _build_card_source(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _clean_text(payload.get("source_title")),
        "author": _clean_text(payload.get("source_author")),
        "author_qualifications": _clean_text(payload.get("author_qualifications") or payload.get("source_author_qualifications")),
        "date": _clean_text(payload.get("source_date")),
        "publication": _clean_text(payload.get("source_publication")),
        "url": _clean_text(payload.get("source_url")),
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


def _normalize_provider(value: Any) -> str:
    provider = _clean_text(value).lower()
    if provider in {"ollama", "local", "local_model", "local-model"}:
        return "ollama"
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
    raise ValueError("Unsupported provider. Use ollama, chatgpt_bridge, openai_compat, openai, or fallback.")


def _provider_preference(payload: dict[str, Any]) -> list[str]:
    configured_provider = _validate_requested_provider(payload)
    if configured_provider:
        return [configured_provider, "fallback"]

    if OLLAMA_MODEL:
        return ["ollama", "chatgpt_bridge", "openai_compat", "openai", "fallback"]
    if os.getenv("LOCAL_MODEL_PROVIDER", "").strip().lower() == "ollama":
        return ["ollama", "chatgpt_bridge", "openai_compat", "openai", "fallback"]
    if CHATGPT_BRIDGE_BASE_URL and CHATGPT_BRIDGE_MODEL:
        return ["chatgpt_bridge", "openai_compat", "openai", "fallback"]
    if OPENAI_COMPAT_BASE_URL and OPENAI_COMPAT_MODEL:
        return ["openai_compat", "openai", "fallback"]
    if os.getenv("OPENAI_API_KEY", "").strip():
        return ["openai", "fallback"]
    return ["fallback"]


def _summarize_card_for_prompt(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "tag_line": _clean_text(card.get("tag_line") or card.get("title")),
        "short_citation": _clean_text(card.get("short_citation")),
        "read_text": _clean_text(card.get("read_text") or card.get("evidence") or card.get("card_text")),
        "claim": _clean_text(card.get("claim")),
        "warrant": _clean_text(card.get("warrant")),
        "impact": _clean_text(card.get("impact")),
    }


def _summarize_candidate_for_prompt(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": int(candidate.get("index", 0) or 0),
        "engine": _clean_text(candidate.get("engine")),
        "title": _clean_text(candidate.get("title")),
        "url": _clean_text(candidate.get("url")),
        "author": _clean_text(candidate.get("author")),
        "publication": _clean_text(candidate.get("publication")),
        "published": _clean_text(candidate.get("published")),
        "score": round(float(candidate.get("score", 0.0)), 2),
        "content_type": _clean_text(candidate.get("content_type")),
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
    }

    if candidate_card:
        base_input["candidate_card"] = {
            "tag_line": _clean_text(candidate_card.get("tag_line") or candidate_card.get("title")),
            "short_citation": _clean_text(candidate_card.get("short_citation")),
            "full_citation": _clean_text(candidate_card.get("full_citation") or candidate_card.get("citation")),
            "cite_line": _clean_text(candidate_card.get("cite_line")),
            "verbal_citation": _clean_text(candidate_card.get("verbal_citation")),
            "read_text": _clean_text(candidate_card.get("read_text") or candidate_card.get("highlighted_text") or candidate_card.get("evidence")),
            "full_context": _clean_text(candidate_card.get("full_context") or candidate_card.get("body")),
            "highlighted_text": _clean_text(candidate_card.get("highlighted_text") or candidate_card.get("excerpt")),
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
                "read_text": "string",
                "full_context": "string",
                "quoted_text": "string",
                "exact_excerpt": "string",
                "highlighted_text": "string",
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
                    "title": "string",
                    "author": "string",
                    "author_qualifications": "string",
                    "date": "string",
                    "publication": "string",
                    "url": "string",
                },
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
                "If the card is weak, unsupported, too broad, duplicated, or awkwardly formatted, revise it.",
                "Return exactly one final card in a cards array.",
                "Include a validation object with useful, revised, notes, issues, and confidence when possible.",
                "Keep the debate-file structure intact: tag line, short cite, bracketed cite line ending in //IT, then readable evidence text.",
                "Preserve compatibility by also returning the legacy fields title, tag, citation, card_text, body, evidence, excerpt, and highlighted_excerpt.",
            ],
            "input": base_input,
            "output_schema": {
                **base_schema,
                "validation": {
                    "useful": "boolean",
                    "revised": "boolean",
                    "notes": "string",
                    "issues": ["string"],
                    "confidence": "number",
                },
            },
        }

    return {
        "task": "Cut one debate card from the provided source or article.",
        "requirements": [
            "Return strict JSON only.",
            "Create exactly one card in the cards array.",
            "Every card must be concise, reusable in debate, and anchored to the source text.",
            "Prefer the card shape used in actual debate files: tag_line, short_citation, full_citation, verbal_citation, read_text, full_context, highlighted_text, date_accessed, and source_url.",
            "If available, include author_qualifications and optional claim, warrant, impact fields.",
            "Model the result after the user's actual files: tag line, short cite plus bracketed full cite ending with //IT, then a full evidence paragraph with a clearly identified read_text/highlighted_text segment.",
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
        source_info = {
            "title": _clean_text(source.get("title") or card.get("source_title") or card.get("publication") or card.get("outlet")),
            "author": _clean_text(source.get("author") or card.get("author")),
            "author_qualifications": _clean_text(source.get("author_qualifications") or card.get("author_qualifications")),
            "date": _clean_text(source.get("date") or card.get("source_date") or card.get("date")),
            "publication": _clean_text(source.get("publication") or source.get("outlet") or card.get("source_publication") or card.get("publication") or card.get("outlet")),
            "url": _clean_text(source.get("url") or card.get("source_url") or card.get("url")),
        }
        tag_line = _clean_text(card.get("tag_line") or card.get("title") or card.get("heading") or card.get("tag"))
        read_text = _clean_text(card.get("read_text") or card.get("highlighted_text") or card.get("highlighted_excerpt") or card.get("excerpt") or card.get("evidence") or card.get("card_text"))
        full_context = _clean_text(card.get("full_context") or card.get("body") or card.get("card_text") or card.get("evidence") or read_text)
        short_citation = _clean_text(card.get("short_citation")) or _build_short_citation(source_info)
        full_citation = _clean_text(card.get("full_citation")) or _build_full_citation(source_info, _clean_text(card.get("date_accessed")) or _today_accessed())
        cite_line = _clean_text(card.get("cite_line")) or _build_cite_line(short_citation, full_citation)
        verbal_citation = _clean_text(card.get("verbal_citation")) or _build_verbal_citation(source_info)
        date_accessed = _clean_text(card.get("date_accessed")) or _today_accessed()
        highlighted_text = _clean_text(card.get("highlighted_text") or card.get("highlighted_excerpt") or read_text)
        exact_excerpt = _clean_text(card.get("exact_excerpt") or card.get("quoted_text") or card.get("excerpt") or highlighted_text or read_text)
        claim = _clean_text(card.get("claim") or card.get("takeaway") or card.get("thesis"))
        warrant = _clean_text(card.get("warrant") or card.get("reason") or card.get("analysis"))
        impact = _clean_text(card.get("impact") or card.get("significance") or card.get("implication"))
        source_url = _clean_text(card.get("source_url") or source_info["url"])
        author_qualifications = _clean_text(card.get("author_qualifications") or source_info["author_qualifications"])
        normalized = {
            "tag_line": tag_line,
            "short_citation": short_citation,
            "full_citation": full_citation,
            "cite_line": cite_line,
            "verbal_citation": verbal_citation,
            "author_qualifications": author_qualifications,
            "read_text": read_text,
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
            "card_text": read_text or full_context,
            "body": full_context,
            "evidence": read_text or full_context,
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


def _fetch_url_bytes(url: str, timeout: int, max_bytes: int) -> tuple[bytes, str, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "identity",
        },
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, context=context, timeout=timeout) as resp:
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
    pattern = re.compile(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
    for offset in range(0, max(limit, 1), 30):
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}&s={offset}"
        body, _, charset, _ = _fetch_url_bytes(search_url, SEARCH_TIMEOUT, 500000)
        html_text = body.decode(charset, errors="replace")
        page_added = 0
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


def _search_bing(query: str, limit: int) -> list[dict[str, Any]]:
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
    for provider in providers:
        try:
            if provider == "bing":
                provider_results = _search_bing(query, limit)
            else:
                provider_results = _search_duckduckgo(query, limit)
        except Exception:
            continue
        for item in provider_results:
            url = item.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            results.append(item)
            if len(results) >= limit:
                return results
    return results


def _fetch_article(url: str, timeout: int = FETCH_TIMEOUT, max_bytes: int = FETCH_MAX_BYTES) -> dict[str, Any]:
    body, content_type, charset, final_url = _fetch_url_bytes(url, timeout, max_bytes)
    text = body.decode(charset, errors="replace")
    if "html" in content_type or "xml" in content_type or "<html" in text[:1000].lower():
        parsed = _parse_html_text(text)
        extracted = parsed["text"]
        return {
            "url": final_url,
            "title": parsed["title"],
            "publication": parsed["title"] or urlparse(final_url).netloc,
            "author": parsed["author"],
            "published": parsed["published"],
            "description": parsed["description"],
            "text": extracted,
            "content_type": content_type,
            "byte_count": len(body),
        }

    cleaned = re.sub(r"\s+", " ", text).strip()
    return {
        "url": final_url,
        "title": "",
        "publication": urlparse(final_url).netloc,
        "author": "",
        "published": "",
        "description": "",
        "text": cleaned,
        "content_type": content_type,
        "byte_count": len(body),
    }


def _research_query(payload: dict[str, Any]) -> str:
    pieces = [
        _clean_text(payload.get("draft_tag")),
        _clean_text(payload.get("resolution")),
        _clean_text(payload.get("emphasis")),
    ]
    query = " ".join(piece for piece in pieces if piece)
    return re.sub(r"\s+", " ", query).strip()


def _candidate_score(candidate: dict[str, Any], query_terms: set[str], phrase: str) -> float:
    title = _clean_text(candidate.get("title")).lower()
    description = _clean_text(candidate.get("description")).lower()
    text = _clean_text(candidate.get("text")).lower()
    score = 0.0
    for term in query_terms:
        if term in title:
            score += 4
        if term in description:
            score += 2
        if term in text:
            score += 1
    if phrase and phrase in title:
        score += 12
    if phrase and phrase in text:
        score += 6
    score += min(len(text) / 1000.0, 8.0)
    if len(text) < 300:
        score -= 3
    return score


def _candidate_snippet(candidate: dict[str, Any], max_chars: int = SOURCE_SELECTION_SNIPPET_CHARS) -> str:
    return _truncate(
        _clean_text(candidate.get("description"))
        or _clean_text(candidate.get("text")),
        max_chars,
    )


def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": int(candidate.get("index", 0) or 0),
        "engine": candidate.get("engine", ""),
        "title": _clean_text(candidate.get("title")),
        "url": _clean_text(candidate.get("url")),
        "author": _clean_text(candidate.get("author")),
        "publication": _clean_text(candidate.get("publication")),
        "date": _clean_text(candidate.get("published")),
        "score": round(float(candidate.get("score", 0.0)), 2),
        "content_type": _clean_text(candidate.get("content_type")),
        "byte_count": int(candidate.get("byte_count", 0) or 0),
        "fetch_error": _clean_text(candidate.get("fetch_error")),
        "snippet": _candidate_snippet(candidate),
    }


def _research_sources(payload: dict[str, Any]) -> dict[str, Any]:
    article_text = _clean_text(payload.get("article_text"))
    source_url = _normalize_web_url(_clean_text(payload.get("source_url")))
    draft_tag = _clean_text(payload.get("draft_tag"))
    query = _research_query(payload)

    if article_text:
        return {
            "used": False,
            "query": query,
            "sources": [],
            "selected": {
                "title": _clean_text(payload.get("source_title")),
                "publication": _clean_text(payload.get("source_publication")),
                "author": _clean_text(payload.get("source_author")),
                "date": _clean_text(payload.get("source_date")),
                "url": source_url or _clean_text(payload.get("source_url")),
                "text": _truncate(article_text, 1200),
                "engine": "provided",
            },
            "article_text": article_text,
            "_candidates": [],
        }

    discovered: list[dict[str, Any]] = []
    if source_url:
        discovered.append(
            {
                "engine": "provided",
                "title": _clean_text(payload.get("source_title")),
                "url": source_url,
                "query": query,
            }
        )

    if query:
        discovered.extend(_search_web(query, SEARCH_RESULTS))
    elif source_url:
        discovered = discovered[:1]
    else:
        raise ValueError("article_text, source_url, or draft_tag is required")

    fetched: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in discovered:
        url = _normalize_web_url(item.get("url", ""))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
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
            fetched.append(item)
            continue
        item = {
            **item,
            **fetched_item,
        }
        fetched.append(item)

    if not fetched:
        raise RuntimeError("No fetchable sources found")

    query_terms = _score_terms(query or draft_tag)
    phrase = (draft_tag or query).lower()
    for item in fetched:
        item["score"] = _candidate_score(item, query_terms, phrase)
    selected = max(fetched, key=lambda item: item.get("score", -999))
    selected_text = _clean_text(selected.get("text"))
    if not selected_text and selected.get("description"):
        selected_text = _clean_text(selected.get("description"))
    if not selected_text and draft_tag:
        selected_text = draft_tag

    ranked = sorted(fetched, key=lambda item: item.get("score", -999), reverse=True)
    return {
        "used": True,
        "query": query,
        "sources": [_public_candidate({**item, "index": index + 1}) for index, item in enumerate(ranked[:SEARCH_RESULTS])],
        "selected": {
            "index": 1,
            "engine": selected.get("engine", ""),
            "title": _clean_text(selected.get("title") or payload.get("source_title")),
            "publication": _clean_text(selected.get("publication") or payload.get("source_publication")),
            "author": _clean_text(selected.get("author") or payload.get("source_author")),
            "date": _clean_text(selected.get("published") or payload.get("source_date")),
            "url": _clean_text(selected.get("url") or source_url or payload.get("source_url")),
            "text": _truncate(selected_text, 4000),
            "score": round(float(selected.get("score", 0.0)), 2),
        },
        "article_text": selected_text,
        "_candidates": [{**item, "index": index + 1} for index, item in enumerate(ranked)],
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
        full_context = _truncate(next((para for para in paragraphs if sentence in para), " ".join(nearby)), 1400)
        read_text = _truncate(sentence, 420)
        highlighted_text = read_text
        tag_line = _truncate(
            " - ".join(bit for bit in [resolution or "Debate card", f"Point {rank + 1}", emphasis] if bit),
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
            "read_text": read_text,
            "full_context": full_context,
            "quoted_text": read_text,
            "exact_excerpt": read_text,
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
            "card_text": read_text,
            "body": full_context,
            "evidence": read_text,
            "source": source,
            "excerpt": highlighted_text,
            "highlighted_excerpt": highlighted_text,
        }
        card["formatted_card"] = _build_formatted_card(card)
        cards.append(card)

    if not cards and article_text:
        excerpt = _truncate(article_text, 500)
        tag_line = _truncate(resolution or "Debate card", 180)
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
            "read_text": excerpt,
            "full_context": excerpt,
            "quoted_text": excerpt,
            "exact_excerpt": excerpt,
            "highlighted_text": excerpt,
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
    confidence = value.get("confidence")

    normalized: dict[str, Any] = {}
    if useful is not None:
        normalized["useful"] = bool(useful)
    if revised is not None:
        normalized["revised"] = bool(revised)
    if notes:
        normalized["notes"] = notes
    if status:
        normalized["status"] = status
    issues = _normalize_validation_issues(value.get("issues") or value.get("problems") or value.get("concerns"))
    if issues:
        normalized["issues"] = issues
    if isinstance(confidence, (int, float)):
        normalized["confidence"] = confidence
    return normalized


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
    ]
    return any(term in text for term in weak_terms)


def _build_source_selection_prompt(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "task": "Choose the best sources for cutting one debate card.",
        "requirements": [
            "Return strict JSON only.",
            "Rank the candidates by which source is most likely to produce a strong, specific, usable debate card.",
            "Prefer sources with clear, quotable evidence and a direct connection to the draft tag, resolution, side, and emphasis.",
            "Avoid ranking weak, generic, duplicated, or irrelevant sources highly.",
            "Return selected_indices as a ranked list of 1-based candidate indices.",
        ],
        "input": {
            "draft_tag": _clean_text(payload.get("draft_tag")),
            "resolution": _clean_text(payload.get("resolution")),
            "side": _normalize_side(_clean_text(payload.get("side"))),
            "emphasis": _clean_text(payload.get("emphasis")),
            "candidates": [
                {
                    "index": index + 1,
                    "title": _clean_text(candidate.get("title")),
                    "author": _clean_text(candidate.get("author")),
                    "publication": _clean_text(candidate.get("publication")),
                    "date": _clean_text(candidate.get("published")),
                    "url": _clean_text(candidate.get("url")),
                    "heuristic_score": round(float(candidate.get("score", 0.0)), 2),
                    "snippet": _candidate_snippet(candidate),
                }
                for index, candidate in enumerate(candidates)
            ],
        },
        "output_schema": {
            "selected_indices": [1, 2, 3],
            "notes": "string",
        },
    }


def _parse_selected_candidate_indices(parsed: dict[str, Any], total_candidates: int) -> list[int]:
    raw_indices = parsed.get("selected_indices") or parsed.get("ranked_indices") or parsed.get("candidate_indices") or []
    if not isinstance(raw_indices, list):
        raw_indices = [parsed.get("selected_index")] if parsed.get("selected_index") is not None else []

    indices: list[int] = []
    for raw in raw_indices:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
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
        }
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    context = ssl.create_default_context()
    with urllib.request.urlopen(req, context=context, timeout=timeout) as resp:
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
            "max_output_tokens": 1800,
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
    context = ssl.create_default_context()
    with urllib.request.urlopen(req, context=context, timeout=60) as resp:
        response_json = json.loads(resp.read().decode("utf-8"))
    return _parse_json_text(_extract_text_from_response(response_json))


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
    context = ssl.create_default_context()
    with urllib.request.urlopen(req, context=context, timeout=OLLAMA_TIMEOUT) as resp:
        response_json = json.loads(resp.read().decode("utf-8"))
    message = response_json.get("message") if isinstance(response_json, dict) else None
    text = _text_from_value(message.get("content") if isinstance(message, dict) else response_json.get("response"))
    return _parse_json_text(text)


def _call_provider_json(provider: str, prompt: dict[str, Any]) -> dict[str, Any]:
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
    }


def _default_validation_meta(*, notes: str, revised: bool, useful: bool = True, issues: list[str] | None = None) -> dict[str, Any]:
    meta = {
        "useful": useful,
        "revised": revised,
        "notes": _clean_text(notes),
    }
    normalized_issues = [issue for issue in (issues or []) if _clean_text(issue)]
    if normalized_issues:
        meta["issues"] = normalized_issues
    return meta


def _call_provider_stage(
    provider: str,
    payload: dict[str, Any],
    *,
    stage: str = "cut",
    candidate_card: dict[str, Any] | None = None,
) -> dict[str, Any]:
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

    context = ssl.create_default_context()
    with urllib.request.urlopen(req, context=context, timeout=timeout) as resp:
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
        "max_output_tokens": 2500,
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

    context = ssl.create_default_context()
    with urllib.request.urlopen(req, context=context, timeout=60) as resp:
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

    context = ssl.create_default_context()
    with urllib.request.urlopen(req, context=context, timeout=OLLAMA_TIMEOUT) as resp:
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
    research_error = ""
    try:
        research_meta = _research_sources(payload)
    except Exception as exc:
        research_error = str(exc)
        research_meta = {
            "used": False,
            "query": _research_query(payload),
            "sources": [],
            "selected": {},
            "article_text": _clean_text(payload.get("article_text") or payload.get("draft_tag") or payload.get("resolution")),
            "error": research_error,
            "_candidates": [],
        }

    candidate_pool = list(research_meta.pop("_candidates", []) or [])
    public_research_meta = dict(research_meta)
    payload = dict(payload)
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
    }
    if research_error:
        base_meta["research_error"] = research_error

    errors: list[str] = []
    for provider in _provider_preference(payload):
        if provider == "fallback":
            break
        try:
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
                except Exception as selection_exc:
                    selection_errors.append(f"{provider} source_select: {selection_exc}")

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

                cut_result = _call_provider_stage(provider, attempt_payload, stage="cut")
                final_card = cut_result["cards"][0]
                validation_completed = False
                validation_errors: list[str] = []
                validation_meta = _extract_validation_meta({"cards": cut_result["cards"]}) or _default_validation_meta(
                    notes="Initial cut completed; validation pass did not return notes yet.",
                    revised=False,
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
                    validation_meta = validation_result.get("validation") or _extract_validation_meta({"cards": validation_result["cards"]})
                    revised = final_card.get("formatted_card") != cut_result["cards"][0].get("formatted_card")
                    if not validation_meta:
                        validation_meta = _default_validation_meta(
                            notes="Validation pass completed without explicit notes.",
                            revised=revised,
                        )
                    else:
                        validation_meta.setdefault("revised", revised)
                        validation_meta.setdefault("useful", True)
                except Exception as validation_exc:
                    validation_errors.append(f"{provider} validate: {validation_exc}")
                    validation_meta = _default_validation_meta(
                        notes=f"Validation pass failed: {validation_exc}",
                        revised=False,
                        useful=False,
                        issues=["Returning the initial cut because the validation pass failed."],
                    )

                final_card["validation"] = validation_meta
                if _validation_is_weak(validation_meta):
                    note = _clean_text(validation_meta.get("notes")) or "Validation marked the card as not useful."
                    attempt_errors.append(f"{provider} source_attempt_{attempt_index}: {note}")
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
                                "text": _truncate(attempt_text, 4000),
                            },
                            "source_selection": selection_meta,
                        },
                        "validation_ran": True,
                        "validation_completed": validation_completed,
                        "validation_provider": provider,
                        "validation": validation_meta,
                        "source_attempts": attempt_index,
                    },
                }
                provider_errors = [*errors, *selection_errors, *attempt_errors, *validation_errors]
                if provider_errors:
                    result["meta"]["provider_errors"] = provider_errors
                return {"ok": True, **result}

            errors.extend([*selection_errors, *attempt_errors])
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            continue

    cards = _build_fallback_cards(payload)
    fallback_validation = _default_validation_meta(
        notes="Fallback cutter used a heuristic validation pass.",
        revised=False,
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
        try:
            payload = _normalize_payload(_read_json_body(self))
            if self.path == "/api/research":
                research = dict(_research_sources(payload))
                research.pop("_candidates", None)
                _json_response(self, HTTPStatus.OK, {"ok": True, "research": research})
                return
            if self.path != "/api/cut":
                _json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"})
                return
            if not _clean_text(payload.get("article_text")) and not _clean_text(payload.get("draft_tag")) and not _clean_text(payload.get("source_url")):
                raise ValueError("article_text, draft_tag, or source_url is required")
            result = _cut_cards(payload)
            _json_response(self, HTTPStatus.OK, result)
        except json.JSONDecodeError:
            _json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Invalid JSON"})
        except ValueError as exc:
            _json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
        except Exception as exc:
            _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})

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
