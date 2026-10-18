# Privacy

The tools send user-selected music prompts and the API-consumer Token to `api.acedata.cloud` over HTTPS. The Token is read from an environment variable or explicit secure input and excluded from tool serialization. The package adds no analytics or telemetry and does not enable CrewAI tracing. CrewAI, the configured LLM, and the caller may have separate telemetry or trace settings. Do not place secrets or personal data in music prompts without authorization.

Returned fields are limited to task status, the task ID, HTTPS audio result URLs and original cost. Raw request payloads and account/application identities are excluded. Optional task polling queries only the same ID. The caller controls retention, LLM context sharing and logging. Do not publish private media links or keys in bug reports.

The API and any configured LLM follow current prices and data handling terms; this package does not accept terms or create an account for the user.
