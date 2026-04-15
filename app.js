const form = document.getElementById('cut-form');
const submitBtn = document.getElementById('submit-btn');
const copyAllBtn = document.getElementById('copy-all-btn');
const modeLocalBtn = document.getElementById('mode-local');
const modeChatgptBtn = document.getElementById('mode-chatgpt');
const researchBtn = document.getElementById('research-btn');
const chatgptPanel = document.getElementById('chatgpt-panel');
const promptPreviewEl = document.getElementById('prompt-preview');
const copyPromptBtn = document.getElementById('copy-prompt-btn');
const queryPreviewEl = document.getElementById('query-preview');
const searchModeSemanticBtn = document.getElementById('search-mode-semantic');
const searchModeLiteralBtn = document.getElementById('search-mode-literal');
const renderImportBtn = document.getElementById('render-import-btn');
const importJsonEl = document.getElementById('import-json');
const sourceSummaryEl = document.getElementById('source-summary');
const statusEl = document.getElementById('status');
const metaEl = document.getElementById('meta');
const cardsEl = document.getElementById('cards');
const hintEl = document.getElementById('output-hint');
const template = document.getElementById('card-template');
const savedCardsListEl = document.getElementById('saved-cards-list');
const queueTagsEl = document.getElementById('queue-tags');
const queueAddBtn = document.getElementById('queue-add-btn');
const queueRunBtn = document.getElementById('queue-run-btn');
const queueProgressEl = document.getElementById('queue-progress');
const downloadDocxBtn = document.getElementById('download-docx-btn');
const downloadTextBtn = document.getElementById('download-text-btn');
const sourceCandidatesEl = document.getElementById('source-candidates');
const runtimeBadgesEl = document.getElementById('runtime-badges');
const runtimeDetailsEl = document.getElementById('runtime-details');
const runtimeErrorEl = document.getElementById('runtime-error');

const LIBRARY_STORAGE_KEY = 'debate-card-cutter-library-v2';
const QUEUE_PARALLELISM = 3;

const fields = {
  draftTag: document.getElementById('draft-tag'),
  resolution: document.getElementById('resolution'),
  side: document.getElementById('side'),
  sourceText: document.getElementById('source-text'),
  sourceTitle: document.getElementById('source-title'),
  sourceAuthor: document.getElementById('source-author'),
  sourceDate: document.getElementById('source-date'),
  sourceUrl: document.getElementById('source-url'),
  blockedDomains: document.getElementById('blocked-domains'),
  emphasis: document.getElementById('emphasis'),
};

let currentCards = [];
let currentMode = 'local';
let semanticSearchEnabled = true;
let savedCards = loadSavedCards();
let runtimeState = {
  action: 'Idle',
  stage: 'Ready',
  provider: '',
  model: '',
  retryCount: 0,
  requestId: '',
  sourceAttempts: 0,
  validationProvider: '',
  error: '',
  providerErrors: [],
  httpStatus: '',
};

function setStatus(message, kind = '') {
  statusEl.textContent = message;
  statusEl.className = `status${kind ? ` is-${kind}` : ''}`;
}

function setBusy(isBusy) {
  submitBtn.disabled = isBusy;
  submitBtn.classList.toggle('is-loading', isBusy);
  copyAllBtn.disabled = isBusy || currentCards.length === 0;
  form.querySelectorAll('input, select, textarea, button').forEach((control) => {
    control.disabled = isBusy;
  });
  if (queueAddBtn) {
    queueAddBtn.disabled = isBusy;
  }
  if (queueRunBtn) {
    queueRunBtn.disabled = isBusy;
  }
  if (queueTagsEl) {
    queueTagsEl.disabled = isBusy;
  }
  if (downloadDocxBtn) {
    downloadDocxBtn.disabled = isBusy || savedCards.length === 0;
  }
  if (downloadTextBtn) {
    downloadTextBtn.disabled = isBusy || savedCards.length === 0;
  }
}

function clearRuntimeStatus() {
  runtimeState = {
    action: 'Idle',
    stage: 'Ready',
    provider: '',
    model: '',
    retryCount: 0,
    requestId: '',
    sourceAttempts: 0,
    validationProvider: '',
    error: '',
    providerErrors: [],
    httpStatus: '',
  };
  renderRuntimeStatus();
}

function setRuntimeStatus(patch = {}) {
  runtimeState = {
    ...runtimeState,
    ...patch,
    providerErrors: Array.isArray(patch.providerErrors)
      ? patch.providerErrors.filter(Boolean)
      : runtimeState.providerErrors,
  };
  renderRuntimeStatus();
}

function renderRuntimeStatus() {
  if (!runtimeBadgesEl || !runtimeDetailsEl || !runtimeErrorEl) {
    return;
  }

  runtimeBadgesEl.replaceChildren();
  runtimeDetailsEl.replaceChildren();
  runtimeErrorEl.textContent = '';
  runtimeErrorEl.classList.toggle('is-visible', false);

  const badgeSpecs = [
    ['Task', runtimeState.action],
    ['Step', runtimeState.stage],
    ['Tries', runtimeState.retryCount ? `x${runtimeState.retryCount}` : 'none'],
  ];
  badgeSpecs.forEach(([label, value]) => {
    const cleaned = normalizeText(value);
    if (!cleaned) {
      return;
    }
    const chip = document.createElement('span');
    chip.className = 'runtime-chip';
    chip.textContent = `${label}: ${cleaned}`;
    runtimeBadgesEl.appendChild(chip);
  });

  const details = [
    runtimeState.sourceAttempts ? `Sources checked: ${runtimeState.sourceAttempts}` : '',
    runtimeState.httpStatus && !normalizeText(runtimeState.error) ? `Status: ${runtimeState.httpStatus}` : '',
  ].filter(Boolean);

  details.forEach((line) => {
    const row = document.createElement('div');
    row.className = 'runtime-detail';
    row.textContent = line;
    runtimeDetailsEl.appendChild(row);
  });

  const issueParts = [
    normalizeText(runtimeState.error),
    ...toArray(runtimeState.providerErrors).map((item) => normalizeText(item)).filter(Boolean),
  ].filter(Boolean);

  if (issueParts.length) {
    runtimeErrorEl.textContent = issueParts.join(' | ');
    runtimeErrorEl.classList.toggle('is-visible', true);
  }
}

function setSearchMode(enabled) {
  semanticSearchEnabled = !!enabled;
  if (searchModeSemanticBtn) {
    searchModeSemanticBtn.classList.toggle('is-active', semanticSearchEnabled);
    searchModeSemanticBtn.setAttribute('aria-pressed', String(semanticSearchEnabled));
  }
  if (searchModeLiteralBtn) {
    searchModeLiteralBtn.classList.toggle('is-active', !semanticSearchEnabled);
    searchModeLiteralBtn.setAttribute('aria-pressed', String(!semanticSearchEnabled));
  }
}

function getSearchModeLabel() {
  return semanticSearchEnabled ? 'Meaning match' : 'Exact wording';
}

function setMode(nextMode) {
  currentMode = nextMode;
  const isChatgpt = nextMode === 'chatgpt';

  modeLocalBtn.classList.toggle('is-active', !isChatgpt);
  modeChatgptBtn.classList.toggle('is-active', isChatgpt);
  modeLocalBtn.setAttribute('aria-selected', String(!isChatgpt));
  modeChatgptBtn.setAttribute('aria-selected', String(isChatgpt));
  chatgptPanel.classList.toggle('is-hidden', !isChatgpt);
  chatgptPanel.setAttribute('aria-hidden', String(!isChatgpt));
  submitBtn.querySelector('.button-label').textContent = isChatgpt ? 'Build card' : 'Cut card';

  if (isChatgpt) {
    metaEl.textContent = 'ChatGPT handoff is ready.';
  } else if (!currentCards.length) {
    metaEl.textContent = '';
  }
}

function normalizeText(value) {
  return String(value ?? '').trim();
}

function describeApiError(data, status, fallbackLabel = 'Request failed') {
  const requestId = normalizeText(data?.request_id ?? data?.requestId);
  const message = typeof data === 'string'
    ? data
    : data?.error?.message
      ?? data?.error
      ?? data?.message
      ?? `${fallbackLabel} with status ${status}.`;
  return requestId ? `${message} [request ${requestId}]` : message;
}

function readJsonResponse(rawText) {
  if (!rawText) {
    return null;
  }
  try {
    return JSON.parse(rawText);
  } catch {
    return rawText;
  }
}

function extractRuntimeSnapshot(endpoint, response, data, action = '') {
  const research = data?.research && typeof data.research === 'object' ? data.research : null;
  const meta = data?.meta && typeof data.meta === 'object' ? data.meta : {};
  const retryCount = Number(meta.json_retry_count ?? 0) + Number(meta.validation_retry_count ?? 0);
  return {
    action: action || (endpoint === '/api/research' ? 'Research' : endpoint === '/api/cut' ? 'Cut' : 'Request'),
    stage: response.ok ? (endpoint === '/api/research' ? 'Completed' : endpoint === '/api/cut' ? 'Completed' : 'Completed') : 'Failed',
    provider: normalizeText(meta.provider ?? meta.validation_provider ?? research?.query_refinement_provider),
    model: normalizeText(meta.model),
    retryCount: Number.isFinite(retryCount) ? retryCount : 0,
    requestId: normalizeText(data?.request_id ?? data?.requestId),
    sourceAttempts: Number(meta.source_attempts ?? 0) || 0,
    validationProvider: normalizeText(meta.validation_provider),
    providerErrors: toArray(meta.provider_errors).map(normalizeText).filter(Boolean),
    httpStatus: String(response.status || ''),
    error: response.ok ? '' : describeApiError(data, response.status),
  };
}

