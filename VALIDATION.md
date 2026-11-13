# Release validation

Checked locally on **13 November 2026**. This report distinguishes tested offline functionality from services and restricted data that were not exercised. It is not a journal-compliance certification or a claim that the repository is already public.

## Environment

A new isolated Windows virtual environment was created with Python **3.11.9**. The application dependencies in `requirements.txt` and the optional statistics dependencies were installed successfully; `pip check` reported no broken requirements. The 92-package environment snapshot is provided in [requirements-lock-windows-py311.txt](requirements-lock-windows-py311.txt). It is a reference-platform snapshot, not a portable or minimal lockfile.

No model weights were downloaded for these tests. PyTorch and sentence-transformers were installed as dependencies, but no embedding model or cloud generation was required. Hardware minimums and cross-platform behavior were not benchmarked.

A subsequent read-only local inspection recovered historical Neo4j version evidence: Enterprise 2026.01.4 and Azul OpenJDK 21.0.12+8-LTS appear in the server logs on 21 October, with the localhost Bolt port used in the saved ablation configuration. The newer local 2026.10.2 installation has its first retained startup on 12 November. The installed Neo4j Desktop application is 2.3.0. These observations do not constitute a fresh live database test. Current workstation details and the separately observed 147-package base-Python inventory are documented in [environment information](docs/environment/README.md).

## Checks performed

| Check | Result and scope |
| --- | --- |
| Original source preservation | All 37 existing Python files checked against a pre-edit backup after removing only module/class/function docstrings from both syntax trees. Behavior-bearing syntax, prompt literals, report vocabulary and database labels were unchanged |
| English source documentation | 640 Chinese comment occurrences and 308 docstrings translated or concisely restated in English; no remaining Chinese Python comments/docstrings found in public candidates |
| Data integrity | All cells in 16 experimental CSV files checked against the pre-edit copies under explicit header/category/rubric translations. Original questions, answers, quotations, scores, IDs and condition/repeat values preserved |
| Offline regression suite | 15 tests passed in the new environment: value/unit normalization, question routing, generation payloads with mocked HTTP, failure/fallback metadata, source-carrier deduplication, ontology parsing and record counts |
| Module imports | Original application modules imported in the new environment without live model or database operations |
| Numerical reconstruction | All six groups of numerical point-estimate checks passed; all 12 paired bootstrap-interval rows also matched the preserved targets using default settings |
| Web initialization | Streamlit AppTest loaded all three main tabs without application exceptions; credentials were blanked for the test and no database/API action was triggered |
| Local processing pipeline | An existing authorized DOCX was processed in a private directory outside this repository, using the demo ontology and local rules. All 64 tables and 259 figures were parsed; text processing was limited to two segments. Ingestion, parsing, extraction, fusion and quality control completed; Neo4j writing was disabled |
| Fictional DOCX smoke test | A separate test copy processed the included [synthetic report](examples/synthetic_demo/README.md) with local rules, then DeepSeek extraction and a live Neo4j/QA run. Parsing found 7 text blocks, 1 table and 1 figure without parser warnings. The live graph run reported 12 event nodes, 3 table rows, 12 cells and 0 storage errors. Nine sequential questions in one chat session were manually classified as 6 pass, 2 partial and 1 fail. The [Chinese test record](examples/synthetic_demo/test_record_zh.docx) documents that run; its referenced runtime paths are not included. These are diagnostic observations, not paper-result reproduction or a general performance estimate |
| Release-candidate scan | Check local documentation links, syntax, English comments/docstrings, CSV headers and common API/GitHub-token patterns; exclude runtime directories and restricted report/archive formats |

Numerical reconstruction distinguishes the main three-component semantic score from the four-component totals in the rater subset. The main ablation uses the `wilcox` zero convention; the historical 35-question adjudication uses Pratt handling. These are documented separately rather than silently replacing historical statistics.

The release-candidate check is a scoped automated audit, not proof that no sensitive information exists. In particular, review the candidate file list and history before public upload. Chinese strings in runtime prompts, labels, report vocabulary and original experimental text are intentional.

## Repeat the public offline checks

From the repository root:

```text
python -m unittest discover -s tests -v
python examples/paper_reproduction/reproduce_statistics.py
```

The first command needs the application dependencies. The second needs only the separate statistics requirements. See [the reconstruction tutorial](examples/paper_reproduction/README.md) for the expected outputs, parameter choices and mismatch behavior.

For the exact tested Windows/Python combination, the complete installed-package snapshot can be installed in a separate environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock-windows-py311.txt
.\.venv\Scripts\python.exe -m pip check
```

## Not verified by this release check

- Live DeepSeek or other hosted-model availability, exact backend snapshot, generation quality or cost.
- A fresh Neo4j/QA run in the isolated release-validation environment or on the user's original database. The separate synthetic test copy did exercise live graph writing and QA, as recorded above; that diagnostic does not validate the original case-study results.
- Full-report LLM extraction or regeneration of the original paper answers.
- Independent expert validation of reference answers or model-assisted scores.
- Linux/macOS behavior or minimum hardware requirements.
- Public repository reachability, which must be checked after publication.

The synthetic smoke test exposed unresolved issues: table events sent to review by a numeric-unit check despite retained units, a schematic misclassified as a plan view, DOCX page metadata differing from rendered pagination, a false refusal caused by missing prose evidence for the monitoring period, and a figure-location answer whose browser-open action was not recorded. Its requested `deepseek-chat` label and the `deepseek-flash` response metadata do not identify a fixed provider backend. Do not present the 6/9 manual pass count as an efficacy estimate.

The original report and complete source data remain restricted. The included fictional DOCX allows a separate application smoke test, while the public numerical example verifies analysis of released ratings; neither reproduces the full original source-to-answer experiment. See [DATA_AVAILABILITY.md](DATA_AVAILABILITY.md).
