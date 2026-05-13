import { Disk, OperationPlan, SafetyReport, ValidationResult } from "../domain/types";
import { formatBytes } from "../domain/bytes";
import type { SimulationResult } from "../simulation/simulator";

export interface PartitionLabDiskLayout {
  schema: "partition-lab.disk-layout.v1";
  capturedAt: string;
  source: string;
  disk: Disk;
}

export interface PartitionLabGeometryLayout {
  schema: "partition-lab.layout.v1";
  scenario?: string;
  mode?: string;
  description?: string;
  image?: {
    path?: string;
    image_id?: string;
  };
  disk: {
    id?: string;
    path?: string;
    label: string;
    sector_size: number;
    alignment_sectors: number;
    size_bytes: number;
    partitions: PartitionLabGeometryPartition[];
  };
}

interface PartitionLabGeometryPartition {
  number: number;
  label?: string;
  name?: string;
  type?: string;
  start_sector: number;
  end_sector: number;
  filesystem?: string;
  filesystem_state?: string;
  mountpoint?: string | null;
  encrypted?: boolean;
  used_bytes?: number;
  free_bytes?: number;
  minimum_size_bytes?: number;
  movable?: boolean;
  resizable?: boolean;
}

export interface PartitionLabMetadata {
  schema: PartitionLabDiskLayout["schema"] | PartitionLabGeometryLayout["schema"];
  capturedAt: string;
  source: string;
}

export interface PartitionLabValidationRequest {
  schema: "tenra-partition.lab-validation-request.v1";
  exportedAt: string;
  source: PartitionLabMetadata;
  requestedExpansionBytes: number;
  plan: OperationPlan;
  simulation: {
    ok: boolean;
    validation: ValidationResult;
  };
  execution: {
    enabled: false;
    reason: string;
  };
}

export interface PartitionLabValidationResult {
  schema: "tenra-partition.lab-validation-result.v1";
  exportedAt: string;
  sourceRequest: PartitionLabValidationRequest;
  reviewedPlan: OperationPlan;
  simulation: {
    ok: boolean;
    validation: ValidationResult;
    disk: Disk;
  };
  review: {
    status: "reviewed" | "blocked";
    requestedPlanMatchesReviewedPlan: boolean;
    safetyPosture: SafetyReport["level"];
    differences: string[];
    execution: {
      enabled: false;
      reason: string;
    };
  };
}

export interface PartitionGuardrailDecision {
  schema: "tenra-guardrail.external-action-decision.v1";
  decidedAt: string;
  requestTraceId: string;
  decision: "allow" | "review" | "deny";
  reason: string;
  sourceReturn?: {
    app?: string;
    traceId?: string;
    expectedSchema?: string;
    action?: string;
  };
}

export function loadDiskFromPartitionLabExport(input: unknown): Disk {
  if (isPartitionLabDiskLayout(input)) {
    return input.disk;
  }
  if (isPartitionLabGeometryLayout(input)) {
    return diskFromGeometryLayout(input);
  }

  throw new Error(
    "Expected tenra Partition lab disk layout JSON with schema partition-lab.disk-layout.v1 or partition-lab.layout.v1.",
  );
}

export function readPartitionLabMetadata(input: unknown): PartitionLabMetadata {
  if (isPartitionLabDiskLayout(input)) {
    return {
      schema: input.schema,
      capturedAt: input.capturedAt,
      source: input.source,
    };
  }
  if (isPartitionLabGeometryLayout(input)) {
    return {
      schema: input.schema,
      capturedAt: new Date().toISOString(),
      source: input.image?.path ?? input.disk.path ?? `tenra Partition Lab ${input.scenario ?? "layout"}`,
    };
  }

  throw new Error(
    "Expected tenra Partition lab disk layout JSON with schema partition-lab.disk-layout.v1 or partition-lab.layout.v1.",
  );
}

export function exportOperationPlan(plan: OperationPlan): string {
  return JSON.stringify(
    {
      schema: "tenra-partition.operation-plan.v1",
      exportedAt: new Date().toISOString(),
      plan,
    },
    null,
    2,
  );
}