async function postJson(endpoint, payload, runtimePatch = {}) {
  if (runtimePatch.action || runtimePatch.stage) {
    setRuntimeStatus({
      action: runtimePatch.action || runtimeState.action,
      stage: runtimePatch.stage || 'Sending request',
      provider: '',
      model: '',
      retryCount: 0,
      requestId: '',
      sourceAttempts: 0,
      validationProvider: '',
      error: '',
      providerErrors: [],
      httpStatus: '',
    });
  }

  const response = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  const rawText = await response.text();
  const data = readJsonResponse(rawText);
  setRuntimeStatus(extractRuntimeSnapshot(endpoint, response, data, runtimePatch.action));

  if (!response.ok) {
    const error = new Error(describeApiError(data, response.status));
    error.responseData = data;
    error.status = response.status;
    throw error;
  }

  return { response, data, rawText };
}

function formatScore(value, digits = 3) {
  const numeric = typeof value === 'number' ? value : Number.parseFloat(normalizeText(value));
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : '';
}

function ensureBracketedCitation(text) {
  const cleaned = normalizeText(text);
  if (!cleaned) {
    return '';
  }
  if (cleaned.startsWith('[') && cleaned.endsWith(']')) {
    return cleaned;
  }
  return `[${cleaned}]`;
}

function normalizeValidation(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }

  const issues = toArray(value.issues ?? value.problems ?? value.concerns)
    .map(normalizeText)
    .filter(Boolean);
  const sourceChecks = toArray(value.source_checks ?? value.sourceChecks ?? value.checks)
    .map(normalizeText)
    .filter(Boolean);
  const notes = normalizeText(value.notes ?? value.revision_notes ?? value.revisionNotes ?? value.summary ?? value.feedback);
  const normalized = {
    useful: typeof value.useful === 'boolean' ? value.useful : null,
    revised: typeof value.revised === 'boolean' ? value.revised : null,
    passed: typeof value.passed === 'boolean' ? value.passed : null,
    notes,
    issues,
    sourceChecks,
    tagFit: normalizeText(value.tag_fit ?? value.tagFit),
    spanGrounding: normalizeText(value.span_grounding ?? value.spanGrounding),
    sourceChoice: normalizeText(value.source_choice ?? value.sourceChoice),
  };

  if (
    normalized.useful === null
    && normalized.revised === null
    && normalized.passed === null
    && !normalized.notes
    && !normalized.tagFit
    && !normalized.spanGrounding
    && !normalized.sourceChoice
    && normalized.issues.length === 0
    && normalized.sourceChecks.length === 0
  ) {
    return null;
  }

  return normalized;
}

function buildValidationText(validation) {
  if (!validation) {
    return '';
  }

  const lines = [
    validation.useful === null ? '' : `Useful: ${validation.useful ? 'yes' : 'no'}`,
    validation.revised === null ? '' : `Revised: ${validation.revised ? 'yes' : 'no'}`,
    validation.passed === null ? '' : `Passed: ${validation.passed ? 'yes' : 'no'}`,
    validation.notes ? `Notes: ${validation.notes}` : '',
    validation.tagFit ? `Tag fit: ${validation.tagFit}` : '',
    validation.spanGrounding ? `Span grounding: ${validation.spanGrounding}` : '',
    validation.sourceChoice ? `Source choice: ${validation.sourceChoice}` : '',
    validation.issues.length ? `Issues: ${validation.issues.join('; ')}` : '',
    validation.sourceChecks.length ? `Source checks: ${validation.sourceChecks.join('; ')}` : '',
  ].filter(Boolean);

  return lines.join('\n');
}

function buildCiteLine(card) {
  const shortCitation = normalizeText(card.shortCitation);
  const fullCitation = ensureBracketedCitation(card.fullCitation || card.citation);
  const pieces = [shortCitation, fullCitation].filter(Boolean);
  if (!pieces.length) {
    return '';
  }
  return `${pieces.join(' ')} //IT`;
}

function annotateContextWithSpans(fullContext, underlinedSpans, highlightedSpans) {
  const context = normalizeText(fullContext);
  if (!context) {
    return joinSpanText(highlightedSpans) || joinSpanText(underlinedSpans);
  }

  const events = new Map();
  const addEvent = (index, marker) => {
    const existing = events.get(index) ?? [];
    existing.push(marker);
    events.set(index, existing);
  };

  toArray(underlinedSpans).forEach((span) => {
    if (Number.isInteger(span?.start) && Number.isInteger(span?.end) && span.start >= 0 && span.end > span.start) {
      addEvent(span.start, '__');
      addEvent(span.end, '__');
    }
  });
  toArray(highlightedSpans).forEach((span) => {
    if (Number.isInteger(span?.start) && Number.isInteger(span?.end) && span.start >= 0 && span.end > span.start) {
      addEvent(span.start, '[[');
      addEvent(span.end, ']]');
    }
  });

  const pieces = [];
  for (let index = 0; index < context.length; index += 1) {
    if (events.has(index)) {
      pieces.push(...events.get(index));
    }
    pieces.push(context[index]);
  }
  if (events.has(context.length)) {
    pieces.push(...events.get(context.length));
  }
  return pieces.join('').trim();
}

function buildFormattedCard(card) {
  const lines = [];

  if (card.tagLine || card.title) {
    lines.push(card.tagLine || card.title);
  }
  if (card.citeLine || card.shortCitation || card.fullCitation) {
    lines.push(card.citeLine || buildCiteLine(card));
  }
  if (card.fullContext || card.body || card.text) {
    lines.push('');
    lines.push(annotateContextWithSpans(card.fullContext || card.body || card.text, card.underlinedSpans, card.highlightedSpans));
  } else if (card.highlightedSpans?.length || card.underlinedSpans?.length) {
    lines.push('');
    lines.push(joinSpanText(card.highlightedSpans) || joinSpanText(card.underlinedSpans));
  }

  return lines.filter(Boolean).join('\n').trim();
}

