# Meridian evaluation scorecard

Generated 2026-09-25T16:28:05+00:00 · LLM mode: **offline** · data mode: **auto**

Offline LLM mode means narrative text is template-based; figures and citations are real either way.

## Cases

| Case | Resolved | Passed | Latency | Notes |
| --- | --- | --- | --- | --- |
| `quick_depth` | MSFT | yes | 48.1s |  |

## Metrics by case

### quick_depth

| Metric | Value | Detail |
| --- | --- | --- |
| task_completion | 1.000 | 7/7 dispatched tasks completed (0 failed) |
| routing_accuracy | 1.000 | missing=none; wrongly included=none |
| citation_coverage | 1.000 | 99/99 fact/calculated findings carry resolvable support |
| source_correctness | 1.000 | 106/106 citations resolve to a real source (0 unknown evidence, 0 orphaned source) |
| calculation_accuracy | 1.000 | 139/139 metrics reproduce exactly |
| critic_rejection_rate | 0.124 | 92 approved, 13 unverified, 0 rejected; 14 issues raised over 1 round(s) |
| unsupported_report_claims | 0.000 | 0/104 factual paragraphs lack a resolvable citation or metric ref |
| report_completeness | 1.000 | missing sections: none (expected 4 for this depth) |
| tool_success_rate | 0.971 | 33/34 tool calls succeeded |
| estimated_cost_usd | 0 | 0 tokens across 0 LLM call(s); 34 tool calls (0 tokens means offline mode) |
| latency_seconds | 48.100 | wall-clock time for the whole run |
