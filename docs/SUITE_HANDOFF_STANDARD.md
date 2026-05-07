# Suite Handoff Standard

Generated from `tenra Registry/contracts/handoff-catalog.json` by `tenra Registry/scripts/generate-suite-contract-docs.mjs`.

## App Role

disk-layout simulation and lab validation app

keep unique; Guardrail can review unsafe changes and Proxy can shape operator-facing explanations.

## Accepted Inputs

- No accepted suite contract is registered yet.

## Emitted Outputs

- `tenra-partition.lab-validation-request.v1` to lab validation, tenra Guardrail
- `tenra-partition.lab-validation-result.v1` to tenra Guardrail

## Standard Controls

- schema badge
- preview payload
- download JSON
- import history
- blocked queue
- history

## Status Vocabulary

- `draft`: Payload or route exists locally but has not been previewed.
- `previewed`: Payload was built and inspected without delivery.
- `queued`: Delivery is waiting for an endpoint, retry, or operator action.
- `sent`: Producer posted or exported the payload successfully.
- `accepted`: Consumer parsed and retained the payload.
- `rejected`: Consumer refused the payload for schema, routing, safety, or policy reasons.
- `failed`: Delivery failed before acceptance or rejection was known.
- `replayed`: Registry or a producer regenerated a prior payload for another delivery attempt.
- `received`: Consumer acknowledged receipt back to the source app.
- `dismissed`: Operator intentionally removed an item from an inbox, queue, or retry list.

## Local Storage

Prefix: `tenra.partition`

- `tenra.partition.labValidationHistory.v1`
- `tenra.partition.guardrailDecisionHistory.v1`

## Endpoints

- No suite HTTP endpoint is documented for this app yet.