function loadSavedCards() {
  try {
    const raw = window.localStorage.getItem(LIBRARY_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map((entry, index) => normalizeSavedCardEntry(entry, index)).filter(Boolean) : [];
  } catch {
    return [];
  }
}

function saveSavedCards() {
  try {
    window.localStorage.setItem(LIBRARY_STORAGE_KEY, JSON.stringify(savedCards));
  } catch {
    // Ignore storage failures.
  }
}

function normalizeSavedCardEntry(entry, index) {
  if (!entry || typeof entry !== 'object') {
    return null;
  }
  const normalizedCard = normalizeCard(entry.card ?? entry, index);
  if (!normalizedCard) {
    return null;
  }
  return {
    id: normalizeText(entry.id) || `card-${Date.now()}-${index}`,
    createdAt: normalizeText(entry.createdAt) || new Date().toISOString(),
    draftTag: normalizeText(entry.draftTag ?? entry.tag),
    meta: entry.meta && typeof entry.meta === 'object' ? entry.meta : {},
    card: normalizedCard,
  };
}

function createSavedCardEntry(card, meta = {}, draftTag = '') {
  return {
    id: `card-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    createdAt: new Date().toISOString(),
    draftTag: normalizeText(draftTag),
    meta,
    card,
  };
}

function renderEvidenceContent(card) {
  const wrapper = document.createElement('div');
  wrapper.className = 'evidence-block';

  const context = normalizeText(card.fullContext || card.body || card.text);
  const underlinedSpans = toArray(card.underlinedSpans);
  const highlightedSpans = toArray(card.highlightedSpans);
  const paragraph = document.createElement('p');

  if (!context && (highlightedSpans.length || underlinedSpans.length)) {
    paragraph.textContent = joinSpanText(highlightedSpans) || joinSpanText(underlinedSpans);
    paragraph.className = 'evidence-readonly';
    wrapper.appendChild(paragraph);
    return wrapper;
  }

  if (!context) {
    paragraph.textContent = 'No evidence paragraph returned.';
    wrapper.appendChild(paragraph);
    return wrapper;
  }

  const underlineMarks = new Array(context.length).fill(false);
  const highlightMarks = new Array(context.length).fill(false);
  let foundAny = false;

  underlinedSpans.forEach((span) => {
    if (Number.isInteger(span?.start) && Number.isInteger(span?.end)) {
      for (let index = span.start; index < span.end && index < context.length; index += 1) {
        underlineMarks[index] = true;
      }
      foundAny = true;
    }
  });

  highlightedSpans.forEach((span) => {
    if (Number.isInteger(span?.start) && Number.isInteger(span?.end)) {
      for (let index = span.start; index < span.end && index < context.length; index += 1) {
        underlineMarks[index] = true;
        highlightMarks[index] = true;
      }
      foundAny = true;
    }
  });

  if (!foundAny) {
    paragraph.textContent = context;
    wrapper.appendChild(paragraph);
    const fallbackText = joinSpanText(highlightedSpans) || joinSpanText(underlinedSpans);
    if (fallbackText && fallbackText !== context) {
      const fallback = document.createElement('p');
      fallback.className = 'evidence-read-fallback';
      fallback.textContent = fallbackText;
      wrapper.appendChild(fallback);
    }
    return wrapper;
  }

  let chunk = '';
  let currentState = null;
  const flushChunk = () => {
    if (!chunk) {
      return;
    }
    if (!currentState?.underline && !currentState?.highlight) {
      paragraph.appendChild(document.createTextNode(chunk));
    } else if (currentState.highlight) {
      const span = document.createElement('mark');
      span.className = 'evidence-highlight';
      span.textContent = chunk;
      paragraph.appendChild(span);
    } else {
      const span = document.createElement('span');
      span.className = 'evidence-read';
      span.textContent = chunk;
      paragraph.appendChild(span);
    }
    chunk = '';
  };

  for (let index = 0; index < context.length; index += 1) {
    const state = {
      underline: underlineMarks[index],
      highlight: highlightMarks[index],
    };
    if (!currentState) {
      currentState = state;
    }
    if (currentState.underline !== state.underline || currentState.highlight !== state.highlight) {
      flushChunk();
      currentState = state;
    }
    chunk += context[index];
  }
  flushChunk();

  wrapper.appendChild(paragraph);
  return wrapper;
}

function appendCardSection(container, label, value, className = '') {
  if (!value) {
    return;
  }
  const section = document.createElement('section');
  section.className = `card-section${className ? ` ${className}` : ''}`;
  const labelEl = document.createElement('div');
  labelEl.className = 'label';
  labelEl.textContent = label;
  section.appendChild(labelEl);

  if (value instanceof Node) {
    section.appendChild(value);
  } else {
    const valueEl = document.createElement('div');
    valueEl.className = 'highlight';
    valueEl.textContent = value;
    section.appendChild(valueEl);
  }
  container.appendChild(section);
}

function rememberCards(cards, meta = {}, draftTag = '') {
  const entries = cards.map((card) => createSavedCardEntry(card, meta, draftTag));
  savedCards = [...entries, ...savedCards].slice(0, 50);
  saveSavedCards();
  renderSavedCardsList();
}

function buildRequestBody() {
  return {
    draft_tag: normalizeText(fields.draftTag.value),
    article_text: normalizeText(fields.sourceText.value),
    resolution: normalizeText(fields.resolution.value),
    side: fields.side.value,
    source_title: normalizeText(fields.sourceTitle.value),
    source_author: normalizeText(fields.sourceAuthor.value),
    source_date: normalizeText(fields.sourceDate.value),
    source_url: normalizeText(fields.sourceUrl.value),
    domain_blacklist: parseDomainBlacklist(),
    semantic_search_enabled: semanticSearchEnabled,
    desired_cards: 1,
    emphasis: normalizeText(fields.emphasis.value),
  };
}

function parseDomainBlacklist() {
  return normalizeText(fields.blockedDomains?.value)
    .split(/[\s,;\r\n]+/)
    .map(normalizeText)
    .filter(Boolean);
}

function hasCompleteSourceInputs(payload) {
  return [
    payload.article_text,
    payload.source_title,
    payload.source_author,
    payload.source_date,
    payload.source_url,
  ].every((value) => normalizeText(value));
}

function buildChatgptPrompt() {
  const request = buildRequestBody();
  const lines = [
    'You are a debate evidence researcher and cutter.',
    'Return strict JSON only. Do not wrap the answer in markdown fences or commentary.',
    'Produce an object with a `cards` array containing exactly one card.',
    'This is the cut call only. Do not perform validation in this response.',
    'Each card must include:',
    '- tag_line',
    '- short_citation',
    '- full_citation',
    '- cite_line',
    '- verbal_citation',
    '- source_url',
    '- dox or date_of_access',
    '- author_qualifications',
    '- full_context',
    '- underlined_spans [{ text, start, end, reason }]',
    '- highlighted_spans [{ text, start, end, reason }]',
    '- warrant',
    '- impact',
    '- source { source_id, title, author, date, publication, url, credibility_score, credibility_notes }',
    '- claim if useful',
    '',
    'Condensed debate card guide:',
    '- Match the sample file pattern: Heading4-style tag line, one cite line, then one evidence paragraph.',
    '- Prefer cite format like `Shortcite [author, date, title, publication, URL/#IT, DOA:MM-DD-YYYY] //IT`.',
    '- Keep the whole evidence paragraph for context, usually several sentences or a short paragraph when the source supports it.',
    '- Underlines are every exact source substring that materially supports the argument: warrants, stats, causal links, comparisons, conclusions, and impact language.',
    '- Highlights are the exact bits actually read aloud in-round and should usually sit inside the underlined support.',
    '- Highlighted spans may be discontiguous and can jump phrase-to-phrase or sentence-to-sentence.',
    '- Reject filler, scene-setting, rhetoric, and unsupported summaries.',
    '',
    'Rules:',
    '- Cut exactly one card.',
    `- The debate side is ${request.side}.`,
    request.resolution ? `- The resolution is: ${request.resolution}.` : '- No resolution was supplied.',
    request.draft_tag ? `- The draft tag is: ${request.draft_tag}. Research likely sources from this tag before cutting.` : '- No draft tag was supplied.',
    request.emphasis ? `- Prioritize: ${request.emphasis}.` : '- No extra emphasis was supplied.',
    '- Use debate-card structure: tag line, short cite line, bracketed full citation, source URL, date of access, author qualifications, full context, underlined support, highlighted read portions, warrant, and impact.',
    '- Match common debate file layout: Heading 4 style tag, cite line, then evidence paragraph.',
    '- Build the cite line in the style `Shortcite [full citation, DOA:MM-DD-YYYY] //IT` when possible.',
    '- Prefer a direct quote with surrounding context when possible.',
    '- Do not create a freeform `read_text` field.',
    '- Every underline/highlight span must be copied exactly from `full_context` and include offsets when possible.',
    '- If you compare or research multiple sources, keep source usefulness separate from source credibility.',
    '- Determine what part of the source actually matters. Do not return filler or generic throat-clearing.',
    '- Keep the tag close to the draft tag. If the source only supports a narrower version, tighten the tag instead of broadening it.',
    '- Keep the quote faithful and preserve ellipses only when necessary.',
    '- If article text is missing, research likely source(s) from the draft tag before cutting.',
    '- Keep the card concise, contextualized, and reusable in a debate round.',
    '',
    'Input:',
    JSON.stringify(request, null, 2),
    '',
    'Output schema:',
    JSON.stringify({
      cards: [
        {
          tag_line: 'string',
          short_citation: 'string',
          full_citation: 'string',
          cite_line: 'string',
          verbal_citation: 'string',
          source_url: 'string',
          dox: 'string',
          author_qualifications: 'string',
          full_context: 'string',
          underlined_spans: [{ text: 'string', start: 0, end: 10, reason: 'string' }],
          highlighted_spans: [{ text: 'string', start: 0, end: 10, reason: 'string' }],
          formatted_card: 'string',
          warrant: 'string',
          impact: 'string',
          claim: 'string',
          title: 'string',
          tag: 'string',
          citation: 'string',
          shortCitation: 'string',
          card_text: 'string',
          body: 'string',
          evidence: 'string',
          highlighted_excerpt: 'string',
          source: {
            source_id: 'string',
            title: 'string',
            author: 'string',
            date: 'string',
            publication: 'string',
            url: 'string',
            credibility_score: 0.0,
            credibility_notes: 'string',
          },
          excerpt: 'string',
        },
      ],
    }, null, 2),
  ];

  return lines.join('\n');
}

function toArray(value) {
  if (!value) {
    return [];
  }
  return Array.isArray(value) ? value : [value];
}

function stripCodeFences(text) {
  return String(text ?? '')
    .trim()
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```$/i, '');
}

function parseJsonLike(text) {
  const cleaned = stripCodeFences(text);
  try {
    return JSON.parse(cleaned);
  } catch {
    const firstBrace = cleaned.indexOf('{');
    const firstBracket = cleaned.indexOf('[');
    const start = [firstBrace, firstBracket].filter((index) => index >= 0).sort((a, b) => a - b)[0];
    if (start === undefined) {
      throw new Error('Could not find a usable result in the pasted text.');
    }

    const end = Math.max(cleaned.lastIndexOf('}'), cleaned.lastIndexOf(']'));
    if (end <= start) {
      throw new Error('Could not find a complete result in the pasted text.');
    }

    return JSON.parse(cleaned.slice(start, end + 1));
  }
}

function normalizeSpans(value, fullContext) {
  const spans = Array.isArray(value) ? value : [];
  const context = normalizeText(fullContext);
  let cursor = 0;

  return spans.map((span) => {
    if (typeof span === 'string') {
      span = { text: span };
    }
    if (!span || typeof span !== 'object') {
      return null;
    }
    const text = normalizeText(span.text ?? span.quote ?? span.value);
    if (!text) {
      return null;
    }

    let start = Number.isInteger(span.start) ? span.start : -1;
    let end = Number.isInteger(span.end) ? span.end : -1;

    if (context) {
      if (!(start >= 0 && end > start && context.slice(start, end) === text)) {
        start = context.indexOf(text, Math.max(0, cursor));
        if (start < 0) {
          start = context.indexOf(text);
        }
        end = start >= 0 ? start + text.length : -1;
      }
    }

    if (start >= 0 && end > start) {
      cursor = end;
    }

    return {
      text,
      start: start >= 0 ? start : null,
      end: end > start ? end : null,
      reason: normalizeText(span.reason),
    };
  }).filter(Boolean);
}

function joinSpanText(spans) {
  return toArray(spans).map((span) => normalizeText(span?.text ?? span)).filter(Boolean).join(' ... ');
}

function normalizeCard(raw, index) {
  if (!raw) {
    return null;
  }

  if (typeof raw === 'string') {
    return {
      title: `Card ${index + 1}`,
      kicker: 'Evidence',
      tags: [],
      tagLine: '',
      shortCitation: '',
      fullCitation: '',
      citeLine: '',
      verbalCitation: '',
      formattedCard: raw,
      sourceUrl: '',
      dox: '',
      authorQualifications: '',
      fullContext: raw,
      quotedText: raw,
      exactExcerpt: raw,
      highlightedText: raw,
      source: '',
      citation: '',
      claim: raw,
      warrant: '',
      impact: '',
      body: raw,
      evidence: raw,
      highlightedExcerpt: '',
      text: raw,
      validation: null,
    };
  }

  const sourceObject = raw.source && typeof raw.source === 'object' ? raw.source : null;
  const sourceBits = sourceObject ? [
    normalizeText(sourceObject.title),
    normalizeText(sourceObject.author),
    normalizeText(sourceObject.date),
    normalizeText(sourceObject.url),
  ].filter(Boolean) : [];
  const tagLine = normalizeText(raw.tag_line ?? raw.tagLine ?? raw.tag ?? raw.kicker ?? raw.type ?? raw.bucket ?? `Card ${index + 1}`);
  const shortCitation = normalizeText(raw.short_citation ?? raw.shortCitation ?? raw.verbal_citation ?? raw.verbalCitation ?? raw.oral_citation ?? raw.citation ?? raw.cite ?? sourceBits[0] ?? tagLine);
  const fullCitation = normalizeText(raw.full_citation ?? raw.fullCitation ?? raw.citation_full ?? raw.citation ?? raw.cite ?? sourceBits.join(', '));
  const citeLine = normalizeText(raw.cite_line ?? raw.citeLine ?? '');
  const verbalCitation = normalizeText(raw.verbal_citation ?? raw.verbalCitation ?? raw.oral_citation ?? raw.oralCitation ?? '');
  const sourceUrl = normalizeText(raw.source_url ?? raw.sourceUrl ?? sourceObject?.url ?? '');
  const dox = normalizeText(raw.dox ?? raw.date_of_access ?? raw.dateOfAccess ?? raw.access_date ?? raw.accessDate ?? '');
  const authorQualifications = normalizeText(raw.author_qualifications ?? raw.authorQualifications ?? raw.qualifications ?? raw.author_bio ?? '');
  const fullContext = normalizeText(raw.full_context ?? raw.fullContext ?? raw.context ?? raw.body ?? raw.content ?? raw.text ?? raw.card_text ?? raw.evidence ?? raw.card ?? raw.payload ?? '');
  const underlinedSpans = normalizeSpans(raw.underlined_spans ?? raw.underlinedSpans ?? raw.support_spans ?? raw.supportSpans ?? [], fullContext);
  const highlightedSpans = normalizeSpans(raw.highlighted_spans ?? raw.highlightedSpans ?? raw.read_spans ?? raw.readSpans ?? [], fullContext);
  const underlinedText = normalizeText(raw.underlined_text ?? raw.underlinedText ?? joinSpanText(underlinedSpans));
  const highlightedText = normalizeText(raw.highlighted_text ?? raw.highlightedText ?? raw.highlighted_excerpt ?? raw.highlightedExcerpt ?? raw.excerpt ?? joinSpanText(highlightedSpans));
  const quotedText = normalizeText(raw.quoted_text ?? raw.quotedText ?? raw.exact_excerpt ?? raw.exactExcerpt ?? highlightedText ?? raw.excerpt ?? raw.card_text ?? raw.text ?? '');
  const rawCredibilityScore = sourceObject?.credibility_score ?? raw.credibility_score ?? raw.credibilityScore;
  const credibilityScore = rawCredibilityScore === '' || rawCredibilityScore === null || rawCredibilityScore === undefined
    ? null
    : Number(rawCredibilityScore);
  const body = raw.body ?? raw.content ?? raw.text ?? raw.card_text ?? raw.evidence ?? raw.card ?? raw.payload ?? '';
  const evidence = raw.evidence ?? raw.card_text ?? raw.text ?? raw.body ?? raw.content ?? raw.card ?? raw.payload ?? '';
  const claim = normalizeText(raw.claim ?? raw.takeaway ?? raw.tagline ?? raw.argument ?? raw.main_point ?? raw.conclusion ?? raw.excerpt ?? '');
  const tags = toArray(raw.tags ?? raw.labels ?? raw.headings ?? raw.signals ?? raw.tag).map(normalizeText).filter(Boolean);
  const validation = normalizeValidation(raw.validation);

  const normalized = {
    title: normalizeText(raw.title ?? raw.heading ?? raw.name ?? `Card ${index + 1}`),
    kicker: shortCitation || tagLine,
    tagLine,
    shortCitation,
    fullCitation,
    citeLine,
    verbalCitation,
    sourceUrl,
    dox,
    authorQualifications,
    sourceTitle: normalizeText(sourceObject?.title ?? raw.source_title ?? raw.sourceTitle ?? ''),
    sourceAuthor: normalizeText(sourceObject?.author ?? raw.source_author ?? raw.sourceAuthor ?? ''),
    sourcePublication: normalizeText(sourceObject?.publication ?? raw.source_publication ?? raw.sourcePublication ?? raw.publication ?? ''),
    sourceDate: normalizeText(sourceObject?.date ?? raw.source_date ?? raw.sourceDate ?? ''),
    sourceId: normalizeText(sourceObject?.source_id ?? raw.source_id ?? raw.sourceId ?? ''),
    credibilityScore: Number.isFinite(credibilityScore) ? credibilityScore : null,
    credibilityNotes: normalizeText(sourceObject?.credibility_notes ?? raw.credibility_notes ?? raw.credibilityNotes ?? ''),
    underlinedSpans,
    highlightedSpans,
    underlinedText,
    fullContext,
    quotedText,
    exactExcerpt: quotedText,
    highlightedText,
    tags,
    source: normalizeText(raw.source ?? fullCitation ?? raw.attribution ?? sourceBits.join(' | ')),
    citation: fullCitation || shortCitation,
    shortCitation,
    claim,
    warrant: normalizeText(raw.warrant ?? raw.reason ?? raw.analysis ?? ''),
    impact: normalizeText(raw.impact ?? raw.significance ?? raw.blip ?? ''),
    body: normalizeText(body),
    evidence: normalizeText(evidence),
    highlightedExcerpt: highlightedText,
    text: normalizeText(body || evidence),
    validation,
  };

  normalized.citeLine = normalized.citeLine || buildCiteLine(normalized);
  normalized.formattedCard = normalizeText(raw.formatted_card ?? raw.formattedCard ?? buildFormattedCard(normalized));

  return normalized;
}

function extractCards(payload) {
  if (Array.isArray(payload)) {
    return payload.map(normalizeCard).filter(Boolean).slice(0, 1);
  }

  const candidates = payload?.cards
    ?? payload?.results
    ?? payload?.data
    ?? payload?.items
    ?? payload?.output
    ?? payload?.cuts;

  const rawCards = toArray(candidates);
  const cards = rawCards.map(normalizeCard).filter(Boolean).slice(0, 1);

  const metaValidation = normalizeValidation(payload?.meta?.validation);
  if (cards.length === 1 && metaValidation && !cards[0].validation) {
    cards[0].validation = metaValidation;
  }

  if (cards.length > 0) {
    return cards;
  }

  if (typeof payload === 'string') {
    return [normalizeCard(payload, 0)];
  }

  return [];
}

function formatCopyText(card) {
  return card.formattedCard || buildFormattedCard(card);
}

function renderEmptyState() {
  currentCards = [];
  cardsEl.innerHTML = '';
  cardsEl.className = 'cards empty-state';
  copyAllBtn.disabled = true;
  hintEl.textContent = 'No card yet. Paste evidence or enter a claim to start.';
  metaEl.textContent = '';
  renderQueryPreview({
    status: 'Waiting for research',
    search_mode: getSearchModeLabel().toLowerCase(),
    query_pack: {},
  });
  renderSourceSummary({
    selected: null,
    articleText: '',
    query: '',
    status: 'Waiting for research',
    mode: 'Cut will auto-research when source fields are incomplete',
  });
}

function syncPromptPreview() {
  promptPreviewEl.textContent = buildChatgptPrompt();
}

function makeTag(label, text, className = 'tag') {
  const tag = document.createElement('span');
  tag.className = className;
  tag.textContent = `${label}${text ? ` ${text}` : ''}`;
  return tag;
}

function renderQueryList(title, queries, className = '') {
  const items = toArray(queries)
    .map((item) => normalizeText(item?.query ?? item?.text ?? item?.value ?? item))
    .filter(Boolean);
  if (!items.length) {
    return null;
  }

  const section = document.createElement('section');
  section.className = `query-preview-section${className ? ` ${className}` : ''}`;
  const heading = document.createElement('div');
  heading.className = 'label';
  heading.textContent = title;
  section.appendChild(heading);

  const list = document.createElement('div');
  list.className = 'query-pill-list';
  items.forEach((item) => {
    const pill = document.createElement('span');
    pill.className = 'query-pill';
    pill.textContent = item;
    list.appendChild(pill);
  });
  section.appendChild(list);
  return section;
}

function renderQueryPreview(research) {
  if (!queryPreviewEl) {
    return;
  }

  const queryPack = research?.query_pack ?? research?.queryPack ?? {};
  const refinementUsed = typeof research?.query_refinement_used === 'boolean'
    ? research.query_refinement_used
    : typeof queryPack?.query_refinement_used === 'boolean'
      ? queryPack.query_refinement_used
      : null;
  const refinementProvider = normalizeText(research?.query_refinement_provider ?? queryPack?.query_refinement_provider);
  const executedQueries = toArray(research?.executed_queries ?? queryPack?.executed_queries);
  const intentClaim = normalizeText(queryPack?.intent_claim ?? research?.intent_claim);
  const explanation = normalizeText(queryPack?.explanation);
  const searchMode = normalizeText(research?.search_mode ?? research?.mode ?? queryPack?.search_mode) || getSearchModeLabel().toLowerCase();

  queryPreviewEl.replaceChildren();
  let hasDetails = false;

  const header = document.createElement('div');
  header.className = 'query-preview-head';
  const badge = document.createElement('span');
  badge.className = 'mini-badge';
  badge.textContent = searchMode.includes('literal') ? 'Exact wording' : 'Meaning match';
  const sourceLine = document.createElement('div');
  sourceLine.className = 'query-preview-source';
  const refinementLabel = refinementUsed === null
    ? 'Search plan not available yet'
    : refinementUsed
      ? 'Search plan adapted to the claim'
      : 'Using the claim as written';
  sourceLine.textContent = refinementLabel;
  header.append(badge, sourceLine);
  queryPreviewEl.appendChild(header);

  if (intentClaim) {
    const intent = document.createElement('div');
    intent.className = 'query-preview-intent';
    const label = document.createElement('div');
    label.className = 'label';
    label.textContent = 'What the search is aiming to prove';
    const value = document.createElement('div');
    value.className = 'muted-block';
    value.textContent = intentClaim;
    intent.append(label, value);
    queryPreviewEl.appendChild(intent);
    hasDetails = true;
  }

  if (explanation) {
    const explanationBlock = document.createElement('div');
    explanationBlock.className = 'query-preview-explanation';
    explanationBlock.textContent = explanation;
    queryPreviewEl.appendChild(explanationBlock);
    hasDetails = true;
  }

  const packSections = [
    ['Search phrases', queryPack?.semantic_queries],
    ['Books and journals', queryPack?.academic_queries],
    ['Policy sources', queryPack?.think_tank_queries],
    ['Web sources', queryPack?.fallback_web_queries],
    ['Anchor terms', queryPack?.must_have_terms],
    ['Filtered out', queryPack?.avoid_terms],
  ];

  packSections.forEach(([title, items]) => {
    const section = renderQueryList(title, items);
    if (section) {
      queryPreviewEl.appendChild(section);
      hasDetails = true;
    }
  });

  if (executedQueries.length) {
    const executed = document.createElement('section');
    executed.className = 'query-preview-section';
    const heading = document.createElement('div');
    heading.className = 'label';
    heading.textContent = 'Searches tried';
    executed.appendChild(heading);

    const list = document.createElement('div');
    list.className = 'query-executed-list';
    executedQueries.forEach((entry) => {
      const row = document.createElement('div');
      row.className = 'query-executed-item';
      row.textContent = [
        normalizeText(entry?.stage ?? entry?.label ?? ''),
        normalizeText(entry?.query ?? entry?.text ?? entry?.value ?? entry),
      ].filter(Boolean).join(' | ');
      list.appendChild(row);
    });
    executed.appendChild(list);
    queryPreviewEl.appendChild(executed);
    hasDetails = true;
  }

  if (!hasDetails) {
    const empty = document.createElement('div');
    empty.className = 'query-preview-empty';
    empty.textContent = `Search mode is ${getSearchModeLabel().toLowerCase()}. Your search plan will appear here after you look for evidence.`;
    queryPreviewEl.appendChild(empty);
  }
}

function requestResearchMode() {
  setMode('local');
  void researchFromTag();
}

function applyResearchResult(research) {
  const selected = research?.selected ?? {};
  const articleText = normalizeText(research?.article_text);

  if (normalizeText(selected.title)) {
    fields.sourceTitle.value = normalizeText(selected.title);
  }
  if (normalizeText(selected.author)) {
    fields.sourceAuthor.value = normalizeText(selected.author);
  }
  if (normalizeText(selected.date)) {
    fields.sourceDate.value = normalizeText(selected.date);
  }
  if (normalizeText(selected.url)) {
    fields.sourceUrl.value = normalizeText(selected.url);
  }
  if (articleText) {
    fields.sourceText.value = articleText;
  }

  syncPromptPreview();
  renderQueryPreview(research);
  renderSourceSummary({
    selected,
    articleText,
    query: normalizeText(research?.query),
    status: 'Ready to cut',
    mode: articleText ? 'Evidence loaded into the form' : 'Source metadata loaded',
    research,
  });
}

function describeResearch(research) {
  const selected = research?.selected ?? {};
  const queryPack = research?.query_pack ?? research?.queryPack ?? {};
  const parts = [];

  if (normalizeText(selected.title)) {
    parts.push(`Picked: ${normalizeText(selected.title)}`);
  }
  if (normalizeText(research?.search_mode ?? queryPack?.search_mode)) {
    parts.push(`Search style: ${normalizeText(research.search_mode ?? queryPack.search_mode)}`);
  }
  if (normalizeText(queryPack?.intent_claim)) {
    parts.push(`Aiming at: ${normalizeText(queryPack.intent_claim)}`);
  }
  if (typeof research?.query_refinement_used === 'boolean') {
    parts.push(research.query_refinement_used ? 'Search plan adjusted to match the claim' : 'Used the claim as written');
  } else if (typeof queryPack?.query_refinement_used === 'boolean') {
    parts.push(queryPack.query_refinement_used ? 'Search plan adjusted to match the claim' : 'Used the claim as written');
  }

  return parts.join(' | ');
}

function renderSourceCandidates(research) {
  if (!sourceCandidatesEl) {
    return;
  }

  sourceCandidatesEl.replaceChildren();
  const sources = toArray(research?.sources).slice(0, 8);
  if (!sources.length) {
    return;
  }

  sources.forEach((source, index) => {
    const item = document.createElement('article');
    item.className = 'source-candidate';

    const head = document.createElement('div');
    head.className = 'source-candidate-head';
    const title = document.createElement('div');
    title.className = 'source-candidate-title';
    title.textContent = normalizeText(source.title) || `Source ${index + 1}`;
    head.appendChild(title);

    const score = document.createElement('span');
    score.className = 'tag';
    score.textContent = `Trust ${formatScore(source.credibility_score) || '0.000'}`;
    head.appendChild(score);

    const fit = document.createElement('span');
    fit.className = 'tag tag-muted';
    fit.textContent = `Match ${formatScore(source.topical_fit_score ?? source.score) || '0.000'}`;
    head.appendChild(fit);

    const quote = document.createElement('span');
    quote.className = 'tag tag-muted';
    quote.textContent = `Evidence ${formatScore(source.quote_strength_score) || '0.000'}`;
    head.appendChild(quote);

    if (normalizeText(source.source_class)) {
      const classTag = document.createElement('span');
      classTag.className = 'tag tag-muted';
      const sourceClass = normalizeText(source.source_class);
      const sourceClassLabel = {
        peer_reviewed: 'Journal or book',
        preprint: 'Working draft',
        working_paper: 'Working paper',
        think_tank: 'Policy source',
        general_web: 'Web source',
        summary_or_news: 'Summary page',
      }[sourceClass] || sourceClass;
      classTag.textContent = sourceClassLabel;
      head.appendChild(classTag);
    }
    if (typeof source.paper_verified === 'boolean') {
      const paperTag = document.createElement('span');
      paperTag.className = source.paper_verified ? 'tag' : 'tag tag-warn';
      paperTag.textContent = source.paper_verified ? 'Full text found' : 'Full text unclear';
      head.appendChild(paperTag);
    }
    item.appendChild(head);

    const meta = document.createElement('div');
    meta.className = 'source-candidate-meta';
    meta.textContent = [
      normalizeText(source.author),
      normalizeText(source.publication),
      normalizeText(source.date),
      normalizeText(source.doi),
      normalizeText(source.pdf_url),
      normalizeText(source.credibility_notes),
    ].filter(Boolean).join(' | ');
    if (meta.textContent) {
      item.appendChild(meta);
    }

    if (normalizeText(source.snippet)) {
      const snippet = document.createElement('div');
      snippet.className = 'muted-block';
      snippet.textContent = normalizeText(source.snippet);
      item.appendChild(snippet);
    }

    if (normalizeText(source.url)) {
      const url = document.createElement('a');
      url.className = 'source-candidate-url';
      url.href = normalizeText(source.url);
      url.target = '_blank';
      url.rel = 'noreferrer';
      url.textContent = normalizeText(source.url);
      item.appendChild(url);
    }

    sourceCandidatesEl.appendChild(item);
  });
}

function renderSourceSummary(research) {
  if (!sourceSummaryEl) {
    return;
  }

  const selected = research?.selected ?? {};
  const items = [
    {
      label: 'Selected source',
      value: normalizeText(selected.title) || 'Waiting for research',
    },
    {
      label: 'Search mode',
      value: [
        normalizeText(research?.search_mode),
        normalizeText(research?.query_refinement_used === true ? 'Search plan adjusted to the claim' : research?.query_refinement_used === false ? 'Using the claim as written' : ''),
      ].filter(Boolean).join(' | ') || getSearchModeLabel(),
    },
    {
      label: 'Intent claim',
      value: normalizeText(research?.query_pack?.intent_claim) || normalizeText(research?.intent_claim) || 'Waiting for the search plan',
    },
    {
      label: 'Source details',
      value: [
        normalizeText(selected.author),
        normalizeText(selected.date),
        normalizeText(selected.credibility_notes),
        normalizeText(selected.url),
      ].filter(Boolean).join(' | ') || 'No source yet',
    },
  ];

  sourceSummaryEl.replaceChildren();
  items.forEach((item) => {
    const block = document.createElement('div');
    block.className = 'source-summary-item';
    const label = document.createElement('span');
    const value = document.createElement('strong');
    label.textContent = item.label;
    value.textContent = item.value;
    block.append(label, value);
    sourceSummaryEl.appendChild(block);
  });
  renderSourceCandidates(research);
}

function renderQueueProgress(items) {
  if (!queueProgressEl) {
    return;
  }
  queueProgressEl.replaceChildren();
  toArray(items).forEach((item) => {
    const row = document.createElement('li');
    const title = document.createElement('strong');
    title.textContent = normalizeText(item.tag) || 'Queued tag';
    const meta = document.createElement('span');
    meta.textContent = normalizeText(item.status) || '';
    row.append(title, meta);

    const detailParts = [
      normalizeText(item.stage),
      item.retryCount ? `extra tries x${item.retryCount}` : '',
    ].filter(Boolean);
    if (detailParts.length) {
      const details = document.createElement('div');
      details.className = 'queue-progress-details';
      details.textContent = detailParts.join(' | ');
      row.appendChild(details);
    }
    if (normalizeText(item.error)) {
      const error = document.createElement('div');
      error.className = 'queue-progress-error';
      error.textContent = normalizeText(item.error);
      row.appendChild(error);
    }
    queueProgressEl.appendChild(row);
  });
}

async function researchFromTag() {
  const payload = buildRequestBody();

  if (!payload.draft_tag && !payload.source_url) {
    setStatus('Enter a claim or source URL first.', 'error');
    return;
  }

  setBusy(true);
  setStatus('Looking for a useful source...', '');
  metaEl.textContent = 'Searching likely sources.';
  renderSourceSummary({
    selected: {
      title: payload.draft_tag || 'Research in progress',
      author: '',
      date: '',
      url: payload.source_url,
    },
    status: 'Looking for evidence',
    mode: 'Checking likely sources and ranking the best fit',
    search_mode: getSearchModeLabel().toLowerCase(),
  });
  renderQueryPreview({
    status: 'Looking for evidence',
    search_mode: getSearchModeLabel().toLowerCase(),
    query_pack: {},
  });

  try {
    const { data } = await postJson('/api/research', payload, {
      action: 'Research',
      stage: 'Searching sources',
    });
    const research = data?.research;
    if (!research) {
      throw new Error('No source details came back.');
    }

    applyResearchResult(research);
    setStatus('Found a likely source and filled it in.', 'success');
    metaEl.textContent = describeResearch(research) || 'Source search finished.';
  } catch (error) {
    setStatus(error instanceof Error ? error.message : 'Could not find a useful source from that claim.', 'error');
    metaEl.textContent = 'Try adding source text or a direct source URL.';
    renderSourceSummary({
      selected: {
        title: payload.draft_tag || 'Research failed',
        author: '',
        date: '',
        url: payload.source_url,
      },
      status: 'Research failed',
      mode: 'Try adding source text or a direct source URL',
    });
  } finally {
    setBusy(false);
  }
}

function importCardsFromText(rawText) {
  const cleaned = stripCodeFences(rawText);
  if (!cleaned) {
    throw new Error('Paste the ChatGPT result before importing.');
  }

  const parsed = parseJsonLike(cleaned);
  const cards = extractCards(parsed);
  if (!cards.length) {
    throw new Error('No cards were found in the pasted result.');
  }

  rememberCards(cards, { provider: 'chatgpt_manual' }, buildRequestBody().draft_tag);
  renderCards(cards);
  metaEl.textContent = 'Imported from ChatGPT.';
  setStatus(`Imported ${cards.length} card.`, 'success');
}

function renderCards(cards) {
  currentCards = cards;
  cardsEl.innerHTML = '';
  cardsEl.className = 'cards';

  if (!cards.length) {
    renderEmptyState();
    return;
  }

  cards.forEach((card, index) => {
    const node = template.content.cloneNode(true);
    const article = node.querySelector('.card');
    const kicker = node.querySelector('.card-kicker');
    const title = node.querySelector('.card-title');
    const citation = node.querySelector('.card-citation');
    const body = node.querySelector('.card-body');
    const copyBtn = node.querySelector('.card-copy');

    kicker.textContent = card.shortCitation || card.kicker || `Card ${index + 1}`;
    title.textContent = card.tagLine || card.title || `Card ${index + 1}`;
    citation.replaceChildren();

    const credibilityText = formatScore(card.credibilityScore);
    const credibilityLabel = credibilityText ? `Cred ${credibilityText}` : '';
    const topRow = [
      card.shortCitation || card.citation,
      card.dox ? `DOA ${card.dox}` : '',
      card.sourceId ? `Source ${card.sourceId}` : (card.sourceUrl ? 'Full URL below' : ''),
      credibilityLabel,
      card.validation?.passed === false ? 'Needs source review' : 'Ready to cut into file',
    ].filter(Boolean);
    topRow.forEach((item) => {
      const span = document.createElement('span');
      span.className = item === 'Needs source review'
        ? 'tag tag-warn'
        : (item.startsWith('Cred ') || item.startsWith('Source ')) ? 'tag tag-muted' : 'tag';
      span.textContent = item;
      citation.appendChild(span);
    });

    if (card.citeLine || card.fullCitation) {
      const fullCitationBlock = document.createElement('div');
      fullCitationBlock.className = 'cite-line';
      fullCitationBlock.textContent = card.citeLine || buildCiteLine(card);
      citation.appendChild(fullCitationBlock);
    }

    if (card.verbalCitation) {
      const verbalWrap = document.createElement('div');
      verbalWrap.className = 'cite-quals';
      const verbalLabel = document.createElement('div');
      const verbalValue = document.createElement('div');

      verbalLabel.className = 'label';
      verbalLabel.textContent = 'Verbal citation';
      verbalValue.className = 'muted-block';
      verbalValue.textContent = card.verbalCitation;
      verbalWrap.append(verbalLabel, verbalValue);
      citation.appendChild(verbalWrap);
    }

    if (card.authorQualifications) {
      const qualsWrap = document.createElement('div');
      qualsWrap.className = 'cite-quals';
      const qualsLabel = document.createElement('div');
      const qualsValue = document.createElement('div');

      qualsLabel.className = 'label';
      qualsLabel.textContent = 'Author qualifications';
      qualsValue.className = 'muted-block';
      qualsValue.textContent = card.authorQualifications;
      qualsWrap.append(qualsLabel, qualsValue);
      citation.appendChild(qualsWrap);
    }

    body.replaceChildren();
    appendCardSection(body, 'Evidence paragraph', renderEvidenceContent(card), 'card-section-evidence');

    const underlinedText = card.underlinedText || joinSpanText(card.underlinedSpans);
    if (underlinedText) {
      appendCardSection(body, 'Underlined support', underlinedText, 'card-section-support');
    }

    const highlightedRead = card.highlightedText || joinSpanText(card.highlightedSpans);
    if (highlightedRead) {
      appendCardSection(body, 'Highlighted read', highlightedRead, 'card-section-highlighted');
    }

    const sourcePacketItems = [
      ['Source ID', card.sourceId],
      ['Title', card.sourceTitle],
      ['Author', card.sourceAuthor],
      ['Publication', card.sourcePublication],
      ['Date', card.sourceDate],
      ['Date accessed', card.dox],
      ['Credibility score', credibilityText],
      ['Credibility notes', card.credibilityNotes],
    ];
    const sourcePacket = document.createElement('div');
    sourcePacket.className = 'analytics-grid source-packet';
    sourcePacketItems.forEach(([labelText, value]) => {
      const cleaned = normalizeText(value);
      if (!cleaned) {
        return;
      }
      const block = document.createElement('div');
      block.className = 'analytics-item';
      const labelEl = document.createElement('div');
      const valueEl = document.createElement('div');
      labelEl.className = 'label';
      labelEl.textContent = labelText;
      valueEl.className = 'muted-block';
      valueEl.textContent = cleaned;
      block.append(labelEl, valueEl);
      sourcePacket.appendChild(block);
    });
    if (card.sourceUrl) {
      const block = document.createElement('div');
      block.className = 'analytics-item source-packet-url';
      const labelEl = document.createElement('div');
      const link = document.createElement('a');
      labelEl.className = 'label';
      labelEl.textContent = 'Full URL';
      link.href = card.sourceUrl;
      link.target = '_blank';
      link.rel = 'noreferrer';
      link.className = 'card-source-link';
      link.textContent = card.sourceUrl;
      block.append(labelEl, link);
      sourcePacket.appendChild(block);
    }
    if (sourcePacket.childElementCount) {
      appendCardSection(body, 'Source packet', sourcePacket, 'card-section-source');
    }

    if (card.validation) {
      appendCardSection(body, 'Validation', buildValidationText(card.validation), 'card-section-validation');
    }

    if (card.claim || card.warrant || card.impact) {
      const analytics = document.createElement('div');
      analytics.className = 'analytics-grid';
      [
        ['Claim', card.claim],
        ['Warrant', card.warrant],
        ['Impact', card.impact],
      ].forEach(([labelText, value]) => {
        if (!value) {
          return;
        }
        const block = document.createElement('div');
        block.className = 'analytics-item';
        const labelEl = document.createElement('div');
        const valueEl = document.createElement('div');
        labelEl.className = 'label';
        labelEl.textContent = labelText;
        valueEl.className = 'muted-block';
        valueEl.textContent = value;
        block.append(labelEl, valueEl);
        analytics.appendChild(block);
      });
      appendCardSection(body, 'Round use', analytics, 'card-section-analytics');
    }

    copyBtn.addEventListener('click', async () => {
      try {
        await copyToClipboard(formatCopyText(card));
        setStatus(`Copied ${card.title || `card ${index + 1}`}.`, 'success');
      } catch {
        setStatus('Could not copy the card text.', 'error');
      }
    });

    article.setAttribute('data-index', String(index));
    cardsEl.appendChild(node);
  });

  copyAllBtn.disabled = false;
  hintEl.textContent = `${cards.length} card${cards.length === 1 ? '' : 's'} on stage. ${savedCards.length} saved in your library.`;
  if (!metaEl.textContent) {
    metaEl.textContent = 'Rendered in debate-file format.';
  }
}

function renderSavedCardsList() {
  if (!savedCardsListEl) {
    return;
  }

  savedCardsListEl.replaceChildren();

  if (!savedCards.length) {
    const empty = document.createElement('li');
    empty.className = 'saved-cards-empty';
    const strong = document.createElement('strong');
    strong.textContent = 'No saved cards yet.';
    const span = document.createElement('span');
    span.textContent = 'The next cut will appear here as a separate card entry.';
    empty.append(strong, span);
    savedCardsListEl.appendChild(empty);
  } else {
    savedCards.forEach((entry, index) => {
      const item = document.createElement('li');
      item.className = 'saved-card-item';

      const titleWrap = document.createElement('div');
      titleWrap.className = 'saved-card-copy';
      const titleEl = document.createElement('strong');
      titleEl.textContent = entry.card.tagLine || entry.card.title || `Card ${index + 1}`;
      const metaLine = document.createElement('span');
      metaLine.textContent = [entry.card.shortCitation, entry.draftTag].filter(Boolean).join(' | ') || 'Saved card';
      titleWrap.append(titleEl, metaLine);

      const actions = document.createElement('div');
      actions.className = 'saved-card-actions';

      const showBtn = document.createElement('button');
      showBtn.type = 'button';
      showBtn.className = 'secondary';
      showBtn.textContent = 'Show';
      showBtn.addEventListener('click', () => {
        renderCards([entry.card]);
        setStatus(`Loaded ${entry.card.tagLine || entry.card.title || 'saved card'}.`, '');
      });

      const copyBtn = document.createElement('button');
      copyBtn.type = 'button';
      copyBtn.className = 'secondary';
      copyBtn.textContent = 'Copy';
      copyBtn.addEventListener('click', async () => {
        try {
          await copyToClipboard(formatCopyText(entry.card));
          setStatus(`Copied ${entry.card.tagLine || entry.card.title || 'saved card'}.`, 'success');
        } catch {
          setStatus('Could not copy the saved card.', 'error');
        }
      });

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'secondary';
      removeBtn.textContent = 'Remove';
      removeBtn.addEventListener('click', () => {
        savedCards = savedCards.filter((saved) => saved.id !== entry.id);
        saveSavedCards();
        renderSavedCardsList();
        if (!savedCards.length && !currentCards.length) {
          renderEmptyState();
        }
      });

      actions.append(showBtn, copyBtn, removeBtn);
      item.append(titleWrap, actions);
      savedCardsListEl.appendChild(item);
    });
  }

  if (downloadDocxBtn) {
    downloadDocxBtn.disabled = savedCards.length === 0;
  }
  if (downloadTextBtn) {
    downloadTextBtn.disabled = savedCards.length === 0;
  }
}

function describeMeta(meta) {
  if (!meta || typeof meta !== 'object') {
    return 'Card ready.';
  }

  const parts = [];

  if (meta.fallback_used) {
    parts.push('Built from a rough backup pass');
  } else {
    parts.push('Card ready');
  }
  if (meta.validation_completed) {
    parts.push('Checked against the source');
  } else if (meta.validation_ran) {
    parts.push('Source check finished');
  }
  if (typeof meta.source_attempts === 'number' && meta.source_attempts > 0) {
    parts.push(`${meta.source_attempts} source${meta.source_attempts === 1 ? '' : 's'} checked`);
  }
  if (typeof meta.card_count === 'number') {
    parts.push(`${meta.card_count} card${meta.card_count === 1 ? '' : 's'}`);
  }
  if (typeof meta.queue_count === 'number') {
    parts.push(`Batch ${meta.completed_count ?? 0}/${meta.queue_count}`);
  }
  if (toArray(meta.provider_errors).length) {
    parts.push(`${toArray(meta.provider_errors).length} issue${toArray(meta.provider_errors).length === 1 ? '' : 's'} to review`);
  }

  return parts.join(' | ') || 'Card ready.';
}

async function copyToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const temp = document.createElement('textarea');
  temp.value = text;
  temp.setAttribute('readonly', '');
  temp.style.position = 'fixed';
  temp.style.left = '-9999px';
  document.body.appendChild(temp);
  temp.select();
  document.execCommand('copy');
  temp.remove();
}

function buildSummaryText() {
  const cards = currentCards.length ? currentCards : savedCards.map((entry) => entry.card);
  if (!cards.length) {
    return '';
  }
  return cards.map((card) => formatCopyText(card)).filter(Boolean).join('\n\n');
}

function buildExportTitle() {
  return normalizeText(fields.draftTag.value) || normalizeText(fields.resolution.value) || 'debate-cards';
}

function parseQueuedTags() {
  return normalizeText(queueTagsEl?.value)
    .split(/\r?\n/)
    .map(normalizeText)
    .filter(Boolean);
}

function nextPaint() {
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => resolve());
  });
}

function updateQueueProgressItem(progress, index, status) {
  if (typeof status === 'string') {
    progress[index] = {
      ...progress[index],
      status,
    };
  } else {
    progress[index] = {
      ...progress[index],
      ...status,
    };
  }
  renderQueueProgress(progress);
}

async function triggerDownload(filename, blob) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function runQueuedCuts() {
  const draftTags = parseQueuedTags();
  if (!draftTags.length) {
    setStatus('Add at least one claim to the batch.', 'error');
    return;
  }

  const basePayload = buildRequestBody();
  const progress = draftTags.map((tag) => ({
    tag,
    status: 'Waiting',
    stage: '',
    provider: '',
    retryCount: 0,
    requestId: '',
    error: '',
  }));

  setBusy(true);
  const workerCount = Math.min(QUEUE_PARALLELISM, draftTags.length);
  setStatus(`Running ${draftTags.length} claim${draftTags.length === 1 ? '' : 's'} in a batch...`, '');
  metaEl.textContent = `Working through ${draftTags.length} claim${draftTags.length === 1 ? '' : 's'} with ${workerCount} lane${workerCount === 1 ? '' : 's'}.`;
  renderQueueProgress(progress);

  try {
    const successfulCardsByIndex = Array.from({ length: draftTags.length }, () => []);
    const failures = [];
    let nextIndex = 0;

    async function processQueueItem(index) {
      const draftTag = draftTags[index];
      updateQueueProgressItem(progress, index, { status: 'Shaping the claim...', stage: 'Search setup', error: '' });
      await nextPaint();
      updateQueueProgressItem(progress, index, { status: 'Looking through books and journals...', stage: 'Books and journals' });
      await nextPaint();
      updateQueueProgressItem(progress, index, { status: 'Checking policy sources...', stage: 'Policy sources' });
      await nextPaint();
      updateQueueProgressItem(progress, index, { status: 'Checking the web...', stage: 'Web search' });
      await nextPaint();
      updateQueueProgressItem(progress, index, { status: 'Picking the best source...', stage: 'Source choice' });
      await nextPaint();

      const payload = {
        ...basePayload,
        draft_tag: draftTag,
        desired_cards: 1,
        article_text: '',
        source_title: '',
        source_author: '',
        source_date: '',
        source_publication: '',
        source_url: '',
      };

      try {
        const { data: researchData } = await postJson('/api/research', payload, {
          action: 'Queue research',
          stage: `Researching ${draftTag}`,
        });
        const research = researchData?.research ?? null;
        if (research) {
          renderQueryPreview(research);
          renderSourceSummary(research);
          updateQueueProgressItem(progress, index, {
            requestId: normalizeText(researchData?.request_id),
            provider: normalizeText(research?.query_refinement_provider),
          });
        }
        updateQueueProgressItem(progress, index, { status: 'Comparing likely sources...', stage: 'Source choice' });
        await nextPaint();
        updateQueueProgressItem(progress, index, { status: 'Building the card...', stage: 'Card build' });

        const { data } = await postJson('/api/cut', {
          ...payload,
          semantic_search_enabled: semanticSearchEnabled,
          query_pack: research?.query_pack ?? research?.queryPack ?? {},
          research_meta: research,
        }, {
          action: 'Queue cut',
          stage: `Cutting ${draftTag}`,
        });
        const cards = extractCards(data);
        if (!cards.length) {
          throw new Error('No card returned.');
        }

        successfulCardsByIndex[index] = cards;
        rememberCards(cards, data?.meta ?? {}, draftTag);
        const selected = data?.meta?.research?.selected ?? {};
        updateQueueProgressItem(progress, index, {
          status: 'Checking the final wording...',
          stage: 'Final check',
          provider: normalizeText(data?.meta?.provider),
          retryCount: Number(data?.meta?.json_retry_count ?? 0) + Number(data?.meta?.validation_retry_count ?? 0),
          requestId: normalizeText(data?.request_id),
        });
        await nextPaint();
        updateQueueProgressItem(progress, index, {
          status: [
            'Done',
            normalizeText(selected.title) || '',
          ].filter(Boolean).join(' | '),
          stage: 'Ready',
          provider: normalizeText(data?.meta?.provider),
          retryCount: Number(data?.meta?.json_retry_count ?? 0) + Number(data?.meta?.validation_retry_count ?? 0),
          requestId: normalizeText(data?.request_id),
          error: '',
        });
        if (data?.meta?.research) {
          renderSourceSummary(data.meta.research);
          renderQueryPreview(data.meta.research);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : 'failed';
        const requestId = normalizeText(error?.responseData?.request_id ?? error?.responseData?.requestId);
        failures.push(`${draftTag}: ${message}`);
        updateQueueProgressItem(progress, index, {
          status: `Could not finish this card`,
          stage: 'Failed',
          requestId,
          error: message,
        });
      }
    }

    async function runWorker() {
      while (true) {
        const index = nextIndex;
        nextIndex += 1;
        if (index >= draftTags.length) {
          return;
        }
        setStatus(`Queue ${index + 1}/${draftTags.length}: ${draftTags[index]}`, '');
        await processQueueItem(index);
      }
    }

    await Promise.all(Array.from({ length: workerCount }, () => runWorker()));

    const successfulCards = successfulCardsByIndex.flat();

    if (successfulCards.length) {
      renderCards(successfulCards);
    } else {
      renderEmptyState();
    }

    const failureSuffix = failures.length ? ` ${failures.length} failed.` : '';
    setStatus(`Queue finished with ${successfulCards.length} card${successfulCards.length === 1 ? '' : 's'}.${failureSuffix}`, failures.length ? 'error' : 'success');
    metaEl.textContent = failures.length ? failures.join(' | ') : `Finished ${successfulCards.length} card${successfulCards.length === 1 ? '' : 's'}.`;
  } catch (error) {
    setStatus(error instanceof Error ? error.message : 'Could not finish the batch.', 'error');
  } finally {
    setBusy(false);
  }
}

copyPromptBtn.addEventListener('click', async () => {
  try {
    await copyToClipboard(buildChatgptPrompt());
    setStatus('Copied the ChatGPT instructions.', 'success');
  } catch {
    setStatus('Could not copy the instructions.', 'error');
  }
});

renderImportBtn.addEventListener('click', () => {
  try {
    importCardsFromText(importJsonEl.value);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : 'Could not import cards.', 'error');
  }
});

modeLocalBtn.addEventListener('click', () => {
  setMode('local');
  setStatus('Quick cut is ready.', '');
});

modeChatgptBtn.addEventListener('click', () => {
  setMode('chatgpt');
  syncPromptPreview();
  setStatus('ChatGPT handoff is ready.', '');
});

researchBtn.addEventListener('click', requestResearchMode);

searchModeSemanticBtn?.addEventListener('click', () => {
  setSearchMode(true);
  syncPromptPreview();
  renderQueryPreview({
    search_mode: getSearchModeLabel().toLowerCase(),
    query_pack: {},
  });
});

searchModeLiteralBtn?.addEventListener('click', () => {
  setSearchMode(false);
  syncPromptPreview();
  renderQueryPreview({
    search_mode: getSearchModeLabel().toLowerCase(),
    query_pack: {},
  });
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = buildRequestBody();
  const shouldAutoResearch = !hasCompleteSourceInputs(payload) && !!(payload.draft_tag || payload.source_url);

  if (!payload.article_text && !payload.source_url && !payload.draft_tag) {
    setStatus('Paste evidence, enter a claim, or provide a source URL before cutting.', 'error');
    return;
  }

  setBusy(true);
  setStatus(shouldAutoResearch ? 'Looking for a source, then building the card...' : 'Building the card...', '');
  metaEl.textContent = 'Working on your card.';

  try {
    const { data } = await postJson('/api/cut', payload, {
      action: 'Cut',
      stage: shouldAutoResearch ? 'Researching then cutting' : 'Cutting card',
    });
    const cards = extractCards(data);
    if (!cards.length) {
      renderEmptyState();
      setStatus('No card came back.', 'error');
      metaEl.textContent = 'Try again with source text or a direct source URL.';
      return;
    }

    rememberCards(cards, data?.meta ?? {}, payload.draft_tag);
    renderCards(cards);
    metaEl.textContent = describeMeta(data?.meta);
    setStatus('Generated 1 card.', 'success');
    if (data?.meta?.research) {
      renderSourceSummary(data.meta.research);
      renderQueryPreview(data.meta.research);
    }
    if (currentMode === 'chatgpt') {
      syncPromptPreview();
    }
  } catch (error) {
    renderEmptyState();
    setStatus(error instanceof Error ? error.message : 'Unable to cut the card.', 'error');
    metaEl.textContent = 'We could not build a card from that yet. Try adding source text or a direct source URL.';
  } finally {
    setBusy(false);
  }
});

copyAllBtn.addEventListener('click', async () => {
  if (!currentCards.length) {
    return;
  }

  try {
    await copyToClipboard(buildSummaryText());
    setStatus('Copied the card.', 'success');
  } catch {
    setStatus('Could not copy the card.', 'error');
  }
});

queueAddBtn?.addEventListener('click', () => {
  const draftTag = normalizeText(fields.draftTag.value);
  if (!draftTag) {
    setStatus('Enter a claim before adding it to the batch.', 'error');
    return;
  }

  const existing = parseQueuedTags();
  if (!existing.includes(draftTag)) {
    existing.push(draftTag);
    queueTagsEl.value = `${existing.join('\n')}\n`;
  }
  setStatus('Added the current claim to the batch.', 'success');
});

queueRunBtn?.addEventListener('click', () => {
  void runQueuedCuts();
});

downloadTextBtn?.addEventListener('click', async () => {
  const cards = savedCards.map((entry) => entry.card);
  if (!cards.length) {
    setStatus('Cut or save at least one card before downloading text.', 'error');
    return;
  }

  const text = cards.map((card) => formatCopyText(card)).filter(Boolean).join('\n\n');
  await triggerDownload(`${buildExportTitle()}.txt`, new Blob([text], { type: 'text/plain;charset=utf-8' }));
  setStatus('Downloaded the text export.', 'success');
});

downloadDocxBtn?.addEventListener('click', async () => {
  const cards = savedCards.map((entry) => entry.card);
  if (!cards.length) {
    setStatus('Cut or save at least one card before downloading the Word file.', 'error');
    return;
  }

  setBusy(true);
  setStatus('Preparing the Word file...', '');
  try {
    const response = await fetch('/api/export/docx', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        title: buildExportTitle(),
        cards,
      }),
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `Export failed with status ${response.status}.`);
    }

    const disposition = response.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="([^"]+)"/i);
    const filename = match?.[1] || `${buildExportTitle()}.verbatim.docx`;
    const blob = await response.blob();
    await triggerDownload(filename, blob);
    setStatus('Downloaded the Word file.', 'success');
  } catch (error) {
    setStatus(error instanceof Error ? error.message : 'Could not download the Word file.', 'error');
  } finally {
    setBusy(false);
  }
});

renderEmptyState();
syncPromptPreview();
setSearchMode(true);
setMode('local');
renderSourceSummary();
renderQueryPreview({ search_mode: getSearchModeLabel().toLowerCase(), query_pack: {} });
renderSavedCardsList();
clearRuntimeStatus();

Object.values(fields).forEach((field) => {
  field.addEventListener('input', syncPromptPreview);
  field.addEventListener('change', syncPromptPreview);
});