export function exportSafetyReport(report: SafetyReport): string {
  return JSON.stringify(
    {
      schema: "tenra-partition.safety-report.v1",
      exportedAt: new Date().toISOString(),
      report,
    },
    null,
    2,
  );
}

export function loadLabValidationRequest(input: unknown): PartitionLabValidationRequest {
  if (!isPartitionLabValidationRequest(input)) {
    throw new Error(
      "Expected read-only tenra Partition lab validation request JSON with schema tenra-partition.lab-validation-request.v1.",
    );
  }

  return input;
}

export function loadLabValidationResult(input: unknown): PartitionLabValidationResult {
  if (!isPartitionLabValidationResult(input)) {
    throw new Error(
      "Expected tenra Partition lab validation result JSON with schema tenra-partition.lab-validation-result.v1.",
    );
  }

  return input;
}

export function loadPartitionGuardrailDecision(input: unknown): PartitionGuardrailDecision {
  if (!isPartitionGuardrailDecision(input)) {
    throw new Error("Expected Guardrail decision JSON returnable to tenra Partition.");
  }

  return input;
}

export function createLabValidationResult(input: {
  sourceRequest: PartitionLabValidationRequest;
  reviewedPlan: OperationPlan;
  simulation: SimulationResult;
  executionDisabledReason: string;
}): PartitionLabValidationResult {
  const differences = compareRequestedPlanToReviewedPlan(input.sourceRequest.plan, input.reviewedPlan);
  if (input.sourceRequest.simulation.ok !== input.simulation.ok) {
    differences.push("Simulation pass/fail changed between request and review.");
  }
  if (input.sourceRequest.simulation.validation.summary !== input.simulation.validation.summary) {
    differences.push("Simulation validation summary changed between request and review.");
  }

  return {
    schema: "tenra-partition.lab-validation-result.v1",
    exportedAt: new Date().toISOString(),
    sourceRequest: input.sourceRequest,
    reviewedPlan: input.reviewedPlan,
    simulation: {
      ok: input.simulation.ok,
      validation: input.simulation.validation,
      disk: input.simulation.disk,
    },
    review: {
      status: input.simulation.ok && differences.length === 0 ? "reviewed" : "blocked",
      requestedPlanMatchesReviewedPlan: differences.length === 0,
      safetyPosture: input.reviewedPlan.safetyReport.level,
      differences,
      execution: {
        enabled: false,
        reason: input.executionDisabledReason,
      },
    },
  };
}

export function createGuardrailReviewFromLabResult(input: {
  result: PartitionLabValidationResult;
}) {
  const { result } = input;

  return {
    schema: "tenra-guardrail.external-action-review.v1",
    exportedAt: new Date().toISOString(),
    sourceApp: "partition",
    actionKind: "execute-system-change",
    actorLabel: "Partition lab validation",
    targetLabel: result.sourceRequest.plan.id,
    summary:
      result.review.status === "blocked"
        ? "Partition lab validation blocked a disk operation. Execution must remain disabled until Guardrail and a human operator review it."
        : "Partition lab validation reviewed a disk operation. Execution remains disabled in the local app.",
    evidence: [
      { label: "Review status", value: result.review.status },
      { label: "Safety posture", value: result.review.safetyPosture },
      { label: "Simulation", value: result.simulation.ok ? "passed" : "blocked" },
      {
        label: "Differences",
        value: result.review.differences.length ? result.review.differences.join("; ") : "none",
      },
    ],
    recommendedDecision: result.review.status === "blocked" ? "deny" : "review",
    traceId: `partition-lab-${result.sourceRequest.plan.id}`,
  };
}

