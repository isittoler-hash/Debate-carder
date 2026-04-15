# AI Debate Card Cutter

Debate evidence cutter with a static frontend, a Python stdlib backend, draft-tag source discovery, semantic or literal query refinement, one-card iterative cutting, queued multi-tag cutting, session card storage, `.verbatim.docx` export, local or remote model support, full-URL citations, source credibility scoring, span-based underlining/highlighting, manual ChatGPT copy/paste support, and a deterministic fallback when no model is available.

## Documentation

- Architecture: `docs/ARCHITECTURE.md`
- Debugging: `docs/DEBUGGING.md`

## What This Is For

The app is built around a debate workflow, not a generic chat workflow:

1. Start with a rough draft tag.
2. Refine the meaning of that tag, then research likely source material from the meaning.
3. Fetch and extract the article text.
4. Cut one debate-style card.
5. Validate the candidate card in a separate AI call.
6. Revise the card if needed.
7. Save the finished card into the session library.
8. Copy or export the result into a debate file.

You can also skip research and paste evidence directly.

## Search Modes

The app supports two search modes:

- `Semantic search` is the default. It searches for the meaning of the draft tag rather than only the exact words.
- `Literal search` keeps the current exact-word query style.

The mode is controlled by a UI toggle near the research controls. The app also shows a read-only query preview so you can see the refined query pack before the search runs.

In semantic mode, the backend can generate AI-refined search strings when a model is available. If no AI provider is available, it falls back to deterministic heuristic query expansion so research can still continue.

## What A Debate Card Looks Like

The backend returns a debate-native shape that mirrors the structure in your sample `.docx` files and the debate wiki style:

- `tag_line`: the headline or claim at the top of the card
- `short_citation`: the compact cite, usually `Surname YY`
- `full_citation`: the longer source cite with source details, full source URL, and date accessed
- `cite_line`: the assembled cite line, usually `Shortcite [full cite] //IT`
- `verbal_citation`: the cite phrasing you can read in-round
- `author_qualifications`: author credential text when available
- `underlined_spans`: the support spans that justify the card
- `highlighted_spans`: the subset of spans you would actually read in-round
- `underlined_text`: compatibility text derived from the underlined spans
- `highlighted_text`: compatibility text derived from the highlighted spans
- `full_context`: the surrounding paragraph or context
- `quoted_text` / `exact_excerpt`: aliases for the quoted passage
- `formatted_card`: a plain-text rendering of the whole card
- `validation`: the recursive usefulness check and revision notes
- `source_url`: the source location
- `source_id`: the selected research packet identifier
- `credibility_score`: a heuristic credibility score for the source
- `credibility_notes`: notes explaining that score
- `source_class`: `peer_reviewed`, `preprint`, `working_paper`, `think_tank`, `general_web`, `summary_or_news`, or `unknown`
- `paper_verified`: whether the source looks like an actual paper or full paper PDF instead of a summary page
- `paper_confidence`: how confident the backend is that the source is a real paper
- `doi`: DOI metadata when available
- `pdf_url`: the full PDF URL when available
- `paper_signals`: signals that support the paper classification
- `summary_signals`: signals that suggest the source is only a summary or overview
- `date_accessed`: the access date used in the cite
- `claim`, `warrant`, `impact`: optional debate explanation fields

The backend also keeps legacy compatibility fields:

- `title`
- `tag`
- `citation`
- `card_text`
- `body`
- `evidence`
- `excerpt`
- `highlighted_excerpt`
- `read_text` is still accepted as a compatibility alias, but the current prompt and export flow are built around spans rather than a made-up read text field.

## Query Preview

When you research from a draft tag, the UI shows a read-only preview of the refined query pack. That preview includes:

- the active search mode
- the intent claim derived from the draft tag
- the literal query
- the semantic and academic query variants
- the think-tank and fallback web variants
- whether the query pack came from AI refinement or heuristic fallback

The preview is informational only in v1.

### Evidence Marking

The app treats underlining and highlighting as separate instructions:

- `underlined_spans` means all of the important source language that supports the argument.
- `highlighted_spans` means the smaller set of words or phrases you would actually read in-round.
- `highlighted_spans` can be discontiguous. The model can jump sentence to sentence or word to word if that makes the best read.
- `read_text` is not something the model is asked to invent. If it exists at all, it is derived from the highlighted spans for compatibility.

### Example Card Layout

```text
Tariffs raise input costs for domestic manufacturing
Smith 25 [Jane Smith, 2025, Policy Journal, https://example.com/article, DOA:04-08-2026] //IT

In the larger paragraph, Smith explains that [[tariffs raise the cost of imported components, which increases production costs across the sector]] and weakens competitiveness.
```

## Research Basis

The current card format is based on three things:

1. Your sample `.docx` files, which consistently follow the pattern `tag line -> cite line -> evidence paragraph`.
2. Debate cite guidance that favors predictable, one-line citation structure with a readable full URL.
3. Evidence practice that distinguishes the tag, the source cite, the oral cite, the underlined support, and the exact read portion.

That is why the app separates `tag_line`, `short_citation`, `full_citation`, `cite_line`, `verbal_citation`, `underlined_spans`, `highlighted_spans`, and `full_context` instead of collapsing everything into one block.

Helpful external formatting references:

- Paperless Debate citation guidance: <https://docs.paperlessdebate.com/verbatim/cutting-evidence/citations>
- Paperless Debate cutting/formatting guidance: <https://docs.paperlessdebate.com/verbatim/cutting-evidence/formatting>
- NCFCA evidence citation samples PDF: <https://ncfca.org/wp-content/uploads/Debate-Evidence-Citation-Samples-1.pdf>

## What Changed In The Current UI

The current frontend is organized around five practical work surfaces:

1. The main card stage, which renders cards like debate evidence instead of a metadata dump.
2. A session library on the right side, which saves each finished card in the browser.
3. A queue box, which lets you paste one draft tag per line, shows per-tag progress, and runs them in sequence.
4. A query preview panel, which shows the refined search pack before research runs.
5. An export box, which downloads either plain text or a `.verbatim.docx` file containing the saved cards with citations and evidence formatting.

The saved library is browser-local. If you refresh the page, the cards persist through `localStorage` unless you clear them.

## How The Cite Is Built

The backend assembles cites in layers:

1. `short_citation` comes from the author surname and a two-digit year.
2. `full_citation` combines the author, date, title, publication or outlet, source URL, and date accessed.
3. `cite_line` joins the short cite with the full cite and adds the `//IT` marker.
4. `verbal_citation` is the oral version and prefers the author plus qualifications.
5. `underlined_spans`, `highlighted_spans`, and `full_context` are split so the UI can show the support language separately from the read portion and the surrounding paragraph.
6. `query_pack` and `executed_queries` describe the meaning-based search process when semantic search is enabled.

If a field is missing, the backend keeps what it can and leaves the rest blank instead of inventing details.

## Separate Validation Call

The current workflow is intentionally iterative and single-card:

1. Research the source from a draft tag or source URL.
2. Cut one candidate card.
3. Send that candidate card through a separate validation call.
4. Revise the card if the validation pass finds a weakness.
5. Keep only the final card.

The backend treats validation as a distinct stage. The validation prompt is not just a line inside the cut prompt. It is a second model call that checks:

- whether the underlined and highlighted spans are grounded in the source
- whether the highlighted spans are the strategically important subset
- whether the tag overclaims the evidence
- whether the card is useful enough to keep

If the validation stage says the card is weak, the backend can abandon that source and try another source instead.

## Mixed Source Pool

The backend does not only hand the AI one search result. It assembles a mixed pool and lets the AI choose the source that best supports the draft tag.

Default pool shape:

- 4 academic or paper-like candidates
- 2 think-tank or policy-report candidates
- 2 high-quality general web candidates

If one bucket is short, the backend backfills from the next best candidates. That gives the AI variety without forcing it to choose a source that only matches the tag literally.

Each source packet in the pool can include:

