# Offline reconstruction of paper results

This is an optional **paper companion example**, not part of the report-processing application and not an integrated TextRAG baseline. It reconstructs numerical results from previously recorded scores. No Neo4j, cloud API, model weights or original report is needed. It does not rate answers again or regenerate them.

## Install and run

From the repository root, use Python 3.11:

```powershell
py -3.11 -m venv .venv-statistics
.\.venv-statistics\Scripts\python.exe -m pip install -r examples/paper_reproduction/requirements.txt
.\.venv-statistics\Scripts\python.exe examples/paper_reproduction/reproduce_statistics.py
```

On another platform, use the corresponding environment's Python executable. The validated reference is Windows; other platforms are not independently certified here. This example normally needs only CPU, the three listed libraries and a small amount of memory. It bootstraps in batches; no GPU or model download is used. No minimum hardware benchmark is claimed.

Default input is `paper_data/`. Default output is `output/paper_reproduction/`, an ignored generated directory. Inputs are never overwritten. The script rejects using the repository root or the source-data directory as its output.

## Inputs and expected results

The example checks 500 five-system answers, 690 three-run ablation answers, the 70 paired rater units and the 35-question adjudicated subset. It recomputes the three-component semantic score, validates score ranges and uniqueness, averages repeated answers by question for paired inference, and compares recalculated values against the released summary tables.

Key expected ablation results are:

- A semantic mean: **8.75/10**; C: **8.6375/10**.
- Unsupported answers: **3/300** in A and **26/300** in C.
- A/C: 100 paired questions; A/B: 30 paired table questions.
- Semantic score excludes evidence accuracy; four-component rater totals are treated separately.

The five-system summaries, task summaries, paired mean differences, Wilcoxon p-values, rank-biserial effects, Holm corrections, rater agreement point estimates and adjudication point estimates are checked against the released numerical targets. No reported target is copied into a recalculated result to make a check pass.

## Outputs

| File | Contents |
| --- | --- |
| `five_system_summary.csv` | Recalculated descriptive benchmark means and rates |
| `ablation_summary.csv` | Recalculated condition summaries |
| `ablation_by_task.csv` | Condition-by-task summaries |
| `ablation_paired_statistics.csv` | Question-level paired differences, pointwise intervals, Wilcoxon tests, effects and Holm correction |
| `rater_agreement_point_estimates.csv` | Recalculated agreement point estimates; no newly claimed reproduction of rater bootstrap intervals |
| `adjudicated_tests_point_estimates.csv` | Tests on the historical 35-question four-component-total subset |
| `verification.json` | Check results, mismatches, record counts, test conventions, software versions and reconstruction limits |

Successful point-estimate checks produce `status: pass` and exit code 0. A mismatch produces exit code 1 and lists affected values. Invalid or missing inputs raise an explicit error. The default bootstrap intervals are checked separately; a changed seed or sample count may alter interval endpoints, which remain visible in the report rather than being silently replaced. Check both `status` and `bootstrap_interval_comparison`.

## Options and statistical conventions

```text
python examples/paper_reproduction/reproduce_statistics.py --help
python examples/paper_reproduction/reproduce_statistics.py --output output/my_check
python examples/paper_reproduction/reproduce_statistics.py --bootstrap-resamples 20000 --seed 20261030
```

`--data-root` can point to another copy of the same release schema. This example deliberately validates the paper's known dataset sizes; it is not a general-purpose evaluator for arbitrary new reports.

The default is 20,000 paired question-level bootstrap samples. Seeds are `20261030 + metric index`, reset for each A/C and A/B family. Six two-sided Wilcoxon tests per comparison family use `zero_method='wilcox'`, followed by Holm correction. Rank-biserial effects use signed nonzero ranks. Pointwise bootstrap intervals are unadjusted; they can disagree with multiplicity-adjusted tests.

The separate historical 35-question adjudication table uses the Pratt zero convention and asymptotic p-value, matching its released statistic of 9. Its rank-biserial effect is calculated from nonzero ranks. This historical convention is explicitly separate from the main ablation. The script does not change original scores to unify the two analyses.

No significant semantic-score difference was detected in the main A/C comparison. This is not an equivalence or noninferiority test. The five-system access conditions differ; their descriptive results do not isolate the independent accuracy gain of graph retrieval.

See [evaluation definitions](../../paper_data/EVALUATION.md), [data provenance and redactions](../../paper_data/README.md), and [source-data availability](../../DATA_AVAILABILITY.md). Data are CC BY 4.0; this example's code is MIT.
