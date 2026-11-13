# Evaluation fields and calculation conventions

## Reference answers and raters

Reference answers were developed and checked against the source report with AI assistance. They are report-checked references, not an independently established expert gold standard. Main scores are model-assisted ratings with rule-based checks. The second-model and author-adjudication records concern the 35-question A/C subset; they are not an independent engineering-geology expert blind review of all 500 benchmark answers or all 690 ablation answers.

The separate [scoring rubric](01_benchmark/scoring_rubric.csv) gives the translated, original rating rules. This release does not create new ratings or retroactively change the criteria.

## Fields used in the primary analysis

| Field | Scale | Definition |
| --- | --- | --- |
| `correctness` | 0-4 | Correctness of core conclusions, object/value attribution and semantic relations |
| `completeness` | 0-2 | Coverage of required facts and necessary qualifications |
| `faithfulness` | 0-2 | Support of substantive statements by the report/evidence |
| `semantic_score` | 0-10 | `(correctness + completeness + faithfulness) / 8 * 10` |
| `evidence_accuracy` | 0-2 | Correctness and sufficiency of source identification in the ablation; separate from semantic score |
| `evidence_traceability_score` | 0-2 or NA | Recorded source-traceability score in the five-system benchmark; not included in semantic score |
| `key_fact_coverage` | 0-1 | Recorded proportion of required key facts covered by the answer |
| `unsupported` | 0 or 1 | At least one unsupported substantive statement capable of changing the factual judgment |
| `strict_content_success` | 0 or 1 | Recorded strict success: for answerable questions, full correctness and completeness, no unsupported statement and no incorrect refusal; correct refusal for unanswerable questions |
| `binding_error` | 0 or 1 | A numeric fact is assigned to the wrong object or otherwise mismatched in the recorded rating |
| `answerable` | 0 or 1 | Whether the requested answer is available in the report |
| `refused` | 0 or 1 | Whether the answer refused |
| `refusal_correct` | 0, 1 or NA | Recorded assessment of refusal correctness |

For correctness, 4 means correct core facts; 3 minor ambiguity/precision issues; 2 partial correctness with an important omission/error; 1 little correct relevant content; and 0 a wrong core answer, object misassignment, incorrect refusal or major fabrication. Completeness is 2 for all required facts and qualifications, 1 for an incomplete but correct core answer and 0 for missing core facts/incorrect refusal. Faithfulness is 2 for supported substantive statements, 1 for minor overreach and 0 for unsupported content that can change the judgment.

Evidence traceability is 2 when source location is correct and sufficient, 1 when incomplete without miscitation and 0 for incorrect or fabricated sources. The original rubric allows NA when a source was neither requested nor claimed. The reconstruction uses the released values as recorded and does not reinterpret A/C source-use scores. C does not require citations; evidence-accuracy differences must therefore not be interpreted as equivalent differences in semantic correctness.

A missing explicit unit does not automatically make a value semantically wrong: a unit unambiguously specified by the question may be inherited. Correct equivalent conversions are accepted. `explicit_unit_present` is separate from `numeric_unit_semantically_correct`. Wrong units, scale, object or time interval can be substantive errors.

Question-specific required facts and applicability are supplied in the benchmark data. Coverage and success fields, including those for unanswerable questions, are preserved as rated. The reconstruction aggregates those fields rather than inventing key facts for unanswerable questions. Macro coverage is the mean of per-answer coverage. Where a micro coverage is calculated, it uses matched/reference fact counts and only records with a valid positive denominator; it is a different metric.

Rates such as unsupported-statement and binding-error rates use all answers in the explicitly selected group as their denominator. A table-only rate must use the table subset, not all 100 questions.

## Four-component totals in the rater subset

The rater-agreement and adjudication materials use a different 0-10 total: correctness + completeness + faithfulness + evidence accuracy. Names containing `four_component_total` refer to this quantity. Do not replace the main semantic score with this total or describe a difference in this total as a semantic-score improvement. The release includes both quantities only in their respective roles.

## Statistical unit and tests

The three-run ablation has 300 A, 90 B and 300 C answers. For paired inference, first average each metric over the three runs of each question. Pair by question ID: A/C has 100 pairs; A/B has 30 table-question pairs. Answer-level rates over 300 or 90 records are descriptive summaries; repeated answers are not treated as independent questions.

Use two-sided Wilcoxon signed-rank tests with zero differences omitted (`zero_method='wilcox'`). Signed rank-biserial effect size is `(positive rank sum - negative rank sum) / total rank sum`, in the A-minus-comparator direction. All-zero differences are represented by p=1 and effect size 0. For each A/C or A/B family, apply Holm correction across six metrics: evidence accuracy, faithfulness, semantic score, key-fact coverage, strict content success and unsupported-statement incidence.

Pointwise 95% intervals use paired question-level bootstrap resampling of the mean difference. They are not multiplicity-adjusted. A pointwise interval and a Holm-adjusted p-value need not imply the same decision. The example documents its seed, resample count and library versions and compares reconstructed results against the preserved statistics. A non-significant difference is not proof of equivalence or noninferiority.

Rater point estimates use Spearman correlation, two-way absolute-agreement single-measure ICC(A,1), Cohen's kappa and exact McNemar tests as applicable. Degenerate all-negative classifications do not yield an estimable kappa. The historical 35-question adjudication table uses the Pratt zero convention for its asymptotic two-sided Wilcoxon test (statistic 9); it is not the main ablation's `wilcox` convention. The reconstruction states these conventions separately and retains the nonzero-rank effect-size calculation. The original published confidence-interval strings are retained; where the original resampling protocol for a rater interval is not reconstructed, the example does not claim to reproduce that interval.
