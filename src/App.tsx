import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  Download,
  FileJson,
  FileText,
  HardDrive,
  Lock,
  ShieldAlert,
  ShieldCheck,
  Upload,
} from "lucide-react";
import { type ChangeEvent, useMemo, useRef, useState } from "react";
import "./App.css";
import labFixture from "../fixtures/partition-lab-ce-layout.json";
import {
  createHumanReadableSummary,
  loadDiskFromPartitionLabExport,
  readPartitionLabMetadata,
  type PartitionLabMetadata,
} from "./io/partitionLab";
import { planGiveSpaceToTarget } from "./planner/giveSpacePlanner";
import { simulateOperationPlan } from "./simulation/simulator";
import {
  Disk,
  Partition,
  SafetyFinding,
} from "./domain/types";
import {
  formatBytes,
  gibToBytes,
  percentage,
} from "./domain/bytes";
import { cloneDisk, getPartitionEnd, sortPartitions } from "./domain/layout";

const fixtureDisk = loadDiskFromPartitionLabExport(labFixture);
const fixtureLabMetadata = readPartitionLabMetadata(labFixture);
const EXECUTION_DISABLED_REASON =
  "Execution is not available until the integrated lab harness proves this operation against disposable images.";

type ExportFormat = "plan-json" | "report-json" | "summary";

type LabCommand = {
  id: string;
  label: string;
  command: string;
};

const labCommands: LabCommand[] = [
  {
    id: "smoke",
    label: "POSIX smoke",
    command: "npm run lab:smoke:posix",
  },
  {
    id: "plan",
    label: "Fixture plan",
    command:
      "cd lab && scripts/plan_operation.py --layout fixtures/normal-c-e-layout.json --increase-c 40G",
  },
  {
    id: "ui",
    label: "Lab UI",
    command: "cd lab && scripts/start_ui.sh --open",
  },
];

