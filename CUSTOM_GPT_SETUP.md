# Custom GPT Setup

## Files To Use

- OpenAPI schema: [custom_gpt_action_openapi.json](/C:/Users/IsitT/OneDrive/Documents/Playground/custom_gpt_action_openapi.json)
- GPT instructions: [CUSTOM_GPT_INSTRUCTIONS.md](/C:/Users/IsitT/OneDrive/Documents/Playground/CUSTOM_GPT_INSTRUCTIONS.md)

## Before Importing

1. Deploy this server to a public HTTPS domain.
2. Replace `https://YOUR-DEPLOYED-DOMAIN.example.com` in `custom_gpt_action_openapi.json` with your real base URL.
3. Make sure that deployed server exposes:
   - `POST /api/custom-gpt/extract`
   - `POST /api/custom-gpt/export/docx`
   - optionally `GET /openapi.json`

## In ChatGPT

1. Open [chatgpt.com/gpts](https://chatgpt.com/gpts).
2. Click `Create`.
3. Open the `Configure` tab.
4. Enable `Web search` so the GPT can find sources on its own before calling the action.
5. Set your GPT name and description.
6. Paste the contents of `CUSTOM_GPT_INSTRUCTIONS.md` into the `Instructions` field.
7. In `Actions`, choose `Create new action`.
8. Import `custom_gpt_action_openapi.json`, or host that file and import it by URL.
9. Authentication:
   - choose `None` if your deployed API is public and requires no secret
   - choose `API key` if you protect the endpoint
   - choose `OAuth` only if each end user must sign in to your backend
10. Test `Web search` + `extractCardText` in Preview. Test `exportCardsDocx` only if you want `.docx` export.

## Suggested GPT Metadata

### Name

Debate Card Extractor and Verbatim Exporter

### Description

Uses ChatGPT web search to find a source for a claim, proposes a debate tag, calls `extractCardText` only to pull the exact passage from the chosen URL, and returns a formatted debate card in chat. `exportCardsDocx` is optional for later export.

### Conversation Starters

- Cut a card that says tariffs raise manufacturing costs.
- Find a source for this claim, propose a tag, and cut a card.
- Export these finished cards to a verbatim Word doc.

## Important Launch Notes

- If you publish or share a GPT with actions publicly, OpenAI requires a valid Privacy Policy URL for the action.
- A GPT can use either apps or actions, not both at once.
- In Enterprise or Edu workspaces, action domains may be restricted by workspace allowlists.
- The intended workflow is `web-first, extract-second, format-in-chat, export-optional`.

## Official Docs Used

- [Configuring actions in GPTs](https://help.openai.com/en/articles/9442513-configuring-actions-in-gpts)
- [Creating and editing GPTs](https://help.openai.com/en/articles/8554397)
- [Key Guidelines for Writing Instructions for Custom GPTs](https://help.openai.com/en/articles/9358033-key-guidelines-for-writing-instructions-for-custom-gpts)
