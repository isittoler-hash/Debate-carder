const form = document.getElementById('cut-form');
const submitBtn = document.getElementById('submit-btn');
const copyAllBtn = document.getElementById('copy-all-btn');
const modeLocalBtn = document.getElementById('mode-local');
const modeChatgptBtn = document.getElementById('mode-chatgpt');
const researchBtn = document.getElementById('research-btn');
const chatgptPanel = document.getElementById('chatgpt-panel');
const promptPreviewEl = document.getElementById('prompt-preview');
const copyPromptBtn = document.getElementById('copy-prompt-btn');
const renderImportBtn = document.getElementById('render-import-btn');
const importJsonEl = document.getElementById('import-json');
const sourceSummaryEl = document.getElementById('source-summary');
const statusEl = document.getElementById('status');
const metaEl = document.getElementById('meta');
const cardsEl = document.getElementById('cards');
const hintEl = document.getElementById('output-hint');
const template = document.getElementById('card-template');

const fields = {
  draftTag: document.getElementById('draft-tag'),
  resolution: document.getElementById('resolution'),
  side: document.getElementById('side'),
  sourceText: document.getElementById('source-text'),
  sourceTitle: document.getElementById('source-title'),
  sourceAuthor: document.getElementById('source-author'),
  sourceDate: document.getElementById('source-date'),
  sourceUrl: document.getElementById('source-url'),
  emphasis: document.getElementById('emphasis'),
};

let currentCards = [];
let currentMode = 'local';

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
  submitBtn.querySelector('.button-label').textContent = isChatgpt ? 'Cut card via backend' : 'Cut card';

  if (isChatgpt) {
    metaEl.textContent = 'Manual ChatGPT workflow uses copy/paste only.';
  } else if (!currentCards.length) {
    metaEl.textContent = '';
  }
}

function normalizeText(value) {
  return String(value ?? '').trim();
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
  };

  if (
    normalized.useful === null
    && normalized.revised === null
    && normalized.passed === null
    && !normalized.notes
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
    validation.issues.length ? `Issues: ${validation.issues.join('; ')}` : '',
    validation.sourceChecks.length ? `Source checks: ${validation.sourceChecks.join('; ')}` : '',
  ].filter(Boolean);

  return lines.join('\n');
}

function getSourceHost(url) {
  const cleaned = normalizeText(url);
  if (!cleaned) {
    return '';
  }

  try {
    return new URL(cleaned).hostname.replace(/^www\./i, '');
  } catch {
    return cleaned;
  }
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

function buildFormattedCard(card) {
  const lines = [];

  if (card.tagLine || card.title) {
    lines.push(card.tagLine || card.title);
  }
  if (card.citeLine || card.shortCitation || card.fullCitation) {
    lines.push(card.citeLine || buildCiteLine(card));
  }
  if (card.verbalCitation) {
    lines.push(`Verbal cite: ${card.verbalCitation}`);
  }
  if (card.fullContext || card.body || card.text) {
    lines.push(card.fullContext || card.body || card.text);
  }
  if (card.readText && card.readText !== card.fullContext) {
    lines.push('');
    lines.push(`Read text: ${card.readText}`);
  }

  return lines.filter(Boolean).join('\n').trim();
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
    desired_cards: 1,
    emphasis: normalizeText(fields.emphasis.value),
  };
}

