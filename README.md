# AI Debate Card Cutter

Debate evidence cutter with a static frontend, a Python stdlib backend, draft-tag source discovery, one-card iterative cutting, local or remote model support, manual ChatGPT copy/paste support, and a deterministic fallback when no model is available.

## What This Is For

The app is built around a debate workflow, not a generic chat workflow:

1. Start with a rough draft tag.
2. Research likely source material from that tag.
3. Fetch and extract the article text.
4. Cut one debate-style card.
5. Validate and revise the card if needed.
6. Copy the result into a debate file.

You can also skip research and paste evidence directly.

## What A Debate Card Looks Like

The backend returns a debate-native shape that mirrors the structure in your sample `.docx` files:

- `tag_line`: the headline or claim at the top of the card
- `short_citation`: the compact cite, usually `Surname YY`
- `full_citation`: the longer source cite with source details and date accessed
- `cite_line`: the assembled cite line, usually `Shortcite [full cite] //IT`
- `verbal_citation`: the cite phrasing you can read in-round
- `author_qualifications`: author credential text when available
- `read_text`: the exact sentence or passage you would read
- `full_context`: the surrounding paragraph or context
- `quoted_text` / `exact_excerpt`: aliases for the quoted passage
- `highlighted_text`: the portion the card should emphasize
- `formatted_card`: a plain-text rendering of the whole card
- `validation`: the recursive usefulness check and revision notes
- `source_url`: the source location
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

### Example Card Layout

```text
Tariffs raise input costs for domestic manufacturing
Smith 25 [Jane Smith, 2025, Policy Journal, https://example.com/article, DOA:04-08-2026] //IT
Verbal cite: According to Jane Smith of Policy Journal...

Read text: Tariffs raise the cost of imported components, which increases production costs across the sector.

Full context: In the larger paragraph, Smith explains that higher input costs reduce margins, slow expansion, and weaken competitiveness.
```

## Research Basis

The current card format is based on three things:

1. Your sample `.docx` files, which consistently follow the pattern `tag line -> cite line -> evidence paragraph`.
2. Debate cite guidance that favors predictable, one-line citation structure.
3. Evidence practice that distinguishes the tag, the source cite, the oral cite, and the exact read text.

That is why the app separates `tag_line`, `short_citation`, `full_citation`, `cite_line`, `verbal_citation`, `read_text`, and `full_context` instead of collapsing everything into one block.

## How The Cite Is Built

The backend assembles cites in layers:

1. `short_citation` comes from the author surname and a two-digit year.
2. `full_citation` combines the author, date, title, publication or outlet, source URL, and date accessed.
3. `cite_line` joins the short cite with the full cite and adds the `//IT` marker.
4. `verbal_citation` is the oral version and prefers the author plus qualifications.
5. `read_text` and `full_context` are split so the UI can show the exact quote separately from the surrounding paragraph.

If a field is missing, the backend keeps what it can and leaves the rest blank instead of inventing details.

## Recursive Validation

The current workflow is intentionally iterative and single-card:

1. Research the source from a draft tag or source URL.
2. Cut one candidate card.
3. Validate that card against the source for factual fidelity, usefulness, and debate value.
4. Revise the card if the validation pass finds a weakness.
5. Keep only the final card.

The manual ChatGPT workflow follows the same shape. The prompt asks for a draft card, a validation pass, and a final revised card in one JSON response. That keeps the human workflow aligned with the backend workflow instead of drifting into a generic chat transcript.

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
- let an AI-capable provider rank the candidate pool before cutting
- retry alternate sources when validation says the first cut is weak
- cut one card from the chosen article
- run a validation pass on that card before returning it

### 2. Cut from pasted source text

Use this when you already have the article, PDF excerpt, or evidence block.

### 3. Cut from a direct URL

Use this when you know the exact article and want to bypass search.

### 4. Manual ChatGPT workflow

Use this when you have a ChatGPT subscription but do not want API billing.

The frontend generates a strict JSON prompt. You paste that prompt into ChatGPT, then paste the returned JSON back into the app. The prompt now asks for one card plus a validation/revision pass.

