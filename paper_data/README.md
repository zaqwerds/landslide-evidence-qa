# Public experimental data

The experiments were conducted on a Chinese landslide investigation report. Original questions, reference answers, system answers and source quotations remain in Chinese to preserve numerical attribution, units and the basis for scoring. File organization, field names and methodological documentation are provided in English. Numeric scores, question IDs and condition IDs are unchanged.

These are paper companion data, not required inputs for running the application. The independently maintained TextRAG comparison is not integrated into the core program; its recorded answers and scores are included only as experimental results.

## Directory guide

| Directory | Contents |
| --- | --- |
| `01_benchmark/` | 100 questions, the reference answers actually used for rating, and an 18-row scoring rubric |
| `02_five_system_benchmark/` | 500 recorded answers and ratings: 100 per system |
| `03_three_run_ablation/` | Three condition descriptions and 690 answers with scores and generation metadata: A=300, B=90, C=300 |
| `04_rater_agreement/` | Two-model-assisted ratings for 70 A/C answer units from 35 questions, 11 adjudications, and corresponding agreement/adjudication statistics |
| `05_reported_statistics/` | Preserved numerical summary and paired-test tables supplied with the manuscript |

`field_crosswalk.csv` maps each English header to its original Chinese header, file by file. The crosswalk is provenance documentation, not another set of experimental observations. [EVALUATION.md](EVALUATION.md) describes the metrics and scoring conventions. CSV files use UTF-8 with a byte-order mark for common Excel import workflows.

## Task categories

| English label | Questions | Meaning |
| --- | ---: | --- |
| Text facts | 25 | Specific facts stated in narrative text |
| Global summary | 10 | Report-level synthesis |
| Table values | 18 | Values associated with specified rows, objects and indicators |
| Table reasoning | 12 | Reasoning over reported table entries |
| Figure retrieval | 10 | Locate captions and original figure carriers, not visual understanding |
| Cross-evidence and multi-hop | 15 | Combine information across multiple evidence items |
| Unanswerable | 10 | The report does not supply the required answer |

Difficulty values are inherited labels, not an independently validated difficulty scale.

## Experimental conditions and comparability

- **A:** structured evidence with constrained generation; all 100 questions, three runs.
- **B:** the same underlying table cells in flattened form, with constrained generation; the 30 table questions only, three runs.
- **C:** structured evidence with free generation; all 100 questions, three runs.

A/C isolates generation constraints under frozen evidence. A/B changes table representation; it does not compare a graph retriever with an equally informed non-graph retriever. Condition A is a controlled frozen-evidence generation condition, not the end-to-end online KGQA run in the five-system benchmark. Do not directly compare their mean scores as if they were the same experiment.

The five systems are KGQA, Qwen, ChatGPT, DeepSeek and TextRAG. Their recorded access and generation conditions differ; the benchmark describes these configurations rather than isolating the causal contribution of graph retrieval. The conversational-model conditions do not have complete API configuration records. Do not assign the ablation's API parameters to them.

The ablation records request `deepseek-chat`, return `deepseek-flash`, use temperature 0 and a maximum of 900 output tokens. The returned identifier is not an independently pinned model snapshot. See [DeepSeek configuration](../docs/deepseek_configuration.md).

## Preserved annotations and redactions

Original rating rationales, adjudication rationales, section names, source-verification notes and error-code annotations remain unchanged in Chinese. English headers ending in `_original` identify several such fields. They are not new English re-ratings. Question IDs, anonymous candidate IDs, evidence IDs, A/B/C labels and repeat indices are retained verbatim. `repeat` identifies the run index, not the total number of repetitions.

The existing public export redacted 46 local-path occurrences and omitted seven table blocks within answers. The `public_text_note` field identifies affected answers. Scores still refer to the original answers before these redactions. This cleanup did not add further answer-text redactions or change scores.

Blank, `NA`, an em dash and the original Chinese not-estimable marker are retained where present. They are not zero scores. Confidence-interval strings retain their original precision and separator. Counts, rates and percentages must not be interchanged: numeric rate fields use 0-1 proportions unless a field explicitly states otherwise.

## Reconstruct the numerical results

Follow [the offline reconstruction example](../examples/paper_reproduction/README.md). It reads the released scores and writes derived outputs under `output/paper_reproduction/` by default, without changing these source CSV files. The preserved results in `05_reported_statistics/` are comparison targets, not replacement inputs for recalculating point estimates.

This reproduces numerical analysis of existing ratings, not report parsing, answer generation or independent expert verification. The authors do not have the rights to distribute the complete original report or source-evidence packages. A separate [fictional report example](../examples/synthetic_demo/README.md) is included for application testing; it is not an input to this numerical reconstruction and cannot reproduce the original case study. See [data availability](../DATA_AVAILABILITY.md) and the [CC BY 4.0 experimental-data license](LICENSE.md).
