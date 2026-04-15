# Debugging

## First Places To Look

For most failures, start with:

- `logs/errors.log`
- `logs/research.log`
- `logs/providers.log`

Those three logs usually tell you whether the failure came from:

- search quality
- provider access
- source validation
- card validation
- response writing

## Common Failure Modes

### Bad search results

Symptoms:

- irrelevant TV, dictionary, support, or SEO pages
- repeated source-validation rejections
- weak or empty candidate pools

Code paths:

- `_heuristic_query_pack`
- `_collect_discovered_sources`
- `_select_mixed_candidate_pool`

### Provider access problems

Symptoms:

- `ProviderAccessError`
- model timeouts
- incomplete JSON
- quota errors

Code paths:

- `_call_provider_json`
- `_call_provider_stage`
- `_call_chat_completion_provider`

Logs:

- `logs/providers.log`
- `logs/errors.log`

### Source pool looks fine but cutting still fails

Symptoms:

- source validation keeps rejecting candidates
- the app falls back after retrying research

Code paths:

- `_select_source_order_with_ai`
- `_run_source_validation_stage`
- `_refresh_cut_candidate_pool`
- `_cut_cards`

### Export problems

Symptoms:

- `.docx` download fails
- broken debate-file formatting in exported output

Code paths:

- `_export_docx`
- `_build_docx_card_blocks`
- `_build_docx_bytes`

## Useful Local Checks

Syntax and import:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
py -3 -c "import ast, pathlib; ast.parse(pathlib.Path('server.py').read_text(encoding='utf-8')); print('AST_OK')"
py -3 -c "import server; print('IMPORT_OK')"
```

Targeted research probe:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
@'
import server
payload = {'draft_tag': 'Intervention degrades troop morale and retention', 'semantic_search_enabled': True}
payload['query_pack'] = server._heuristic_query_pack(payload, semantic_enabled=True)
print(server._research_sources(payload).get('selected'))
'@ | py -3 -
```

Targeted cut probe:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
@'
import server
print(server._cut_cards({'draft_tag': 'Intervention degrades troop morale and retention', 'semantic_search_enabled': True, 'desired_cards': 1}).get('meta'))
'@ | py -3 -
```

## Refactor Guardrails

When refactoring `server.py`, keep these boundaries stable:

- request parsing and HTTP responses stay near the handler
- research stays separate from card cutting
- source validation stays separate from card validation
- fallback behavior remains deterministic

The easiest safe improvement is usually helper extraction inside one workflow, not cross-cutting abstraction.
