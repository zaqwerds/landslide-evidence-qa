"""Reconstruct numerical paper results from released ratings without API or database access."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import platform
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest, rankdata, spearmanr, wilcoxon

ROOT = Path(__file__).resolve().parents[2]
METRICS = ["evidence_accuracy", "faithfulness", "semantic_score", "key_fact_coverage", "strict_content_success", "unsupported"]
RATE_NAMES = {"strict_content_success": "strict_content_success_rate", "unsupported": "unsupported_statement_rate", "binding_error": "binding_error_rate"}


def read_csv(path: Path) -> pd.DataFrame:
    """Preserve floating-point round trips and reject empty inputs."""
    frame = pd.read_csv(path, encoding="utf-8-sig", float_precision="round_trip")
    if frame.empty:
        raise ValueError(f"Empty input: {path.name}")
    return frame


def require_scores(frame: pd.DataFrame) -> None:
    """Validate ratings without changing or filling any source score."""
    limits = {"correctness": 4, "completeness": 2, "faithfulness": 2, "key_fact_coverage": 1,
              "strict_content_success": 1, "unsupported": 1, "binding_error": 1}
    if "evidence_accuracy" in frame:
        limits["evidence_accuracy"] = 2
    for column, high in limits.items():
        values = pd.to_numeric(frame[column], errors="raise")
        if values.isna().any() or not values.between(0, high).all():
            raise ValueError(f"Missing or out-of-range scores: {column}")
        if column in {"strict_content_success", "unsupported", "binding_error"} and not values.isin([0, 1]).all():
            raise ValueError(f"Nonbinary flag: {column}")
    calculated = (frame.correctness + frame.completeness + frame.faithfulness) * 1.25
    if not np.allclose(calculated, frame.semantic_score, atol=1e-12, rtol=0):
        raise ValueError("Released semantic scores disagree with the three-component definition")
    frame["semantic_score"] = calculated


def holm(values: list[float]) -> np.ndarray:
    """Adjust one explicitly defined comparison family."""
    p = np.asarray(values, dtype=float)
    order = np.argsort(p)
    adjusted = np.empty(len(p))
    adjusted[order] = np.minimum(1.0, np.maximum.accumulate(p[order] * (len(p) - np.arange(len(p)))))
    return adjusted


def rank_biserial(differences: np.ndarray) -> float:
    """Use nonzero absolute ranks, signed in the A-minus-comparator direction."""
    nonzero = differences[differences != 0]
    if not len(nonzero):
        return 0.0
    ranks = rankdata(np.abs(nonzero), method="average")
    return float(np.sum(ranks * np.sign(nonzero)) / np.sum(ranks))


def paired(x: np.ndarray, y: np.ndarray, seed: int, resamples: int) -> dict:
    """Bootstrap paired questions and test their per-question run averages."""
    differences = np.asarray(x, float) - np.asarray(y, float)
    rng = np.random.default_rng(seed)
    sampled_means = np.empty(resamples)
    for start in range(0, resamples, 1000):
        count = min(1000, resamples - start)
        sampled_means[start:start + count] = differences[rng.integers(0, len(differences), size=(count, len(differences)))].mean(axis=1)
    p = 1.0 if np.all(differences == 0) else float(wilcoxon(x, y, alternative="two-sided", zero_method="wilcox", method="auto").pvalue)
    return {"n_paired_questions": len(differences), "mean_A": float(np.mean(x)), "mean_comparator": float(np.mean(y)),
            "A_minus_comparator": float(np.mean(differences)), "bootstrap_ci95_low": float(np.quantile(sampled_means, .025)),
            "bootstrap_ci95_high": float(np.quantile(sampled_means, .975)), "wilcoxon_p": p,
            "rank_biserial": rank_biserial(differences)}


def icc_absolute_single(values: np.ndarray) -> float:
    """Two-way absolute-agreement single-measure ICC(A,1)."""
    n, k = values.shape
    grand = values.mean()
    row = values.mean(axis=1)
    col = values.mean(axis=0)
    ms_rows = k * np.sum((row - grand) ** 2) / (n - 1)
    ms_cols = n * np.sum((col - grand) ** 2) / (k - 1)
    ms_error = np.sum((values - row[:, None] - col[None, :] + grand) ** 2) / ((n - 1) * (k - 1))
    denominator = ms_rows + (k - 1) * ms_error + k * (ms_cols - ms_error) / n
    return float((ms_rows - ms_error) / denominator) if denominator else math.nan


def exact_mcnemar(a: np.ndarray, c: np.ndarray) -> float:
    """Use discordant binary pairs only; an all-concordant sample has p=1."""
    b = int(np.sum((a == 1) & (c == 0)))
    d = int(np.sum((a == 0) & (c == 1)))
    return float(binomtest(min(b, d), b + d, p=.5).pvalue) if b + d else 1.0


def rater_point_estimates(frame: pd.DataFrame) -> pd.DataFrame:
    """Recalculate agreement point estimates, not the original rater bootstrap intervals."""
    rows = []
    for scope in ["A", "C", "Combined"]:
        group = frame if scope == "Combined" else frame[frame.condition.eq(scope)]
        x = group.rater1_four_component_total.to_numpy(float)
        y = group.rater2_four_component_total.to_numpy(float)
        a = group.rater1_unsupported.to_numpy(int)
        c = group.rater2_unsupported.to_numpy(int)
        observed = float(np.mean(a == c))
        expected = float(a.mean() * c.mean() + (1 - a.mean()) * (1 - c.mean()))
        rows.append({"scope": scope, "n_answer_units": len(group), "rater1_mean": x.mean(), "rater2_mean": y.mean(),
                     "rater2_minus_rater1": (y - x).mean(), "mae": np.abs(y - x).mean(), "rmse": np.sqrt(np.mean((y - x) ** 2)),
                     "exact_score_agreement": np.mean(x == y), "within_one_point_agreement": np.mean(np.abs(x - y) <= 1),
                     "spearman_rho": float(spearmanr(x, y).statistic), "icc_A1": icc_absolute_single(np.column_stack([x, y])),
                     "unsupported_agreement": observed, "cohen_kappa": (observed - expected) / (1 - expected) if expected < 1 else math.nan,
                     "mcnemar_p": exact_mcnemar(a, c)})
    return pd.DataFrame(rows)


def compare_numeric(observed: pd.DataFrame, expected: pd.DataFrame, keys: list[str], columns: list[str], label: str) -> dict:
    """Compare actual recalculations with reported targets; never copy target values into results."""
    left = observed.set_index(keys).sort_index()
    right = expected.set_index(keys).sort_index()
    if left.index.duplicated().any() or right.index.duplicated().any() or not left.index.equals(right.index):
        raise ValueError(f"Comparison keys do not align: {label}")
    differences = []
    for column in columns:
        actual = pd.to_numeric(left[column], errors="coerce").to_numpy(float)
        target = pd.to_numeric(right[column], errors="coerce").to_numpy(float)
        match = np.isclose(actual, target, rtol=1e-9, atol=1e-9, equal_nan=True)
        for key, a, b, ok in zip(left.index, actual, target, match):
            if not ok:
                differences.append({"key": str(key), "field": column, "reconstructed": float(a), "reported": float(b)})
    return {"comparison": label, "rows": len(left), "fields_checked": columns, "passed": not differences, "differences": differences}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT / "paper_data")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "paper_reproduction")
    parser.add_argument("--bootstrap-resamples", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=20261030)
    args = parser.parse_args()
    data = args.data_root.resolve()
    output = args.output.resolve()
    if args.bootstrap_resamples < 1000:
        parser.error("Use at least 1000 bootstrap resamples")
    if output == ROOT or output == data or data in output.parents:
        parser.error("Derived outputs must not overwrite the repository root or released data")
    output.mkdir(parents=True, exist_ok=True)

    ablation = read_csv(data / "03_three_run_ablation/answers_and_scores.csv")
    five = read_csv(data / "02_five_system_benchmark/answers_and_scores.csv")
    for frame in (ablation, five):
        require_scores(frame)
    if len(ablation) != 690 or set(ablation.repeat) != {1, 2, 3} or ablation.groupby(["condition", "question_id"]).size().ne(3).any():
        raise ValueError("Expected 690 ablation records with three runs per condition/question")
    if ablation.duplicated(["condition", "question_id", "repeat"]).any() or ablation.groupby("condition").size().to_dict() != {"A": 300, "B": 90, "C": 300}:
        raise ValueError("Duplicate or unexpected ablation keys")
    if len(five) != 500 or five.groupby("system").size().ne(100).any() or five.duplicated(["system", "question_id"]).any():
        raise ValueError("Expected 500 unique system/question records")

    summary = ablation.groupby("condition")[METRICS + ["binding_error"]].mean().rename(columns=RATE_NAMES).reset_index()
    by_task = ablation.groupby(["condition", "task_type"])[METRICS].mean().rename(columns=RATE_NAMES).reset_index()
    five_summary = five.groupby("system")[["semantic_score", "key_fact_coverage", "strict_content_success", "unsupported", "binding_error"]].mean().rename(columns=RATE_NAMES).reset_index()
    rows = []
    for comparator, count in [("C", 100), ("B", 30)]:
        family = []
        for index, metric in enumerate(METRICS):
            pivot = ablation.pivot_table(index="question_id", columns="condition", values=metric, aggfunc="mean").dropna(subset=["A", comparator]).sort_index()
            if len(pivot) != count:
                raise ValueError("Unexpected paired-question count")
            result = paired(pivot.A.to_numpy(), pivot[comparator].to_numpy(), args.seed + index, args.bootstrap_resamples)
            family.append({"comparison": f"A/{comparator}", "metric": RATE_NAMES.get(metric, metric), **result})
        for row, corrected in zip(family, holm([r["wilcoxon_p"] for r in family])):
            row["holm_p"] = float(corrected)
        rows.extend(family)
    tests = pd.DataFrame(rows)

    checks = [compare_numeric(summary, read_csv(data / "05_reported_statistics/ablation_summary.csv"), ["condition"], ["evidence_accuracy", "faithfulness", "semantic_score", "key_fact_coverage", "strict_content_success_rate", "unsupported_statement_rate", "binding_error_rate"], "ablation summaries"),
              compare_numeric(by_task, read_csv(data / "05_reported_statistics/ablation_by_task.csv"), ["condition", "task_type"], ["evidence_accuracy", "faithfulness", "semantic_score", "key_fact_coverage", "strict_content_success_rate", "unsupported_statement_rate"], "ablation task summaries"),
              compare_numeric(five_summary, read_csv(data / "05_reported_statistics/five_system_summary.csv"), ["system"], ["semantic_score", "key_fact_coverage", "strict_content_success_rate", "unsupported_statement_rate", "binding_error_rate"], "five-system summaries")]
    targets = read_csv(data / "05_reported_statistics/ablation_paired_statistics.csv")
    checks.append(compare_numeric(tests, targets, ["comparison", "metric"], ["n_paired_questions", "mean_A", "mean_comparator", "A_minus_comparator", "wilcoxon_p", "rank_biserial", "holm_p"], "paired-test point estimates"))
    interval_check = compare_numeric(tests, targets, ["comparison", "metric"], ["bootstrap_ci95_low", "bootstrap_ci95_high"], "pointwise bootstrap intervals")

    ratings = read_csv(data / "04_rater_agreement/paired_ratings_four_component_total.csv")
    if len(ratings) != 70 or ratings.duplicated(["condition", "question_id"]).any():
        raise ValueError("Expected 70 paired rater answer units")
    agreement = rater_point_estimates(ratings)
    agreement_targets = read_csv(data / "04_rater_agreement/agreement_statistics_four_component_total.csv")
    agreement_columns = [c for c in agreement if c != "scope"]
    checks.append(compare_numeric(agreement, agreement_targets, ["scope"], agreement_columns, "rater agreement point estimates"))

    adjudicated = read_csv(data / "04_rater_agreement/adjudicated_question_details_four_component_total.csv")
    x, y = adjudicated.A_final_four_component_total.to_numpy(float), adjudicated.C_final_four_component_total.to_numpy(float)
    # The historical 35-question adjudication table uses the Pratt zero convention.
    # Keep it distinct from the main ablation's wilcox convention and nonzero-rank effect size.
    adjudication = [{"metric": "four_component_total", "n_questions": len(x), "A_minus_C": float((x - y).mean()), "p_value": float(wilcoxon(x, y, zero_method="pratt", alternative="two-sided", method="asymptotic").pvalue), "effect_size_or_risk_difference": rank_biserial(x - y)},
                    {"metric": "unsupported_statement_rate", "n_questions": len(x), "A_minus_C": float((adjudicated.A_final_unsupported - adjudicated.C_final_unsupported).mean()), "p_value": exact_mcnemar(adjudicated.A_final_unsupported.to_numpy(), adjudicated.C_final_unsupported.to_numpy()), "effect_size_or_risk_difference": float((adjudicated.A_final_unsupported - adjudicated.C_final_unsupported).mean())}]
    adjudication_frame = pd.DataFrame(adjudication)
    checks.append(compare_numeric(adjudication_frame, read_csv(data / "04_rater_agreement/adjudicated_tests_four_component_total.csv"), ["metric"], ["n_questions", "A_minus_C", "p_value", "effect_size_or_risk_difference"], "adjudicated-subset point estimates"))

    for filename, frame in [("ablation_summary.csv", summary), ("ablation_by_task.csv", by_task), ("five_system_summary.csv", five_summary), ("ablation_paired_statistics.csv", tests), ("rater_agreement_point_estimates.csv", agreement), ("adjudicated_tests_point_estimates.csv", adjudication_frame)]:
        frame.to_csv(output / filename, index=False, encoding="utf-8-sig")
    report = {"status": "pass" if all(c["passed"] for c in checks) else "mismatch", "checks": checks,
              "bootstrap_interval_comparison": interval_check, "bootstrap_resamples": args.bootstrap_resamples,
              "bootstrap_seed": args.seed, "bootstrap_seed_rule": "seed plus metric index, reset within each A/C or A/B family",
              "statistical_unit": "question; mean of three repeated answers", "holm_family": "six metrics separately within A/C and A/B",
              "wilcoxon_conventions": {"main_ablation": "two-sided, zero_method=wilcox, method=auto", "historical_35_question_adjudication": "two-sided, zero_method=pratt, method=asymptotic; matches the released statistic 9 and p-value", "rank_biserial": "signed ranks of nonzero differences in both tables"},
              "semantic_score_excludes_evidence_accuracy": True,
              "ablation_records": len(ablation), "benchmark_records": len(five),
              "unsupported_counts": {str(k): int(v) for k, v in ablation.groupby("condition").unsupported.sum().items()},
              "environment": {"python": platform.python_version(), "platform": platform.platform(), **{p: importlib.metadata.version(p) for p in ("numpy", "pandas", "scipy")}},
              "not_reconstructed": ["Original generation, extraction and retrieval", "Independent semantic re-rating", "Original rater bootstrap confidence intervals"],
              "note": "Bootstrap intervals are compared separately because changed seeds or resample counts can change their endpoints; mismatches are exposed, not replaced by reported targets."}
    (output / "verification.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"status": report["status"], "point_estimate_checks_passed": sum(c["passed"] for c in checks), "point_estimate_checks": len(checks), "bootstrap_intervals_match": interval_check["passed"], "output": str(output)}, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