function compareRequestedPlanToReviewedPlan(
  requested: OperationPlan,
  reviewed: OperationPlan,
): string[] {
  const differences: string[] = [];

  if (requested.id !== reviewed.id) {
    differences.push("Plan id changed between request and review.");
  }
  if (requested.requestedExpansionBytes !== reviewed.requestedExpansionBytes) {
    differences.push("Requested expansion size changed between request and review.");
  }
  if (requested.operations.length !== reviewed.operations.length) {
    differences.push("Operation count changed between request and review.");
  }
  requested.operations.forEach((operation, index) => {
    const reviewedOperation = reviewed.operations[index];
    if (!reviewedOperation) return;
    if (operation.type !== reviewedOperation.type || operation.partitionId !== reviewedOperation.partitionId) {
      differences.push(`Operation ${index + 1} changed from ${operation.type} to ${reviewedOperation.type}.`);
    }
  });
  if (requested.safetyReport.level !== reviewed.safetyReport.level) {
    differences.push("Safety level changed between request and review.");
  }

  return differences;
}

export function createHumanReadableSummary(plan: OperationPlan): string {
  const lines = [
    "tenra Partition operation summary",
    "",
    `Workflow: Give ${formatBytes(plan.requestedExpansionBytes)} from E: to C:`,
    `Status: ${plan.status}`,
    `Movement required: ${plan.requiresMovement ? "yes" : "no"}`,
    "",
    "Planner explanation:",
    plan.explanation,
    "",
    "Operation queue:",
    ...plan.operations.map(
      (operation, index) => `${index + 1}. ${operation.title} - ${operation.description}`,
    ),
    "",
    "Safety findings:",
    ...(plan.safetyReport.findings.length === 0
      ? ["No blocking findings for read-only simulation."]
      : plan.safetyReport.findings.map(
          (finding) => `${finding.severity.toUpperCase()}: ${finding.message}`,
        )),
    "",
    "Execution:",
    "Execution is not available until the integrated lab harness proves the operation against disposable images.",
  ];

  return lines.join("\n");
}

function isPartitionLabDiskLayout(input: unknown): input is PartitionLabDiskLayout {
  if (!input || typeof input !== "object") return false;
  const candidate = input as Partial<PartitionLabDiskLayout>;
  return (
    candidate.schema === "partition-lab.disk-layout.v1" &&
    typeof candidate.capturedAt === "string" &&
    typeof candidate.source === "string" &&
    isDisk(candidate.disk)
  );
}

function isPartitionLabGeometryLayout(input: unknown): input is PartitionLabGeometryLayout {
  if (!input || typeof input !== "object") return false;
  const candidate = input as Partial<PartitionLabGeometryLayout>;
  return (
    candidate.schema === "partition-lab.layout.v1" &&
    Boolean(candidate.disk && typeof candidate.disk === "object") &&
    typeof candidate.disk?.label === "string" &&
    typeof candidate.disk.sector_size === "number" &&
    typeof candidate.disk.alignment_sectors === "number" &&
    typeof candidate.disk.size_bytes === "number" &&
    Array.isArray(candidate.disk.partitions)
  );
}

function diskFromGeometryLayout(layout: PartitionLabGeometryLayout): Disk {
  const sectorSizeBytes = layout.disk.sector_size;
  const alignmentBytes = layout.disk.alignment_sectors * sectorSizeBytes;
  const scheme = layout.disk.label.toLowerCase() === "gpt" ? "GPT" : "MBR";
  const id = layout.disk.id ?? layout.image?.image_id ?? layout.scenario ?? "lab-raw-image";

  return {
    id,
    name: layout.scenario ?? layout.disk.path ?? "Lab raw image",
    sizeBytes: layout.disk.size_bytes,
    sectorSizeBytes,
    alignmentBytes,
    scheme,
    partitions: layout.disk.partitions.map((partition) =>
      partitionFromGeometryLayout(partition, sectorSizeBytes, alignmentBytes),
    ),
  };
}

