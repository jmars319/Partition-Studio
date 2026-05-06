import fs from "node:fs";
import path from "node:path";

const fixtureDir = path.resolve("fixtures/handoffs");
const expectedSchemas = new Set(["tenra-partition.lab-validation-request.v1"]);

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

console.log(`Validated ${files.length} Partition handoff fixture(s).`);
