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
4. Set your GPT name and description.
5. Paste the contents of `CUSTOM_GPT_INSTRUCTIONS.md` into the `Instructions` field.
6. In `Actions`, choose `Create new action`.
7. Import `custom_gpt_action_openapi.json`, or host that file and import it by URL.
8. Authentication:
   - choose `None` if your deployed API is public and requires no secret
   - choose `API key` if you protect the endpoint
   - choose `OAuth` only if each end user must sign in to your backend
9. Test both actions in Preview.

## Suggested GPT Metadata

### Name

Debate Card Extractor and Verbatim Exporter

### Description

Extracts debate evidence from source URLs using snippet bounds, formats debate cards, and returns a download link for a verbatim Word document.

### Conversation Starters

- Extract a card from this URL between these two snippets.
- Turn these excerpts into formatted debate cards.
- Export these final cards into a verbatim Word doc.

## Important Launch Notes

- If you publish or share a GPT with actions publicly, OpenAI requires a valid Privacy Policy URL for the action.
- A GPT can use either apps or actions, not both at once.
- In Enterprise or Edu workspaces, action domains may be restricted by workspace allowlists.

## Official Docs Used

- [Configuring actions in GPTs](https://help.openai.com/en/articles/9442513-configuring-actions-in-gpts)
- [Creating and editing GPTs](https://help.openai.com/en/articles/8554397)
- [Key Guidelines for Writing Instructions for Custom GPTs](https://help.openai.com/en/articles/9358033-key-guidelines-for-writing-instructions-for-custom-gpts)