function partitionFromGeometryLayout(
  partition: PartitionLabGeometryPartition,
  sectorSizeBytes: number,
  alignmentBytes: number,
) {
  const label = partition.label ?? partition.name ?? `Partition ${partition.number}`;
  const startByte = partition.start_sector * sectorSizeBytes;
  const sizeBytes = (partition.end_sector - partition.start_sector + 1) * sectorSizeBytes;
  const usedBytes = partition.used_bytes ?? Math.max(0, sizeBytes - (partition.free_bytes ?? 0));
  const minimumSizeBytes =
    partition.minimum_size_bytes ?? Math.min(sizeBytes, usedBytes + alignmentBytes);

  return {
    id: `lab-part-${partition.number}-${label.toLowerCase()}`,
    number: partition.number,
    name: partition.name ?? label,
    letter: /^[A-Za-z]$/.test(label) ? label.toUpperCase() : undefined,
    startByte,
    sizeBytes,
    filesystem: {
      type: (partition.filesystem ?? "unknown").toLowerCase(),
      label,
      totalBytes: sizeBytes,
      usedBytes,
      minimumSizeBytes,
    },
    mounted: Boolean(partition.mountpoint),
    encrypted: Boolean(partition.encrypted),
    dirty: Boolean(partition.filesystem_state && partition.filesystem_state !== "clean"),
    movable: partition.movable ?? label.toUpperCase() === "E",
    resizable: partition.resizable ?? ["C", "E"].includes(label.toUpperCase()),
  };
}

function isPartitionLabValidationResult(input: unknown): input is PartitionLabValidationResult {
  if (!input || typeof input !== "object") return false;
  const candidate = input as Partial<PartitionLabValidationResult>;
  return (
    candidate.schema === "tenra-partition.lab-validation-result.v1" &&
    typeof candidate.exportedAt === "string" &&
    Boolean(candidate.sourceRequest) &&
    Boolean(candidate.reviewedPlan) &&
    Boolean(candidate.simulation) &&
    Boolean(candidate.review)
  );
}

function isPartitionGuardrailDecision(input: unknown): input is PartitionGuardrailDecision {
  if (!input || typeof input !== "object") return false;
  const candidate = input as Partial<PartitionGuardrailDecision>;
  return (
    candidate.schema === "tenra-guardrail.external-action-decision.v1" &&
    typeof candidate.decidedAt === "string" &&
    typeof candidate.requestTraceId === "string" &&
    (candidate.decision === "allow" || candidate.decision === "review" || candidate.decision === "deny") &&
    typeof candidate.reason === "string" &&
    candidate.sourceReturn?.app === "partition" &&
    candidate.sourceReturn.action === "apply-guardrail-decision"
  );
}

function isDisk(input: unknown): input is Disk {
  if (!input || typeof input !== "object") return false;
  const disk = input as Partial<Disk>;
  return (
    typeof disk.id === "string" &&
    typeof disk.name === "string" &&
    typeof disk.sizeBytes === "number" &&
    typeof disk.sectorSizeBytes === "number" &&
    typeof disk.alignmentBytes === "number" &&
    (disk.scheme === "GPT" || disk.scheme === "MBR") &&
    Array.isArray(disk.partitions)
  );
}

function isPartitionLabValidationRequest(input: unknown): input is PartitionLabValidationRequest {
  if (!input || typeof input !== "object") return false;
  const candidate = input as Partial<PartitionLabValidationRequest>;
  return (
    candidate.schema === "tenra-partition.lab-validation-request.v1" &&
    typeof candidate.exportedAt === "string" &&
    (candidate.source?.schema === "partition-lab.disk-layout.v1" ||
      candidate.source?.schema === "partition-lab.layout.v1") &&
    typeof candidate.source.capturedAt === "string" &&
    typeof candidate.source.source === "string" &&
    typeof candidate.requestedExpansionBytes === "number" &&
    Boolean(candidate.plan && typeof candidate.plan === "object") &&
    typeof candidate.simulation?.ok === "boolean" &&
    Boolean(candidate.simulation.validation && typeof candidate.simulation.validation === "object") &&
    candidate.execution?.enabled === false &&
    typeof candidate.execution.reason === "string" &&
    candidate.execution.reason.length > 0
  );
}