### 5. Remote model hosting

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

### OpenAI-compatible hosted endpoints

Use this for hosted inference servers that expose an OpenAI-style chat endpoint.

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
3. OpenAI API
4. deterministic fallback cutter

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
- `remote`
- `nvidia`
- `openai`
- `api`
- `fallback`

There is also an optional `LOCAL_MODEL_PROVIDER=ollama` env var that pins the auto-detection path toward Ollama.

## Frontend How-To

### Research from a draft tag

1. Enter a draft tag.
2. Optionally add resolution, side, emphasis, or a source URL.
3. Click `Research from tag`.
4. The frontend calls `POST /api/research`.
5. The backend returns the query, source candidates, selected source, and extracted article text.
6. The frontend prefills the source fields and article text box.
7. Click `Cut card`.

### Cut from pasted text

1. Paste the article or evidence block.
2. Fill in any source metadata you already know.
3. Click `Cut card`.

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
- `source_url`
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
- `sources`
- `selected`
- `article_text`
- `error` when research fails

### `POST /api/cut`

Purpose:

- cut debate cards from pasted evidence or researched source text

Accepted inputs:

- `draft_tag`
- `article_text`
- `resolution`
- `side`
- `source_title`
- `source_author`
- `source_date`
- `source_publication`
- `source_url`
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
- `card_count`
- `validation` when the cut path returns recursive review metadata
- `research`
- the normalized source metadata used for the cut

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
      "read_text": "Quoted evidence block",
      "full_context": "Larger context paragraph around the quote",
      "quoted_text": "Quoted evidence block",
      "exact_excerpt": "Quoted evidence block",
      "highlighted_text": "The most quotable line",
      "formatted_card": "Regulation lowers catastrophic misuse risk\\nSmith 25 [Jane Smith, 2025, Policy Journal, https://example.com/article, DOA:04-08-2026] //IT\\n\\nRead text: Quoted evidence block\\n\\nFull context: Larger context paragraph around the quote",
      "validation": {
        "passed": true,
        "useful": true,
        "issues": [],
        "revision_notes": "No changes needed after validation.",
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
      "title": "Regulation lowers catastrophic misuse risk",
      "tag": "Regulation lowers catastrophic misuse risk",
      "citation": "[Jane Smith, 2025, Policy Journal, https://example.com/article, DOA:04-08-2026]",
      "card_text": "Quoted evidence block",
      "body": "Larger context paragraph around the quote",
      "evidence": "Quoted evidence block",
      "source": {
        "title": "Policy Journal",
        "author": "Jane Smith",
        "author_qualifications": "Director of AI Policy, Example Institute",
        "date": "2025",
        "publication": "Policy Journal",
        "url": "https://example.com/article"
      },
      "excerpt": "Quoted evidence block",
      "highlighted_excerpt": "The most quotable line"
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
      "revision_notes": "Final card kept after recursive validation."
    },
    "research": {
      "used": true,
      "query": "AI regulation reduces catastrophic misuse risk Resolved: The United States should regulate frontier AI",
      "selected": {
        "title": "Example Article",
        "url": "https://example.com/article"
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
- `SEARCH_RESULTS=5`
- `SEARCH_TIMEOUT=20`
- `FETCH_TIMEOUT=20`
- `FETCH_MAX_BYTES=1500000`
- `MODEL_INPUT_MAX_CHARS=24000`
- `USER_AGENT=...`

These tune the search scrape, fetch timeout, and how much text gets passed into the model.

## What The Backend Actually Does

The backend uses only built-in Python tooling:

- HTML scraping from public search result pages
- article fetching with `urllib`
- visible-text extraction with `html.parser`
- heuristic scoring of candidate sources against the draft tag
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
- Plain JSON cannot fully preserve Word-style underline or highlight formatting, so the backend represents that information as `read_text` and `highlighted_text`.

## Suggested Next Improvements

- let the UI choose among multiple researched sources before cutting
- add domain allowlists and blocklists
- support PDF extraction
- support export into Word-friendly debate file formats
- add richer highlighting and source comparison views