- `source_class`
- `paper_verified`
- `paper_confidence`
- `doi`
- `pdf_url`
- `paper_signals`
- `summary_signals`

## Working Modes

### 1. Research from a draft tag

Use this when you only know the rough argument.

Example draft tag:

```text
tariffs raise input costs and hurt domestic manufacturing competitiveness
```

The backend can:

- build a search query from the tag, resolution, side, and emphasis
- search a broad public web result set
- fetch candidate pages
- extract visible article text
- score candidates against the tag
- filter out blocked domains
- package multiple source candidates with full URLs, snippets, and credibility notes
- let an AI-capable provider rank the candidate pool before cutting
- tell the model what a real debate card should look like using condensed guidance from your sample files and debate formatting conventions
- retry alternate sources when validation says the first cut is weak
- cut one card from the chosen article
- run a separate validation pass on that card before returning it

### 2. Cut from pasted source text

Use this when you already have the article, PDF excerpt, or evidence block.

### 3. Cut from a direct URL

Use this when you know the exact article and want to bypass search.

### 4. Manual ChatGPT workflow

Use this when you have a ChatGPT subscription but do not want API billing.

The frontend generates a strict JSON cut prompt. You paste that prompt into ChatGPT, then paste the returned JSON back into the app.

The backend path is still the recommended way to get the separate validation call, because the backend now automatically performs source selection, cutting, and validation as distinct stages.

The subscription-friendly path is still manual unless you wire up a separate bridge service.

### 5. Queued tag workflow

Use this when you already have several argument claims and want the app to research and cut them back-to-back.

1. Put one draft tag per line in the queue box.
2. Click `Run queue`.
3. The frontend runs the research -> cut -> validate pipeline once per tag and updates queue status as each one is processed.
4. The backend runs the normal research -> cut -> validate pipeline once per tag.
5. Each successful card is added to the session library and rendered on the main stage.

### 6. Session library and export

Every completed card is saved into the sidebar library. From there you can:

- reopen a saved card on the main stage
- copy a saved card
- remove a saved card from the browser library
- download all saved cards as plain text
- download all saved cards as a `.verbatim.docx` file

### 7. Remote model hosting

Use this when you want inference on another machine, such as:

- a remote Ollama box
- a self-hosted OpenAI-compatible endpoint
- another vendor that exposes a chat-completions style API

This is the path to use if you want the frontend/backend local but the model elsewhere.

## Billing and Cost Notes

ChatGPT subscriptions and API billing are separate.

That means:

- your ChatGPT subscription cannot be used as a hidden backend API key
- if you want zero API cost, use a local model or a compatible endpoint you control
- if you want to use ChatGPT specifically, use the manual copy/paste workflow

OpenAI help docs:

