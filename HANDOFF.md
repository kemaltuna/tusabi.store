# Handoff Notes

## Current state
- Queue system removed; admin endpoint now uses `GeminiClient` in Vertex/ADC mode (set `GEMINI_USE_VERTEX=true` plus project/location or fallback to API key pool).
- Background job manager, batch queue files, and legacy scripts deleted.
- Frontend generation UI shows generated question IDs + JSON download; job monitor/batch sections removed.
- Gemini prompts already include the requested rules (buffer, source authority, leakage, discipline focus, etc.).

## Next steps for new session
1. Confirm `.env`/deployment sets `GEMINI_USE_VERTEX=true`, `VERTEX_PROJECT`, `VERTEX_LOCATION` (default `us-central1`), and that `gcloud auth application-default login` or service-account ADC is available.
2. Run existing integration/test suites around `/new_web_app/backend/tests/test_generation_v2.py` if needed.
3. Rebuild/restart backend to ensure dependencies and new environment variables are honored.

## Tips
- If you want to revert to GEMINI_API_KEY mode (local dev without ADC), set `GEMINI_USE_VERTEX=false` and provide at least one key in `GEMINI_API_KEY` or `GEMINI_API_KEY_*`.
- For Vertex admins: ensure service account has Vertex AI User + Storage Admin and `GOOGLE_CLOUD_PROJECT` matches the project used in `gcloud config`.
