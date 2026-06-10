// dynamic-workflow: llmwikify-deep-research
//
// Triggered by: `ultracode: research <question>` or `/llmwikify-research <question>`
// Saved in: .claude/workflows/llmwikify-research
//
// Architecture (4 phases, all running in Claude Code's workflow runtime,
// not in the main conversation's context):
//
//   planner (Opus)            -> phase plan JSON
//   researchers (Sonnet) x N  -> findings, in parallel, worktree-isolated
//   verifier (Sonnet)         -> adversarial review, filters hallucinations
//   synthesizer (Opus)        -> writes the final wiki page
//
// Intermediate state lives in script variables, not in Claude's context.
// The main conversation only sees the final report and the run summary.

const question = args.question;
if (!question) {
  throw new Error("llmwikify-research: missing args.question. Invoke as `/llmwikify-research <question>` or `ultracode: research <question>`.");
}

const MAX_PARALLEL_RESEARCHERS = 4;  // bounded by runtime: up to 16 concurrent agents
const MIN_FINDINGS_PER_PHASE   = 2;  // if a phase returns less, it's flagged in summary

// ---------------------------------------------------------------------------
// Phase 1: plan
// ---------------------------------------------------------------------------
const plan = await runAgent("wikify-research-planner", { question });

if (!plan?.phases || plan.phases.length < 3) {
  throw new Error(`planner returned ${plan?.phases?.length ?? 0} phases; expected 3-5`);
}
console.log(`plan: ${plan.phases.length} phases`);

// ---------------------------------------------------------------------------
// Phase 2: parallel research, one subagent per phase
// ---------------------------------------------------------------------------
const phasePromises = plan.phases.map((phase) =>
  runAgent("wikify-phase-researcher", { phase })
);
const phaseResults = await Promise.all(phasePromises);

const sparse = phaseResults.filter(
  (r) => !r?.findings || r.findings.length < MIN_FINDINGS_PER_PHASE
);
if (sparse.length > 0) {
  console.warn(
    `${sparse.length}/${plan.phases.length} phases returned < ${MIN_FINDINGS_PER_PHASE} findings; ` +
    `they will still be reviewed, but expect a partial synthesis`
  );
}

// ---------------------------------------------------------------------------
// Phase 3: adversarial verification
// ---------------------------------------------------------------------------
const flatClaims = phaseResults.flatMap((pr) =>
  (pr?.findings ?? []).map((f) => ({ phase_id: pr.phase_id, ...f }))
);

const review = await runAgent("wikify-adversarial-verifier", {
  question,
  claims: flatClaims,
});

const acceptedOrDowngraded = new Set(
  (review?.verdicts ?? [])
    .filter((v) => v.verdict === "accept" || v.verdict === "downgrade")
    .map((v) => v.claim)
);
const filteredFindings = phaseResults.map((pr) => ({
  ...pr,
  findings: (pr?.findings ?? []).filter((f) => acceptedOrDowngraded.has(f.claim)),
}));

const dropped = flatClaims.length - filteredFindings.flatMap((p) => p.findings).length;
console.log(
  `adversarial review: ${review?.summary?.overall ?? "unknown"}; ` +
  `${dropped} claim(s) filtered out of ${flatClaims.length}`
);

// ---------------------------------------------------------------------------
// Phase 4: synthesis -> wiki page
// ---------------------------------------------------------------------------
const result = await runAgent("wikify-synthesizer", {
  question,
  plan,
  filteredFindings,
  reviewSummary: review?.summary,
  synthesisCriteria: plan.synthesis_criteria,
});

return {
  question,
  page_path: result.page_path,
  plan_phases: plan.phases.length,
  raw_findings: flatClaims.length,
  accepted_findings: flatClaims.length - dropped,
  review_verdict: review?.summary?.overall ?? "unknown",
  criteria_met: result.criteria_met?.length ?? 0,
  criteria_unmet: result.criteria_unmet?.length ?? 0,
  open_questions: result.open_questions ?? [],
};
