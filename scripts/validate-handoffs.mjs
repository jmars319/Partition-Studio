import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

const fixtureDir = path.resolve("fixtures/handoffs");
const registryDocCheck = spawnSync(process.execPath, ["scripts/generate-handoff-registry.mjs", "--check"], {
  stdio: "inherit"
});
if (registryDocCheck.status !== 0) process.exit(registryDocCheck.status ?? 1);
const expectedSchemas = new Set([
  "tenra-partition.lab-validation-request.v1",
  "tenra-partition.lab-validation-result.v1"
]);

function listJsonFiles(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = path.join(dir, entry.name);
    return entry.isDirectory() ? listJsonFiles(fullPath) : entry.name.endsWith(".json") ? [fullPath] : [];
  });
}

const files = listJsonFiles(fixtureDir);
if (files.length === 0) throw new Error("No handoff fixtures found.");

for (const file of files) {
  const payload = JSON.parse(fs.readFileSync(file, "utf8"));
  if (!payload || typeof payload !== "object" || typeof payload.schema !== "string") {
    throw new Error(`${file} must contain an object payload with a schema string.`);
  }
  if (!expectedSchemas.has(payload.schema)) {
    throw new Error(`${file} uses an unexpected schema: ${payload.schema}`);
  }
  if (payload.schema === "tenra-partition.lab-validation-request.v1") {
    if (payload.execution?.enabled !== false) {
      throw new Error(`${file} must keep execution.enabled false.`);
    }
    if (!Array.isArray(payload.plan?.operations) || payload.plan.operations.length === 0) {
      throw new Error(`${file} must include a full operation plan with operations.`);
    }
    if (payload.plan?.validation?.ok !== true || payload.simulation?.validation?.ok !== true) {
      throw new Error(`${file} must include passing plan and simulation validation summaries.`);
    }
    if (payload.plan?.safetyReport?.level !== "clear") {
      throw new Error(`${file} must keep the golden fixture safety posture clear.`);
    }
  }
  if (payload.schema === "tenra-partition.lab-validation-result.v1") {
    if (payload.sourceRequest?.schema !== "tenra-partition.lab-validation-request.v1") {
      throw new Error(`${file} must embed the source lab validation request.`);
    }
    if (payload.review?.execution?.enabled !== false) {
      throw new Error(`${file} must keep result review execution disabled.`);
    }
    if (payload.review?.requestedPlanMatchesReviewedPlan !== true) {
      throw new Error(`${file} must preserve a matching reviewed plan in the golden result.`);
    }
  }
}

console.log(`Validated ${files.length} Partition handoff fixture(s).`);
