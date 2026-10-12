# LLM provider registrations

Ontology Studio routes discovery and knowledge-graph extraction through the
`LLMProvider` protocol. Provider-specific SDKs and request formats are isolated in
`backend/app/modules/llm/providers.py`; domain workflows receive schema-validated
Pydantic results and do not depend on a vendor SDK.

## Supported registrations

| Provider | Endpoint and protocol | Connection check |
| --- | --- | --- |
| OpenAI | Direct OpenAI API; Chat Completions for standard models and Responses for recognized reasoning models | Authenticated model lookup |
| Anthropic | Native Messages API with JSON-schema output | Authenticated minimal Messages request |
| Azure AI Foundry | Azure OpenAI v1, OpenAI-compatible Foundry deployments, or Anthropic Foundry deployments; API key or Microsoft Entra ID where supported | Authenticated lookup or minimal inference request, depending on API |
| Ollama | Ollama's OpenAI-compatible `/v1` generation endpoint | Native `/api/show` request verifies the configured model |
| OpenAI-compatible | Existing compatible endpoint behavior, including older database registrations | Existing compatible provider check |

The Azure deployment/API type is selected explicitly in Settings. The adapter does
not treat every Foundry deployment as interchangeable: Azure OpenAI, compatible
Foundry models, and Anthropic Foundry use different request clients and endpoint
conventions. Deployment names and API-version requirements are controlled by the
configured Azure resource and model deployment.

## Credentials and endpoint configuration

The registry stores only a credential environment-variable name (for example,
`MY_PROVIDER_KEY`), never the credential value. The server resolves the value when
creating a provider: first from the process environment, then from the git-ignored
`.env` files that also configure the application (`backend/.env` before the repository
`.env`). Edits to `.env` are picked up without a restart. Read APIs and KG build
snapshots expose provider/model and
non-secret inference metadata only. Microsoft Entra ID uses the server's default
Azure credential chain and does not require a stored API-key reference.

Direct OpenAI and Anthropic endpoints default to their vendor APIs. Ollama defaults
to `http://localhost:11434`; local Ollama can use HTTP, while remote non-local
providers must use HTTPS. Existing `openai-compatible` rows are preserved as-is for
backward compatibility. Their endpoint is administrator-managed and is not rewritten
by the multi-provider migration.

Inference settings are validated against the selected provider's supported
parameters. Unsupported provider settings are rejected rather than silently dropped.
The application makes no claim that an endpoint is reachable merely because it was
registered; use **Test connection** to run an actual provider-specific request.

## Selection and migration

Projects may set distinct defaults for ontology discovery and KG extraction. A build's
explicit LLM selection takes precedence over the applicable project default, followed
by the server's environment default. If no provider is configured, operations that
require one report an explicit unavailable/configuration error; no synthetic model
result is substituted.

Migration `0009` adds provider-specific settings and activation state to registered
LLMs and adds discovery/KG project defaults. It copies the former shared project
default into both new purpose-specific fields. Existing OpenAI-compatible rows remain
valid. When a project has no registered model selected, `env-default` remains the
fallback.

## Operational notes

- Install the backend optional runtime dependencies from `backend/pyproject.toml`
  when deploying these providers.
- Use the Settings connection test to diagnose network, credential, model, and
  deployment access. Error messages are deliberately sanitized and do not echo
  credential-bearing SDK errors.
- Azure Entra authentication depends on the host's configured Azure credential chain
  and the identity's access to the selected Foundry resource.
- Provider model catalogs and capabilities can change. The registry intentionally
  accepts a configured model/deployment identifier rather than inventing or
  maintaining a hardcoded business/domain model catalog.