function buildChatgptPrompt() {
  const request = buildRequestBody();
  const lines = [
    'You are a debate evidence researcher and cutter.',
    'Return strict JSON only. Do not wrap the answer in markdown fences or commentary.',
    'Produce an object with a `cards` array containing exactly one card.',
    'Perform a recursive validation pass before returning the final card.',
    'Each card must include:',
    '- tag_line',
    '- short_citation',
    '- full_citation',
    '- cite_line',
    '- verbal_citation',
    '- source_url',
    '- dox or date_of_access',
    '- author_qualifications',
    '- read_text',
    '- full_context',
    '- quoted_text or exact_excerpt',
    '- highlighted_text',
    '- warrant',
    '- impact',
    '- source { title, author, date, url }',
    '- claim if useful',
    '',
    'Rules:',
    '- Cut exactly one card.',
    `- The debate side is ${request.side}.`,
    request.resolution ? `- The resolution is: ${request.resolution}.` : '- No resolution was supplied.',
    request.draft_tag ? `- The draft tag is: ${request.draft_tag}. Research likely sources from this tag before cutting.` : '- No draft tag was supplied.',
    request.emphasis ? `- Prioritize: ${request.emphasis}.` : '- No extra emphasis was supplied.',
    '- Use debate-card structure: tag line, short cite line, bracketed full citation, source URL, date of access, author qualifications, full context, read text, highlighted text, warrant, and impact.',
    '- Match common debate file layout: Heading 4 style tag, cite line, then evidence paragraph.',
    '- Build the cite line in the style `Shortcite [full citation, DOA:MM-DD-YYYY] //IT` when possible.',
    '- First draft the card, then validate it for usefulness, factual fidelity, and debate value.',
    '- If validation finds a weakness, revise the card before returning final JSON.',
    '- Return a validation object with your assessment, revision notes, and whether the card is worth keeping.',
    '- Prefer a direct quote with surrounding context when possible.',
    '- Mark the exact words that are meant to be read aloud or highlighted in the round.',
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
          read_text: 'string',
          full_context: 'string',
          quoted_text: 'string',
          exact_excerpt: 'string',
          highlighted_text: 'string',
          formatted_card: 'string',
          validation: {
            passed: 'boolean',
            useful: 'boolean',
            issues: ['string'],
            revision_notes: 'string',
            source_checks: ['string'],
          },
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
            title: 'string',
            author: 'string',
            date: 'string',
            url: 'string',
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
      throw new Error('Could not find JSON in the pasted response.');
    }

    const end = Math.max(cleaned.lastIndexOf('}'), cleaned.lastIndexOf(']'));
    if (end <= start) {
      throw new Error('Could not find complete JSON in the pasted response.');
    }

    return JSON.parse(cleaned.slice(start, end + 1));
  }
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
      readText: raw,
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
  const readText = normalizeText(raw.read_text ?? raw.readText ?? raw.read ?? raw.highlighted_text ?? raw.highlightedText ?? raw.quoted_text ?? raw.quotedText ?? raw.exact_excerpt ?? raw.exactExcerpt ?? raw.excerpt ?? raw.card_text ?? raw.text ?? raw.body ?? raw.evidence ?? raw.card ?? raw.payload ?? '');
  const fullContext = normalizeText(raw.full_context ?? raw.fullContext ?? raw.context ?? raw.body ?? raw.content ?? raw.text ?? raw.card_text ?? raw.evidence ?? raw.card ?? raw.payload ?? '');
  const quotedText = normalizeText(raw.quoted_text ?? raw.quotedText ?? raw.exact_excerpt ?? raw.exactExcerpt ?? raw.read_text ?? raw.readText ?? raw.highlighted_text ?? raw.highlightedText ?? raw.excerpt ?? raw.card_text ?? raw.text ?? '');
  const highlightedText = normalizeText(raw.highlighted_text ?? raw.highlightedText ?? raw.highlighted_excerpt ?? raw.highlightedExcerpt ?? raw.excerpt ?? quotedText);
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
    readText,
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
  const base = card.formattedCard || buildFormattedCard(card);
  const analytics = [
    card.claim ? `Claim: ${card.claim}` : '',
    card.warrant ? `Warrant: ${card.warrant}` : '',
    card.impact ? `Impact: ${card.impact}` : '',
    buildValidationText(card.validation) ? `Validation:\n${buildValidationText(card.validation)}` : '',
  ].filter(Boolean);

  if (!analytics.length) {
    return base;
  }

  return `${base}\n\n${analytics.join('\n')}`;
}

function renderEmptyState() {
  currentCards = [];
  cardsEl.innerHTML = '';
  cardsEl.className = 'cards empty-state';
  copyAllBtn.disabled = true;
  hintEl.textContent = 'No card yet. Paste text or enter a draft tag to research a source.';
  metaEl.textContent = '';
  renderSourceSummary({
    selected: null,
    articleText: '',
    query: '',
    status: 'Waiting for research',
    mode: 'Paste text or research from a tag',
  });
}

function syncPromptPreview() {
  promptPreviewEl.textContent = buildChatgptPrompt();
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
  renderSourceSummary({
    selected,
    articleText,
    query: normalizeText(research?.query),
    status: 'Ready to cut',
    mode: articleText ? 'Evidence loaded into the form' : 'Source metadata loaded',
  });
}

function describeResearch(research) {
  const selected = research?.selected ?? {};
  const parts = [];

  if (normalizeText(selected.engine)) {
    parts.push(`source: ${normalizeText(selected.engine)}`);
  }
  if (normalizeText(selected.title)) {
    parts.push(normalizeText(selected.title));
  }
  if (normalizeText(research?.query)) {
    parts.push(`query: ${normalizeText(research.query)}`);
  }

  return parts.join(' | ');
}