function App() {
  const [disk, setDisk] = useState<Disk>(() => cloneDisk(fixtureDisk));
  const [labMetadata, setLabMetadata] = useState<PartitionLabMetadata>(() => fixtureLabMetadata);
  const [desiredGiB, setDesiredGiB] = useState(64);
  const [importError, setImportError] = useState("");
  const [copiedCommandId, setCopiedCommandId] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const plan = useMemo(
    () =>
      planGiveSpaceToTarget({
        disk,
        sourceLetter: "E",
        targetLetter: "C",
        expansionBytes: gibToBytes(desiredGiB),
      }),
    [desiredGiB, disk],
  );

  const simulation = useMemo(() => simulateOperationPlan(plan), [plan]);
  const afterDisk = simulation.ok ? simulation.disk : undefined;
  const blockingCount = plan.safetyReport.findings.filter(
    (finding) => finding.severity === "blocking",
  ).length;

  async function handleImport(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    if (!file) return;

    try {
      const json = JSON.parse(await file.text());
      setDisk(loadDiskFromPartitionLabExport(json));
      setLabMetadata(readPartitionLabMetadata(json));
      setImportError("");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown import error.";
      setImportError(message);
    } finally {
      event.currentTarget.value = "";
    }
  }

  function resetFixture() {
    setDisk(cloneDisk(fixtureDisk));
    setLabMetadata(fixtureLabMetadata);
    setImportError("");
  }

  function exportPlan(format: ExportFormat) {
    const filenameBase = `${plan.id}-${format}`;
    if (format === "plan-json") {
      downloadFile(
        `${filenameBase}.json`,
        JSON.stringify(plan, null, 2),
        "application/json",
      );
      return;
    }

    if (format === "report-json") {
      downloadFile(
        `${filenameBase}.json`,
        JSON.stringify(plan.safetyReport, null, 2),
        "application/json",
      );
      return;
    }

    downloadFile(`${filenameBase}.txt`, createHumanReadableSummary(plan), "text/plain");
  }

  async function copyLabCommand(command: LabCommand) {
    await navigator.clipboard.writeText(command.command);
    setCopiedCommandId(command.id);
    window.setTimeout(() => setCopiedCommandId(""), 1800);
  }

  function exportLabRequest() {
    downloadFile(
      `${plan.id}-lab-validation-request.json`,
      JSON.stringify(
        {
          schema: "tenra-partition.lab-validation-request.v1",
          exportedAt: new Date().toISOString(),
          source: labMetadata,
          requestedExpansionBytes: plan.requestedExpansionBytes,
          plan,
          simulation: {
            ok: simulation.ok,
            validation: simulation.validation,
          },
          execution: {
            enabled: false,
            reason: EXECUTION_DISABLED_REASON,
          },
        },
        null,
        2,
      ),
      "application/json",
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            TP
          </div>
          <div>
            <h1>tenra Partition</h1>
            <p>Read-only planner</p>
          </div>
        </div>

        <nav className="workflow-list" aria-label="Workflow">
          <button className="workflow-item workflow-item-active" type="button">
            <HardDrive size={18} />
            <span>Give space from E to C</span>
          </button>
          <button className="workflow-item" type="button" disabled>
            <Lock size={18} />
            <span>Execution locked</span>
          </button>
          <button className="workflow-item" type="button">
            <ShieldCheck size={18} />
            <span>Lab harness visible</span>
          </button>
        </nav>

        <section className="sidebar-section">
          <h2>Disk input</h2>
          <input
            ref={fileInputRef}
            className="visually-hidden"
            type="file"
            accept="application/json,.json"
            onChange={handleImport}
          />
          <div className="button-grid">
            <button type="button" onClick={() => fileInputRef.current?.click()}>
              <Upload size={16} />
              Import JSON
            </button>
            <button type="button" onClick={resetFixture}>
              <FileJson size={16} />
              Mock C/E layout
            </button>
          </div>
          {importError ? <p className="import-error">{importError}</p> : null}
        </section>

        <section className="sidebar-section">
          <h2>Export</h2>
          <div className="button-grid">
            <button type="button" onClick={() => exportPlan("plan-json")}>
              <Download size={16} />
              Plan JSON
            </button>
            <button type="button" onClick={() => exportPlan("report-json")}>
              <ShieldCheck size={16} />
              Safety JSON
            </button>
            <button type="button" onClick={() => exportPlan("summary")}>
              <FileText size={16} />
              Summary
            </button>
          </div>
        </section>

        <section className="sidebar-section boundary-note">
          <h2>Boundary</h2>
          <p>The planner and lab harness now live in one app. Execution stays locked until disposable-image validation proves the workflow.</p>
        </section>
      </aside>

      <section className="workspace" aria-label="Partition planning workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">{disk.name}</p>
            <h2>{formatBytes(disk.sizeBytes)} {disk.scheme} disk</h2>
          </div>
          <div className={`plan-status plan-status-${plan.status}`}>
            {plan.status === "ready" ? <CheckCircle2 size={18} /> : <ShieldAlert size={18} />}
            <span>{plan.status === "ready" ? "Plan ready" : "Plan refused"}</span>
          </div>
        </header>

        <section className="plan-grid">
          <section className="primary-column">
            <section className="surface">
              <SectionHeader
                title="Before"
                subtitle="Imported layout from the read-only scanner abstraction"
              />
              <DiskMap disk={disk} selectedLetters={["C", "E"]} />
            </section>

            <section className="surface">
              <SectionHeader
                title="After simulation"
                subtitle={
                  afterDisk
                    ? "In-memory result after applying the operation queue"
                    : "Simulation is unavailable until blocking findings are resolved"
                }
              />
              <DiskMap disk={afterDisk ?? disk} selectedLetters={["C", "E"]} muted={!afterDisk} />
              {simulation.ok ? (
                <p className="validation-note">{simulation.validation.summary}</p>
              ) : (
                <p className="validation-note validation-note-blocked">
                  {simulation.validation.summary}
                </p>
              )}
            </section>

            <section className="partition-list">
              {sortPartitions(disk.partitions).map((partition) => (
                <PartitionCard key={partition.id} partition={partition} />
              ))}
            </section>
          </section>

          <aside className="inspector">
            <section className="surface">
              <SectionHeader title="Workflow" subtitle="Give space from E to C" />
              <label className="input-label" htmlFor="desired-size">
                Desired C expansion
              </label>
              <div className="size-control">
                <input
                  id="desired-size"
                  min={1}
                  max={256}
                  step={1}
                  type="number"
                  value={desiredGiB}
                  onChange={(event) => setDesiredGiB(Number(event.currentTarget.value))}
                />
                <span>GiB</span>
              </div>
              <div className="concept-rule">
                <AlertTriangle size={18} />
                <p>{plan.explanation}</p>
              </div>
            </section>

            <section className="surface">
              <SectionHeader
                title="Safety report"
                subtitle={
                  blockingCount > 0
                    ? `${blockingCount} blocking finding${blockingCount === 1 ? "" : "s"}`
                    : "No blocking findings for the mock plan"
                }
              />
              <SafetyReport findings={plan.safetyReport.findings} />
            </section>

            <LabStatusPanel
              metadata={labMetadata}
              planStatus={plan.status}
              simulationOk={simulation.ok}
              commands={labCommands}
              copiedCommandId={copiedCommandId}
              onCopyCommand={copyLabCommand}
              onExportLabRequest={exportLabRequest}
            />

            <button className="execute-button" type="button" disabled>
              <Lock size={18} />
              Execute disabled
            </button>
            <p className="execute-reason">{EXECUTION_DISABLED_REASON}</p>

            <section className="surface">
              <SectionHeader
                title="Operation queue"
                subtitle={`${plan.operations.length} planned read-only steps`}
              />
              <ol className="operation-list">
                {plan.operations.map((operation, index) => (
                  <li key={operation.id}>
                    <span>{index + 1}</span>
                    <div>
                      <h3>{operation.title}</h3>
                      <p>{operation.description}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          </aside>
        </section>
      </section>
    </main>
  );
}

function LabStatusPanel({
  metadata,
  planStatus,
  simulationOk,
  commands,
  copiedCommandId,
  onCopyCommand,
  onExportLabRequest,
}: {
  metadata: PartitionLabMetadata;
  planStatus: string;
  simulationOk: boolean;
  commands: LabCommand[];
  copiedCommandId: string;
  onCopyCommand: (command: LabCommand) => void;
  onExportLabRequest: () => void;
}) {
  const stages = [
    {
      label: "Layout imported",
      detail: `${metadata.source} · ${formatTimestamp(metadata.capturedAt)}`,
      status: "ready",
    },
    {
      label: "Planner compared C and E",
      detail:
        planStatus === "ready"
          ? "The current mock layout has a complete read-only operation queue."
          : "The current layout is blocked before execution can be considered.",
      status: planStatus === "ready" ? "ready" : "blocked",
    },
    {
      label: "Simulation replay",
      detail: simulationOk
        ? "Studio can render the modeled after-state without touching a disk."
        : "Simulation waits for blocking safety findings to clear.",
      status: simulationOk ? "ready" : "blocked",
    },
    {
      label: "Lab execution gate",
      detail:
        "Disposable VHDX/raw-image mutation remains locked until Partition Lab validates the full backend path.",
      status: "locked",
    },
  ];

  return (
    <section className="surface lab-panel">
      <SectionHeader
        title="Partition Lab"
        subtitle="Visible validation bridge for the destructive-test harness"
      />
      <div className="lab-summary">
        <div>
          <span>Mode</span>
          <strong>Mock fixture / imported Lab JSON</strong>
        </div>
        <div>
          <span>Execution</span>
          <strong>Locked</strong>
        </div>
      </div>
      <ol className="lab-stage-list">
        {stages.map((stage, index) => (
          <li className={`lab-stage lab-stage-${stage.status}`} key={stage.label}>
            <span>{index + 1}</span>
            <div>
              <h3>{stage.label}</h3>
              <p>{stage.detail}</p>
            </div>
          </li>
        ))}
      </ol>
      <div className="lab-actions">
        <button type="button" onClick={onExportLabRequest}>
          <Download size={16} />
          Lab request
        </button>
        {commands.map((command) => (
          <button
            key={command.id}
            type="button"
            onClick={() => onCopyCommand(command)}
          >
            <Clipboard size={16} />
            {copiedCommandId === command.id ? "Copied" : command.label}
          </button>
        ))}
      </div>
    </section>
  );
}

function SectionHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <header className="section-header">
      <h2>{title}</h2>
      <p>{subtitle}</p>
    </header>
  );
}

function DiskMap({
  disk,
  selectedLetters,
  muted = false,
}: {
  disk: Disk;
  selectedLetters: string[];
  muted?: boolean;
}) {
  const blocks = buildDiskBlocks(disk);

  return (
    <div className={`disk-map ${muted ? "disk-map-muted" : ""}`}>
      {blocks.map((block) => {
        const width = Math.max(percentage(block.sizeBytes, disk.sizeBytes), 2.2);
        const isSelected =
          block.partition?.letter && selectedLetters.includes(block.partition.letter);
        return (
          <div
            className={`disk-block disk-block-${block.kind} ${
              isSelected ? "disk-block-selected" : ""
            }`}
            key={block.id}
            style={{ width: `${width}%` }}
            title={`${block.label}: ${formatBytes(block.sizeBytes)}`}
          >
            <span>{block.label}</span>
            <small>{formatBytes(block.sizeBytes)}</small>
          </div>
        );
      })}
    </div>
  );
}

function PartitionCard({ partition }: { partition: Partition }) {
  const used = partition.filesystem
    ? percentage(partition.filesystem.usedBytes, partition.filesystem.totalBytes)
    : 0;
  const flags = [
    partition.mounted ? "mounted" : undefined,
    partition.encrypted ? "encrypted" : undefined,
    partition.dirty ? "dirty" : undefined,
  ].filter(Boolean);

  return (
    <article className="partition-card">
      <header>
        <div>
          <h3>{partition.letter ? `${partition.letter}: ` : ""}{partition.name}</h3>
          <p>
            {partition.filesystem?.type.toUpperCase() ?? "Unknown FS"} ·{" "}
            {formatBytes(partition.sizeBytes)}
          </p>
        </div>
        <span>{formatBytes(getPartitionEnd(partition))}</span>
      </header>
      <div className="usage-meter" aria-label={`${used.toFixed(1)} percent used`}>
        <span style={{ width: `${used}%` }} />
      </div>
      <footer>
        <span>{partition.filesystem ? `${used.toFixed(1)}% used` : "No filesystem data"}</span>
        <span>{flags.length > 0 ? flags.join(", ") : "offline, clear"}</span>
      </footer>
    </article>
  );
}

function SafetyReport({ findings }: { findings: SafetyFinding[] }) {
  if (findings.length === 0) {
    return (
      <div className="empty-findings">
        <ShieldCheck size={18} />
        <span>Ready for simulation. Execution remains locked.</span>
      </div>
    );
  }

  return (
    <ul className="finding-list">
      {findings.map((finding) => (
        <li className={`finding finding-${finding.severity}`} key={finding.id}>
          <span>{finding.severity}</span>
          <p>{finding.message}</p>
        </li>
      ))}
    </ul>
  );
}

function buildDiskBlocks(disk: Disk) {
  const blocks: Array<{
    id: string;
    kind: "partition" | "free";
    label: string;
    sizeBytes: number;
    partition?: Partition;
  }> = [];
  let cursor = 0;

  for (const partition of sortPartitions(disk.partitions)) {
    if (partition.startByte > cursor) {
      blocks.push({
        id: `free-${cursor}`,
        kind: "free",
        label: "Free",
        sizeBytes: partition.startByte - cursor,
      });
    }

    blocks.push({
      id: partition.id,
      kind: "partition",
      label: `${partition.letter ? `${partition.letter}: ` : ""}${partition.name}`,
      sizeBytes: partition.sizeBytes,
      partition,
    });
    cursor = getPartitionEnd(partition);
  }

  if (cursor < disk.sizeBytes) {
    blocks.push({
      id: `free-${cursor}`,
      kind: "free",
      label: "Free",
      sizeBytes: disk.sizeBytes - cursor,
    });
  }

  return blocks;
}

function formatTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function downloadFile(filename: string, contents: string, type: string) {
  const blob = new Blob([contents], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default App;
