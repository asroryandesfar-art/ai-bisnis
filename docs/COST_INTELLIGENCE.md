# Cost Intelligence

BotNesia records one `cost_records` row for every successful LLM response. Cost is estimated from prompt and completion tokens and grouped by tenant, channel, conversation, agent, and model.

## Configuration

- `GROQ_CHEAP_MODEL`: economy model used for simple tasks. Default: `llama-3.1-8b-instant`.
- `GROQ_MODEL`: quality model used for complex tasks and fallback. Default: `llama-3.3-70b-versatile`.
- `AI_MODEL_PRICING_JSON`: optional JSON map with USD input/output prices per one million tokens.
- `AI_DEFAULT_INPUT_COST_PER_MILLION` and `AI_DEFAULT_OUTPUT_COST_PER_MILLION`: conservative fallback pricing for unknown models.

Example:

```json
{"custom-model":{"input":0.25,"output":0.50}}
```

Budget alerts are calculated dynamically at 80% (warning), 90% (critical), and 100% (exceeded). Budget alerts do not block customer requests.
