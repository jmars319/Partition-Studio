import { Disk, OperationPlan, SafetyReport } from "../domain/types";
import { formatBytes } from "../domain/bytes";

export interface PartitionLabDiskLayout {
  schema: "partition-lab.disk-layout.v1";
  capturedAt: string;
  source: string;
  disk: Disk;
}

export interface PartitionLabMetadata {
  schema: PartitionLabDiskLayout["schema"];
  capturedAt: string;
  source: string;
}

export function loadDiskFromPartitionLabExport(input: unknown): Disk {
  if (!isPartitionLabDiskLayout(input)) {
    throw new Error("Expected tenra Partition lab disk layout JSON with schema partition-lab.disk-layout.v1.");
  }

  return input.disk;
}

export function readPartitionLabMetadata(input: unknown): PartitionLabMetadata {
  if (!isPartitionLabDiskLayout(input)) {
    throw new Error("Expected tenra Partition lab disk layout JSON with schema partition-lab.disk-layout.v1.");
  }

  return {
    schema: input.schema,
    capturedAt: input.capturedAt,
    source: input.source,
  };
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