function renderSourceSummary(research) {
  if (!sourceSummaryEl) {
    return;
  }

  const selected = research?.selected ?? {};
  const host = getSourceHost(selected.url);
  const items = [
    {
      label: 'Selected source',
      value: normalizeText(selected.title) || 'Waiting for research',
    },
    {
      label: 'Evidence mode',
      value: normalizeText(research?.mode) || normalizeText(research?.status) || 'Paste text or research from a tag',
    },
    {
      label: 'Source details',
      value: [normalizeText(selected.author), normalizeText(selected.date), host].filter(Boolean).join(' | ') || 'No source yet',
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
}

async function researchFromTag() {
  const payload = buildRequestBody();

  if (!payload.draft_tag && !payload.source_url) {
    setStatus('Enter a draft tag or source URL before researching.', 'error');
    return;
  }

  setBusy(true);
  setStatus('Researching likely sources...', '');
  metaEl.textContent = 'Sending request to /api/research.';
  renderSourceSummary({
    selected: {
      title: payload.draft_tag || 'Research in progress',
      author: '',
      date: '',
      url: payload.source_url,
    },
    status: 'Researching likely sources',
    mode: 'Fetching and ranking candidate sources',
  });

  try {
    const response = await fetch('/api/research', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    const rawText = await response.text();
    let data = null;

    try {
      data = rawText ? JSON.parse(rawText) : null;
    } catch {
      data = rawText;
    }

    if (!response.ok) {
      const message = typeof data === 'string'
        ? data
        : data?.error?.message
          ?? data?.message
          ?? `Request failed with status ${response.status}.`;
      throw new Error(message);
    }

    const research = data?.research;
    if (!research) {
      throw new Error('No research payload was returned.');
    }

    applyResearchResult(research);
    setStatus('Found a likely source and filled the evidence form.', 'success');
    metaEl.textContent = describeResearch(research) || 'Research completed.';
  } catch (error) {
    setStatus(error instanceof Error ? error.message : 'Unable to research from the draft tag.', 'error');
    metaEl.textContent = 'The backend research endpoint may still need to be added.';
    renderSourceSummary({
      selected: {
        title: payload.draft_tag || 'Research failed',
        author: '',
        date: '',
        url: payload.source_url,
      },
      status: 'Research failed',
      mode: 'Check the backend logs or try a direct source URL',
    });
  } finally {
    setBusy(false);
  }
}

function importCardsFromText(rawText) {
  const cleaned = stripCodeFences(rawText);
  if (!cleaned) {
    throw new Error('Paste JSON before importing cards.');
  }

  const parsed = parseJsonLike(cleaned);
  const cards = extractCards(parsed);
  if (!cards.length) {
    throw new Error('No cards were found in the imported JSON.');
  }

  renderCards(cards);
  metaEl.textContent = 'Imported from ChatGPT JSON.';
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

    const sourceHost = getSourceHost(card.sourceUrl);
    const topRow = [card.shortCitation || card.citation, card.dox ? `DOA ${card.dox}` : '', sourceHost || (card.sourceUrl ? 'Source linked' : '')].filter(Boolean);
    topRow.forEach((item) => {
      const span = document.createElement('span');
      span.className = 'tag';
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

    const sections = [
      ['Source', card.sourceUrl],
      ['Read text', card.readText || card.highlightedText || card.quotedText || card.body || card.evidence || card.text],
      ['Highlighted text', card.highlightedText && card.highlightedText !== card.readText ? card.highlightedText : ''],
      ['Quoted text', card.quotedText && card.quotedText !== card.highlightedText ? card.quotedText : ''],
      ['Full context', card.fullContext],
      ['Validation', buildValidationText(card.validation)],
      ['Formatted card', card.formattedCard],
      ['Claim', card.claim],
      ['Warrant', card.warrant],
      ['Impact', card.impact],
    ].filter(([, value]) => value);

    body.replaceChildren();
    sections.forEach(([label, value]) => {
      const wrapper = document.createElement('div');
      const labelEl = document.createElement('div');
      const valueEl = document.createElement('div');

      labelEl.className = 'label';
      labelEl.textContent = label;
      valueEl.className = 'highlight';
      if (label === 'Read text') {
        valueEl.classList.add('highlight-read');
      }
      if (label === 'Formatted card') {
        valueEl.classList.add('highlight-mono');
      }
      if (label === 'Source') {
        valueEl.classList.add('highlight-url');
      }
      if (label === 'Validation') {
        valueEl.classList.add('highlight-validation');
      }
      valueEl.textContent = value;
      wrapper.append(labelEl, valueEl);
      body.appendChild(wrapper);
    });

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
  hintEl.textContent = `${cards.length} card ready.`;
  metaEl.textContent = 'Rendered from /api/cut response. Copy the formatted card for a debate file layout.';
}

function describeMeta(meta) {
  if (!meta || typeof meta !== 'object') {
    return 'Rendered from /api/cut response.';
  }

  const mode = normalizeText(meta.mode);
  const model = normalizeText(meta.model);
  const parts = [];

  if (mode) {
    parts.push(mode === 'ai' ? 'AI cut' : 'Fallback cut');
  }
  if (normalizeText(meta.provider)) {
    parts.push(normalizeText(meta.provider));
  }
  if (meta.experimental) {
    parts.push('experimental bridge');
  }
  if (model) {
    parts.push(model);
  }
  if (meta.validation_completed) {
    parts.push('validated');
  } else if (meta.validation_ran) {
    parts.push('validation fallback');
  }
  if (typeof meta.card_count === 'number') {
    parts.push(`${meta.card_count} card${meta.card_count === 1 ? '' : 's'}`);
  }

  return parts.join(' | ') || 'Rendered from /api/cut response.';
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
  const card = currentCards[0];
  if (!card) {
    return '';
  }

  const blocks = [
    'Card',
    card.formattedCard || buildFormattedCard(card),
  ];

  const analyticBlock = [
    card.claim ? `Claim: ${card.claim}` : '',
    card.warrant ? `Warrant: ${card.warrant}` : '',
    card.impact ? `Impact: ${card.impact}` : '',
    buildValidationText(card.validation) ? `Validation:\n${buildValidationText(card.validation)}` : '',
  ].filter(Boolean).join('\n');
  if (analyticBlock) {
    blocks.push(analyticBlock);
  }

  return blocks.join('\n\n');
}

copyPromptBtn.addEventListener('click', async () => {
  try {
    await copyToClipboard(buildChatgptPrompt());
    setStatus('Copied the ChatGPT prompt.', 'success');
  } catch {
    setStatus('Could not copy the prompt.', 'error');
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
  setStatus('Using the local model workflow.', '');
});

modeChatgptBtn.addEventListener('click', () => {
  setMode('chatgpt');
  syncPromptPreview();
  setStatus('Using the manual ChatGPT workflow.', '');
});

researchBtn.addEventListener('click', requestResearchMode);

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = buildRequestBody();

  if (!payload.article_text) {
    if (!payload.draft_tag) {
      setStatus('Paste source text or enter a draft tag before cutting.', 'error');
      return;
    }
    setStatus('Researching from the draft tag...', '');
  }

  setBusy(true);
  setStatus('Cutting one card...', '');
  metaEl.textContent = 'Sending request to /api/cut.';

  try {
    const response = await fetch('/api/cut', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    const rawText = await response.text();
    let data = null;

    try {
      data = rawText ? JSON.parse(rawText) : null;
    } catch {
      data = rawText;
    }

    if (!response.ok) {
      const message = typeof data === 'string'
        ? data
        : data?.error?.message
          ?? data?.message
          ?? `Request failed with status ${response.status}.`;
      throw new Error(message);
    }

    const cards = extractCards(data);
    if (!cards.length) {
      renderEmptyState();
      setStatus('No card was returned by /api/cut.', 'error');
      metaEl.textContent = 'Check the endpoint response shape.';
      return;
    }

    renderCards(cards);
    metaEl.textContent = describeMeta(data?.meta);
    setStatus('Generated 1 card.', 'success');
    if (currentMode === 'chatgpt') {
      syncPromptPreview();
    }
  } catch (error) {
    renderEmptyState();
    setStatus(error instanceof Error ? error.message : 'Unable to cut the card.', 'error');
    metaEl.textContent = 'The frontend is ready; the backend endpoint may still need to be added.';
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

renderEmptyState();
syncPromptPreview();
setMode('local');
renderSourceSummary();

Object.values(fields).forEach((field) => {
  field.addEventListener('input', syncPromptPreview);
  field.addEventListener('change', syncPromptPreview);
});
