# BotNesia Frontend

Production dashboard assets are served directly by the existing FastAPI app. No separate frontend build step or replacement backend is required.

## Run

1. Configure the existing `.env` values for PostgreSQL, JWT, and the AI provider.
2. Start BotNesia from the repository root:

   ```bash
   python3 run_server.py
   ```

3. Open `http://127.0.0.1:8000/dashboard`.

The UI uses the existing authentication, tenant, agent, conversation, analytics, billing, RBAC, knowledge, channel, and voice APIs. Microphone transcription requires browser microphone permission and a configured `GROQ_API_KEY`. Spoken replies use the browser Web Speech API.

## Structure

- `index.html`: authentication and application shell
- `styles.css`: responsive enterprise design system
- `components.js`: reusable UI components
- `api-client.js`: authenticated FastAPI integration layer
- `app.js`: routes, page rendering, state, charts, and interactions
