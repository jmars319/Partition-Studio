import { describe, expect, it } from "vitest";
import ceFixture from "../fixtures/partition-lab-ce-layout.json";
import { gibToBytes } from "../src/domain/bytes";
import {
  createGuardrailReviewFromLabResult,
  createLabValidationResult,
  loadDiskFromPartitionLabExport,
  loadLabValidationRequest,
  loadLabValidationResult,
  loadPartitionGuardrailDecision,
  readPartitionLabMetadata,
} from "../src/io/partitionLab";
import { planGiveSpaceToTarget } from "../src/planner/giveSpacePlanner";
import { simulateOperationPlan } from "../src/simulation/simulator";

describe("lab validation request import", () => {
  it("accepts read-only lab requests and refuses execution-enabled requests", () => {
    const disk = loadDiskFromPartitionLabExport(ceFixture);
    const plan = planGiveSpaceToTarget({
      disk,
      sourceLetter: "E",
      targetLetter: "C",
      expansionBytes: gibToBytes(40),
    });
    const simulation = simulateOperationPlan(plan);
    const request = {
      schema: "tenra-partition.lab-validation-request.v1",
      exportedAt: "2026-05-06T17:30:00.000Z",
      source: readPartitionLabMetadata(ceFixture),
      requestedExpansionBytes: plan.requestedExpansionBytes,
      plan,
      simulation: {
        ok: simulation.ok,
        validation: simulation.validation,
      },
      execution: {
        enabled: false,
        reason: "Execution is disabled until disposable-image validation is proven.",
      },
    };

    expect(loadLabValidationRequest(request).execution.enabled).toBe(false);

    expect(() =>
      loadLabValidationRequest({
        ...request,
        execution: { enabled: true, reason: "unsafe" },
      }),
    ).toThrow(/read-only tenra Partition lab validation request/);
  });
});

describe("lab validation result handoffs", () => {
  it("imports lab results and exports blocked Guardrail review requests", () => {
    const disk = loadDiskFromPartitionLabExport(ceFixture);
    const plan = planGiveSpaceToTarget({
      disk,
      sourceLetter: "E",
      targetLetter: "C",
      expansionBytes: gibToBytes(40),
    });
    const simulation = simulateOperationPlan(plan);
    const request = loadLabValidationRequest({
      schema: "tenra-partition.lab-validation-request.v1",
      exportedAt: "2026-05-06T17:30:00.000Z",
      source: readPartitionLabMetadata(ceFixture),
      requestedExpansionBytes: plan.requestedExpansionBytes,
      plan,
      simulation: {
        ok: simulation.ok,
        validation: simulation.validation,
      },
      execution: {
        enabled: false,
        reason: "Execution is disabled until disposable-image validation is proven.",
      },
    });
    const result = createLabValidationResult({
      sourceRequest: request,
      reviewedPlan: plan,
      simulation,
      executionDisabledReason: "Execution remains disabled.",
    });
    const blockedResult = loadLabValidationResult({
      ...result,
      review: {
        ...result.review,
        status: "blocked",
        differences: ["Fixture blocked this handoff for Guardrail export coverage."],
      },
    });
    const review = createGuardrailReviewFromLabResult({ result: blockedResult });

    expect(blockedResult.review.status).toBe("blocked");
    expect(review.schema).toBe("tenra-guardrail.external-action-review.v1");
    expect(review.sourceApp).toBe("partition");
    expect(review.recommendedDecision).toBe("deny");
  });

  it("imports Guardrail allow and deny decisions for blocked lab reviews", () => {
    const baseDecision = {
      schema: "tenra-guardrail.external-action-decision.v1",
      decidedAt: "2026-05-06T18:00:00.000Z",
      requestTraceId: "partition-lab-plan-demo",
      reason: "Reviewed by operator.",
      sourceReturn: {
        app: "partition",
        traceId: "partition-lab-plan-demo",
        expectedSchema: "tenra-partition.lab-validation-result.v1",
        action: "apply-guardrail-decision",
      },
    };

    expect(loadPartitionGuardrailDecision({ ...baseDecision, decision: "allow" }).decision).toBe("allow");
    expect(loadPartitionGuardrailDecision({ ...baseDecision, decision: "deny" }).decision).toBe("deny");
    expect(() =>
      loadPartitionGuardrailDecision({
        ...baseDecision,
        decision: "allow",
        sourceReturn: { ...baseDecision.sourceReturn, app: "align" },
      }),
    ).toThrow(/returnable to tenra Partition/);
  });
});
