# Azure OpenAI Entra acceptance record (sanitized)

One application-level request through the real NEXUS Azure OpenAI adapter. The harness that ran it was temporary and is
not part of the repository. Context and limits: `docs/azure-openai-provider.md`, ADR 0006.

| Item | Value |
|---|---|
| Date | 2026-10-02 |
| Region | South India |
| Deployment type | regional Standard |
| Model | gpt-4.1-mini 2025-04-14 |
| Endpoint path | `/openai/v1/chat/completions` |
| Selected Entra scope | `https://ai.azure.com/.default` |
| Credential used | Azure CLI user credential (through the adapter's `DefaultAzureCredential` path) |
| Token acquisitions | 1 |
| Provider requests | 1 (`POST`, `max_completion_tokens` 16, no tools, 30 s timeout, no retry) |
| Result | success |
| Output and streamed text | `OK` |
| Usage | 11 input tokens, 1 output token |
| Observed latency | 3166 ms |
| Tool invocations | 0 |
| Budget | one hold reserved and settled once (`committed`); the ledger records 1 internal cent, the minimum accounting unit, which is not an Azure retail charge |
| Credential or token found in output, logs, audit rows or tool rows | none detected |

## Limits of this evidence

- The test used an Azure CLI **user** credential. Managed-identity and service-principal authentication are **unverified**
  and must be validated in the deployed environment.
- One latency observation is not a benchmark.
- One request, one user principal, one tenant, one region. Other regions, tenants and endpoint families are unverified.
- The earlier scope probe showed both `https://cognitiveservices.azure.com/.default` and `https://ai.azure.com/.default`
  returning HTTP 200. NEXUS deliberately selects `ai.azure.com`; this record does not claim the other scope is invalid.
- Production enablement is a separate decision. The provider remains disabled by default.

Deliberately omitted: tenant, subscription, principal, resource and role-assignment identifiers, tokens and request
headers.
