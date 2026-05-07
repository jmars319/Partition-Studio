# Module Manifest

Generated from `tenra Registry/contracts/handoff-catalog.json` by `tenra Registry/scripts/generate-suite-contract-docs.mjs`.

## Standalone Mode

Runs as a complete partition planning and lab validation app with local simulation, refusal checks, safety review, and result queues.

## Required Suite Dependencies

- None

## Optional Suite Dependencies

- tenra Guardrail: Optional external review for blocked or unsafe lab results.
- tenra Proxy: Optional operator-facing explanation shaping.

## Provides

- lab validation request
- lab validation result
- blocked result queue

## Consumes

- guardrail decision

## Contracts

Emits:

- `tenra-partition.lab-validation-request.v1`
- `tenra-partition.lab-validation-result.v1`

Accepts:

- None

## Rules

- Each app must remain complete and usable without another tenra app running.
- Suite integrations are optional module links, not required runtime dependencies.
- Shared functions should be exposed through explicit local APIs, exports, imports, or schemas.
- No app may read another app's private filesystem, database, or localStorage state.
- Registry can index and audit the module graph, but it must not become a hidden runtime bus.
