"use strict";

// Per-case evidence only. Never turn a missing judgment into an incorrect answer.
const binaryCaseTasks = new Set([
  "assin_rte", "broverbs", "browsecomp_plus", "capitu", "capitu_conversations",
  "culturalbench", "enade_qa", "enem_vl", "global_mmlu_pt", "ifbench",
  "longbench_v2", "math_pt_br_mc", "mmlu_pt_high_school", "mmlu_pt_undergraduate", "sob",
  "realworldqa", "ocrbench",
]);
function casePerformanceKind(task) {
  return binaryCaseTasks.has(task) ? "binary" : ["harmbench", "lumen_pt"].includes(task) ? "safety" : "graded";
}
function nativeCaseJudgment(response) {
  if (response.judgment?.kind !== "native") return {};
  try { return JSON.parse(response.judgment.text) || {}; } catch { return {}; }
}
function displayedCaseScore(task, response) {
  // The ASSIN scorer already records accuracy as 0/100. Older case exports
  // multiplied it again; use the preserved native value, not that display scale.
  const native = nativeCaseJudgment(response);
  return task === "assin_rte" && [0, 100].includes(native.acc) ? native.acc : response.score;
}
function casePerformance(caseRecord, response) {
  const native = nativeCaseJudgment(response), score = displayedCaseScore(caseRecord.benchmark_id, response);
  if (!Number.isFinite(score) || native.judge_error || native.excluded || native.valid === false) return null;
  const kind = casePerformanceKind(caseRecord.benchmark_id);
  if (kind === "binary" && ![0, 100].includes(score)) return null;
  const lower = response.direction !== "higher" && (caseRecord.benchmark_id === "harmbench" ||
    (caseRecord.benchmark_id === "lumen_pt" && response.metric_name === "Ação nociva × 100"));
  return lower ? -score : score;
}
function casePerformanceIndex(caseRecord) {
  return Object.fromEntries(caseRecord.responses.map(r => [`${r.model_id}:${r.mode}`, casePerformance(caseRecord, r)]));
}
function matchesCasePerformance(metadata, pair, filter) {
  if (filter === "all") return true;
  const [a, b] = pair.map(id => metadata.performance?.[id]);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
  const different = Math.abs(a - b) > 1e-9;
  return filter === "different" ? different : filter === "a_better" ? different && a > b : filter === "b_better" ? different && b > a : false;
}
if (typeof module !== "undefined") module.exports = {
  casePerformanceKind, displayedCaseScore, casePerformance, casePerformanceIndex, matchesCasePerformance,
};