- [Billing settings in ChatGPT vs Platform](https://help.openai.com/en/articles/9039756-billing-settings-in-chatgpt-vs-platform)
- [How can I move my ChatGPT subscription to the API?](https://help.openai.com/en/articles/8156019-how-can-i-move-my-chatgpt-subscription-to-the-api)

## Experimental ChatGPT Bridge

If you want to experiment with a ChatGPT-subscription bridge, keep it separate from the official API path and treat it as brittle.

The intended shape is:

1. Run a separate bridge service that logs into the ChatGPT web session or proxies it.
2. Point this app at that bridge with OpenAI-compatible env vars.
3. Expect the bridge to break when the upstream site or proxy changes.

This repo does not ship the bridge service itself. The old `transitive-bullshit/chatgpt-api` line of work is a historical reference point, not a supported dependency. If you revive a similar bridge, keep it opt-in and clearly marked experimental.

Example env values:

```dotenv
CHATGPT_BRIDGE_BASE_URL=http://127.0.0.1:3000/v1
CHATGPT_BRIDGE_MODEL=gpt-4o
CHATGPT_BRIDGE_API_KEY=
CHATGPT_BRIDGE_PATH=/chat/completions
```

## Quick Start

1. Copy `.env.example` to `.env`.
2. Configure at least one provider path.
3. Start the app:

```powershell
py server.py
```

4. Open:

```text
http://127.0.0.1:8000
```

## Setup Paths

### Local Ollama, no API cost

This is the preferred local path.

1. Install Ollama.
2. Pull a model:

```powershell
ollama pull llama3.1
```

3. Set:

```dotenv
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1
```

4. Start the app.

If the model is on another machine, point `OLLAMA_BASE_URL` at that host:

```dotenv
OLLAMA_BASE_URL=http://your-server:11434
OLLAMA_MODEL=llama3.1
```

### NVIDIA or another OpenAI-compatible hosted endpoint

Use this for hosted inference servers that expose an OpenAI-style chat endpoint.

```dotenv
OPENAI_COMPAT_BASE_URL=https://integrate.api.nvidia.com/v1
OPENAI_COMPAT_MODEL=tiiuae/falcon3-7b-instruct
OPENAI_COMPAT_API_KEY=your-nvidia-key
OPENAI_COMPAT_PATH=/chat/completions
```

The same section also works for other compatible services:

```dotenv
OPENAI_COMPAT_BASE_URL=https://your-compatible-endpoint.example/v1
OPENAI_COMPAT_MODEL=your-model-name
OPENAI_COMPAT_API_KEY=your-key-if-needed
OPENAI_COMPAT_PATH=/chat/completions
```

Notes:

- If the base URL already ends in `/chat/completions`, the backend uses it as-is.
- If the base URL ends in `/v1`, the backend appends `/chat/completions`.
- The provider name is generic on purpose so you are not locked to one vendor.
- `nvidia` and `openai_compat` are both supported provider labels for this path.

### Amazon Bedrock provider

Use this when you want a native Bedrock model path instead of an OpenAI-compatible proxy.

```dotenv
BEDROCK_MODEL=us.meta.llama4-scout-17b-instruct-v1:0
BEDROCK_INFERENCE_PROFILE=
BEDROCK_REGION=us-west-2
BEDROCK_API_KEY=your-bedrock-key-if-needed
AWS_BEARER_TOKEN_BEDROCK=your-bearer-token-if-needed
BEDROCK_BASE_URL=
```

Notes:

- The provider label is `bedrock`.
- Bedrock uses the Converse API path, not OpenAI-compatible chat completions.
- `BEDROCK_BASE_URL` is optional and only needed if you are pointing at a custom Bedrock-compatible gateway.
- For Llama 4 Scout on Bedrock, prefer an inference profile ID such as `us.meta.llama4-scout-17b-instruct-v1:0` rather than the raw model ID.
- `BEDROCK_INFERENCE_PROFILE` is optional if you want to separate the profile ID from `BEDROCK_MODEL`; either field can carry the inference profile.
- `BEDROCK_API_KEY` or `AWS_BEARER_TOKEN_BEDROCK` can be used depending on how your Bedrock access is configured.

### Optional OpenAI fallback

If you want a paid fallback path:

```dotenv
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=gpt-5.1
OPENAI_BASE_URL=https://api.openai.com/v1/responses
```

Leave `OPENAI_API_KEY` empty if you do not want API billing.

## Provider Routing

The backend tries providers in this order unless you override it per request:

1. Ollama
2. OpenAI-compatible endpoint
3. Bedrock
4. OpenAI API
5. deterministic fallback cutter

### Force a provider per request

```json
{
  "provider": "ollama"
}
```

Supported provider values:

- `ollama`
- `local`
- `chatgpt_bridge`
- `chatgpt_subscription`
- `openai_compat`
- `bedrock`
- `remote`
- `nvidia`
- `openai`
- `api`
- `fallback`

There is also an optional `LOCAL_MODEL_PROVIDER=ollama` env var that pins the auto-detection path toward Ollama.

If you want a hosted OpenAI-compatible path, `OPENAI_COMPAT_BASE_URL` can point at a compatible service such as NVIDIA's API gateway.

## Frontend How-To

### Research from a draft tag

1. Enter a draft tag.
2. Optionally add resolution, side, emphasis, or a source URL.
3. Choose `Semantic search` or `Literal search`.
4. Click `Research from tag`.
5. The frontend calls `POST /api/research`.
6. The backend returns the query pack, search mode, source candidates, selected source, full source URLs, credibility scores, paper verification fields, and extracted article text.
7. The frontend prefills the source fields and article text box.
8. Click `Cut card`.

### Cut from pasted text

1. Paste the article or evidence block.
2. Fill in any source metadata you already know.
3. Click `Cut card`.
4. The card is saved into the session library automatically.

### Queue multiple draft tags

1. Paste one draft tag per line into the `Queued draft tags` box.
2. Click `Run queue`.
3. The frontend updates per-tag queue status while each tag is processed.
4. Each completed card appears on the main stage and in the session library.

### Download a `.verbatim.docx`

1. Cut one or more cards so they appear in the session library.
2. Click `Download .docx`.
3. The frontend calls `POST /api/export/docx`.
4. The backend returns a `.verbatim.docx` file.
5. The exported file uses a Heading4-style tag line, a one-line cite, and an evidence paragraph with underlined and highlighted spans when exact matching is possible.
6. Citations are included in the downloaded document, including the full source URL in the cite line.

### Manual ChatGPT workflow

1. Switch to `ChatGPT manual`.
2. Fill in the draft tag and resolution.
3. Copy the generated prompt.
4. Paste it into ChatGPT.
5. Paste the returned JSON into the import box.
6. Click `Render import`.

## API Contract

### `POST /api/research`

Purpose:

- search for likely source material
- fetch and extract article text
- select the strongest source candidate

Accepted inputs:

- `draft_tag`
- `resolution`
- `side`
- `emphasis`
- `semantic_search_enabled`
- `source_url`
- `domain_blacklist`
- `source_title`
- `source_author`
- `source_date`
- `source_publication`
- `author_qualifications`

Example:

```json
{
  "draft_tag": "AI regulation reduces catastrophic misuse risk",
  "resolution": "Resolved: The United States should regulate frontier AI",
  "side": "affirmative",
  "emphasis": "misuse risk"
}
```

The response shape is:

- `ok`
- `research`

The `research` object includes:

- `used`
- `query`
- `search_mode`
- `query_pack`
- `query_refinement_used`
- `query_refinement_provider`
- `executed_queries`
- `sources`
- `selected`
- `article_text`
- `blocked_domains`
- `error` when research fails

Each source packet includes:

- `source_id`
- `title`
- `url`
- `source_class`
- `paper_verified`
- `paper_confidence`
- `doi`
- `pdf_url`
- `paper_signals`
- `summary_signals`
- `credibility_score`
- `credibility_notes`
- `overall_score`
- `snippet`

### `POST /api/cut`

Purpose:

- cut debate cards from pasted evidence or researched source text

Accepted inputs:

- `draft_tag`
- `article_text`
- `resolution`
- `side`
- `semantic_search_enabled`
- `source_title`
- `source_author`
- `source_date`
- `source_publication`
- `source_url`
- `domain_blacklist`
- `desired_cards`
- `emphasis`
- `provider`

Example:

```json
{
  "draft_tag": "AI regulation reduces catastrophic misuse risk",
  "resolution": "Resolved: The United States should regulate frontier AI",
  "side": "affirmative",
  "desired_cards": 1,
  "emphasis": "misuse risk",
  "provider": "ollama"
}
```

The response shape is:

- `ok`
- `cards`
- `meta`

The `meta` object includes:

- `mode`
- `provider`
- `used_ai`
- `fallback_used`
- `fallback_reason` when applicable
- `search_exhausted` when source retries ran out of usable candidates
- `quality` with:
  - `delivery_gate_passed`
  - `quality_gate_passed`
  - `tier`
  - `failures`
- `card_count`
- `validation`
- `validation_completed`
- `validation_separate_call`
- `research`
- the normalized source metadata used for the cut
- `blocked_domains`
- `search_mode`
- `query_pack`
- `query_refinement_used`
- `query_refinement_provider`
- `executed_queries`

### Reliability Suite

Run the checked-in live suite with:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
py -3 scripts/reliability_suite.py --openai-compat-timeout 60
```

The suite reports both:

- delivery success: the API returned a usable card response
- quality success: the response passed the stricter `meta.quality.quality_gate_passed` gate

### `POST /api/queue`

Purpose:

- run the normal research -> cut -> validate pipeline for multiple draft tags

Accepted inputs:

- every normal `POST /api/cut` field
- `draft_tags` as a list or newline-separated queue

Example:

```json
{
  "draft_tags": [
    "Tariffs raise manufacturing costs",
    "Trade wars escalate great power rivalry"
  ],
  "resolution": "Resolved: The United States should increase tariffs",
  "side": "negative",
  "provider": "nvidia"
}
```

The response shape is:

- `ok`
- `results`
- `cards`
- `meta`

### `POST /api/export/docx`

Purpose:

- export saved or generated cards as a debate-style `.verbatim.docx`

Accepted inputs:

- `title`
- `cards`

Example:

```json
{
  "title": "Tariff Neg",
  "cards": [
    {
      "tag_line": "Tariffs raise input costs",
      "cite_line": "Yap 25 [full cite] //IT",
      "full_context": "In the new world order, tariffs have become a key battleground...",
      "underlined_spans": [
        { "start": 0, "end": 9 }
      ],
      "highlighted_spans": [
        { "start": 0, "end": 9 }
      ]
    }
  ]
}
```

The response is a downloadable `.docx` binary, not JSON.

## Example Response

```json
{
  "ok": true,
  "cards": [
    {
      "tag_line": "Regulation lowers catastrophic misuse risk",
      "short_citation": "Smith 25",
      "full_citation": "[Jane Smith, 2025, Policy Journal, https://example.com/article, DOA:04-08-2026]",
      "cite_line": "Smith 25 [Jane Smith, 2025, Policy Journal, https://example.com/article, DOA:04-08-2026] //IT",
      "verbal_citation": "According to Jane Smith of Policy Journal...",
      "author_qualifications": "Director of AI Policy, Example Institute",
      "underlined_spans": [
        { "start": 0, "end": 18 }
      ],
      "highlighted_spans": [
        { "start": 0, "end": 18 }
      ],
      "full_context": "Larger context paragraph around the quote",
      "formatted_card": "Regulation lowers catastrophic misuse risk\\nSmith 25 [Jane Smith, 2025, Policy Journal, https://example.com/article, DOA:04-08-2026] //IT\\n\\nLarger context paragraph around the quote, including [[Quoted evidence block]].",
      "validation": {
        "passed": true,
        "useful": true,
        "revised": false,
        "issues": [],
        "notes": "No changes needed after validation.",
        "source_checks": [
          "Quote matches the selected article",
          "Card is useful for the debate round"
        ]
      },
      "date_accessed": "04-08-2026",
      "source_url": "https://example.com/article",
      "claim": "Rules reduce misuse risk before deployment.",
      "warrant": "This card proves the plan prevents misuse because...",
      "impact": "That matters because catastrophic misuse scales quickly.",
      "source": {
        "title": "Policy Journal",
        "author": "Jane Smith",
        "author_qualifications": "Director of AI Policy, Example Institute",
        "date": "2025",
        "publication": "Policy Journal",
        "url": "https://example.com/article",
        "source_id": "S1",
        "credibility_score": 0.86
      }
    }
  ],
  "meta": {
    "mode": "ai",
    "provider": "ollama",
    "card_count": 1,
    "validation": {
      "passed": true,
      "useful": true,
      "issues": [],
      "notes": "Final card kept after recursive validation."
    },
    "research": {
      "used": true,
      "query": "AI regulation reduces catastrophic misuse risk Resolved: The United States should regulate frontier AI",
      "selected": {
        "title": "Example Article",
        "url": "https://example.com/article",
        "source_id": "S1"
      }
    }
  }
}
```

## Environment Variables

### Core server

- `PORT=8000`

### Ollama

- `OLLAMA_BASE_URL=http://localhost:11434`
- `OLLAMA_MODEL=llama3.1`
- `OLLAMA_TIMEOUT=120`

Set these when you want local inference or a remote Ollama box.

### Optional provider pinning

- `LOCAL_MODEL_PROVIDER=ollama`

Use this when you want to steer auto-detection toward Ollama.

### OpenAI-compatible provider

- `OPENAI_COMPAT_BASE_URL=`
- `OPENAI_COMPAT_MODEL=`
- `OPENAI_COMPAT_API_KEY=`
- `OPENAI_COMPAT_PATH=/chat/completions`

Use this for remote chat-completions style endpoints, including vendor-hosted services and compatible gateways.

### Optional OpenAI provider

- `OPENAI_API_KEY=`
- `OPENAI_MODEL=gpt-5.1`
- `OPENAI_BASE_URL=https://api.openai.com/v1/responses`

This is the optional paid fallback. Leave it empty if you want no API billing.

### Research controls

- `SEARCH_ENGINE=duckduckgo`
- `SEARCH_RESULTS=50`
- `SEARCH_TIMEOUT=20`
- `FETCH_TIMEOUT=20`
- `FETCH_MAX_BYTES=1500000`
- `MODEL_INPUT_MAX_CHARS=24000`
- `MODEL_OUTPUT_TOKENS=3500`
- `USER_AGENT=...`
- `BLOCKED_DOMAINS=example.com,reddit.com`

These tune the search scrape, fetch timeout, how much text gets passed into and returned from the model, and which domains get filtered out.

## What The Backend Actually Does

The backend uses only built-in Python tooling:

- HTML scraping from public search result pages
- article fetching with `urllib`
- visible-text extraction with `html.parser`
- heuristic scoring of candidate sources against the draft tag
- source credibility scoring and domain filtering
- provider routing between local, remote-compatible, and fallback cutters
- cite assembly from source metadata into short, full, and verbal forms
- card normalization that keeps both the debate-native fields and the legacy compatibility fields

That keeps the app dependency-light, but it also means extraction quality is heuristic rather than perfect.

## Troubleshooting

### Research finds bad sources

- make the draft tag more specific
- add resolution context
- add emphasis terms
- provide a direct `source_url` if you already know the article
- add a `domain_blacklist` to exclude bad sites

### The model returns bad JSON

- use a stronger instruction-tuned model
- point the endpoint at a model that follows JSON better
- use the manual ChatGPT workflow if you want a human-in-the-loop pass

### Ollama does not respond

1. Verify the model exists:

```powershell
ollama list
```

2. Verify the host is reachable.
3. Verify `OLLAMA_BASE_URL`.
4. Verify `OLLAMA_MODEL`.

### The OpenAI-compatible provider fails

- check whether the provider expects `/v1/chat/completions`
- check whether `OPENAI_COMPAT_BASE_URL` is correct
- check whether the model name is valid for that provider
- check whether the provider requires a bearer token

### Search works but the extracted article text is poor

- some pages hide content behind client-side rendering
- some sites aggressively block scraping
- use a direct source URL from a cleaner site
- paste the source text manually if needed

### The cite line looks thin

- supply `source_publication` or `author_qualifications` if you know them
- the backend preserves the metadata you provide
- if the source page exposes better metadata, the research step can populate it automatically

## Limitations

- Search scraping is brittle because result page HTML can change.
- Some sites block fetches or do not expose useful raw HTML text.
- The extractor is not a full readability engine.
- A weak local or remote model will still produce weak cards.
- The fallback cutter is a last resort, not a substitute for strong evidence cutting.
- Plain JSON cannot fully preserve Word-style underline or highlight formatting, so the backend represents that information with explicit span fields that the UI and exporter render.

## Suggested Next Improvements

- let the UI choose among multiple researched sources before cutting
- add domain allowlists in addition to blocklists
- support PDF extraction
- support export into Word-friendly debate file formats
- add richer highlighting and source comparison views
