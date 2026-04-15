# Architecture

This repository is a small application with a large single-file backend:

- `index.html`, `styles.css`, `app.js`: static frontend
- `server.py`: stdlib HTTP server, research pipeline, card cutting flow, queue worker, and `.docx` export
- `logs/`: rotating runtime logs

## Runtime Shape

The app runs as:

1. A browser UI served from the same Python process.
2. A `ThreadingHTTPServer` in `server.py`.
3. A set of JSON endpoints used by the frontend.

Important endpoints:

- `POST /api/research`
- `POST /api/cut`
- `POST /api/queue`
- `POST /api/export/docx`

## Backend Flow

The backend is organized around four major workflows.

### 1. Research

Primary entrypoint:

- `_research_sources`

Responsibilities:

- refine or build a query pack
- search academic, think-tank, and general-web sources
- fetch candidate pages
- classify and score candidates
- build a mixed candidate pool for AI source selection

Key helper groups:

- query construction: `_refine_query_pack`, `_heuristic_query_pack`, `_expand_query_pack_for_research_round`
- search providers: `_search_web`, `_search_duckduckgo`, `_search_bing`
- candidate scoring/classification: `_classify_candidate`, `_candidate_metrics`, `_select_mixed_candidate_pool`

### 2. Card Cutting

Primary entrypoint:

- `_cut_cards`

Responsibilities:

- load or synthesize the research packet
- let the model rank source candidates
- validate each selected source before cutting
- cut one card
- run a second validation pass on the card
- retry research with a refined query pack when the source pool is weak
- fall back to heuristic output if no provider succeeds

Refactored helper boundaries:

- research/context setup: `_resolve_cut_research_context`
- attempt building: `_build_cut_attempts`, `_prepare_cut_attempt_payload`
- source validation: `_run_source_validation_stage`
- card validation: `_run_card_validation_stage`
- retry refresh: `_refresh_cut_candidate_pool`
- success assembly: `_build_cut_success_result`

### 3. Queue Execution

Primary entrypoint:

- `_queue_cut_cards`

Responsibilities:

- parse one tag per line or a list of tags
- run repeated `_cut_cards` calls
- preserve prior cards so later items can avoid duplicates
- optionally parallelize work with `ThreadPoolExecutor`

### 4. DOCX Export

Primary entrypoints:

- `_export_docx`
- `_build_docx_bytes`

Responsibilities:

- normalize card payloads
- render debate-card blocks
- assemble a minimal `.docx` package manually with `zipfile`

## Frontend Responsibilities

`app.js` is responsible for:

- form state
- session-library persistence via `localStorage`
- queue progress rendering
- request/response orchestration for `/api/*`
- card rendering and export triggers

The frontend does not do research ranking or evidence formatting logic. That stays on the backend.

## Logging

Runtime logs are split by concern:

- `logs/server.log`
- `logs/research.log`
- `logs/providers.log`
- `logs/requests.log`
- `logs/errors.log`

The shared event writer is `_log_event`.

## Provider Model

Provider choice is centralized through:

- `_provider_preference`
- `_call_provider_stage`
- `_call_provider_json`

There are two broad classes of model calls:

1. JSON control calls for source selection, query refinement, and source validation.
2. Card-generation calls for `cut` and `validate`.

## Maintenance Notes

The codebase is still intentionally conservative:

- stdlib server instead of a web framework
- one backend module instead of many packages
- explicit JSON payload construction instead of deep abstractions

When extending the backend, prefer extracting helpers around a single workflow instead of adding another layer of generic indirection.
