# Synthetic landslide report tutorial

This example lets a reviewer exercise the application without access to the restricted source report. The input is a **fictional** Chinese DOCX, not a real site investigation or a substitute for the paper's historical case study. It contains native text, one Word table and one embedded schematic. The accompanying ontology is a small project-authored demonstration schema.

## Files and prerequisites

- Input report: [`../synthetic_landslide_report.docx`](../synthetic_landslide_report.docx)
- Demonstration ontology: [`../demo_ontology.ttl`](../demo_ontology.ttl)
- Reusable questions: [`questions.csv`](questions.csv)
- Recorded Chinese test document: [`test_record_zh.docx`](test_record_zh.docx)
- Installation and resource requirements: [main README](../../README.md)

The fictional input report and recorded test document are released under [CC BY 4.0](../LICENSE.md). This permission applies only to those example files, not to the restricted source report.

The CSV is encoded as UTF-8 with a byte-order mark so Chinese questions are recognized when opened directly by common Windows spreadsheet programs. If importing it manually, select UTF-8 rather than a local legacy encoding.

The test document is a **record of one completed run**, not an additional input report. It preserves the nine-question result table and an image of the fictional figure. Its relative `output/` and `artifacts/` paths refer to the separate test copy used to produce the record; those runtime files are intentionally not bundled in this public repository. Use the input report and steps below to create your own run files.

Start the web application from the repository root using `python "启动网页.py"`. Use a **dedicated** Neo4j database if you plan to test graph writing; the interface has a maintenance control that can clear all reports in the connected database. A cloud extraction or answer-generation run also needs your own API credentials and may incur charges.

## A. Local processing without an API or database

1. In the sidebar, upload `examples/demo_ontology.ttl` under **上传本体文件（TTL）**.
2. Set **正文抽取方式** to **本地规则** and turn off **写入Neo4j**.
3. Open **报告处理**, upload `examples/synthetic_landslide_report.docx`, and select **开始解析并构建图谱**.
4. Inspect the run summary and the files written under `output/<report_id>/runs/<run_id>/`. Inspect the table JSON/HTML and figure image under `artifacts/<report_id>/content/`.

The observed parser smoke test on 13 November 2026 found **7 text blocks, 1 table and 1 figure**, without parser warnings. The table had three rows including the header and four columns. Check the report itself if a future code version produces different segmentation counts. This path tests parsing, local extraction, fusion and quality-control handling; it does **not** create a queryable graph or reproduce the paper's model-based extraction.

## B. Graph storage and evidence-based questions

1. Start a separate Neo4j instance and enter its URI and credentials in the sidebar. Confirm **测试 Neo4j 连接** succeeds.
2. To exercise model-based extraction, select **大模型**, configure an available provider/model and your own API key. Enable **写入Neo4j** and process the same DOCX again. Provider output and event counts can vary.
3. Select the newly built report in **结果浏览** and **图谱问答**. Ask the questions in `questions.csv` in the listed order if you want to compare with the recorded single-session check. Use separate fresh sessions if you want independent answers; those are a different test design.
4. For each answer, verify the monitoring point, indicator, value, unit and source carrier. A plausible sentence alone is not a pass. A local file path is not a public URL; check that linked HTML/image carriers still exist on the machine where the application ran.

## Ground-truth facts and expected checks

The report states that **GNSS1** is at the rear of the slope, with cumulative horizontal displacement **4.5 mm** and mean rate **0.15 mm/d**. **GNSS3** is at the front, with **15.0 mm** and **0.50 mm/d**. The difference in cumulative displacement is **10.5 mm**. Both points were observed from **1 to 30 June 2026**, a 30-day period. Values and rates belong to their named rows in Table 1. Figure 1 is a monitoring-point location schematic, not a source for exact measured spacing.

The report explicitly provides **no GNSS2**, precise GNSS1–GNSS3 spacing, rainfall amount, groundwater level, failure-surface depth or stability factor. A response should not substitute another point's measurements or infer these quantities from the schematic. Expected checks are factual targets, **not exact answer strings**; citations must support the associated claims.

## Observed test result and known limitations

On 13 November 2026, a local-rule run completed, followed by a DeepSeek extraction run and a live Neo4j/QA check in a separate test copy. In the live run, graph storage reported 7 text blocks, 1 table with 3 rows and 12 cells, 1 figure, 12 accepted event nodes and zero storage errors. The requested extraction model was `deepseek-chat`; QA response metadata reported `deepseek-flash`, so the requested label does not establish an exact provider backend snapshot.

Nine questions were asked sequentially in **one** Streamlit chat session. Manual report checks classified **6 as pass, 2 as partial and 1 as fail**. This is a diagnostic smoke test, not a general success-rate estimate or the paper's experiment. The failure concerned the observation period: the date range was present in prose, but retrieval selected only table evidence and the system incorrectly refused. One correct refusal about absent GNSS2 lacked a direct supporting citation. The figure-location answer found a figure carrier, but a browser-open action was not recorded. In addition, both table-derived events were sent to review by a numeric-unit rule despite the table carrier retaining units; a schematic was misclassified as a plan view; and DOCX page metadata did not match Word's layout pagination. **These issues remain unresolved in this release.**

| Question IDs | Manual outcome | What the recorded check showed |
| --- | --- | --- |
| SYN-01–SYN-04, SYN-06, SYN-08 | Pass | Named-point facts, arithmetic or an appropriate refusal matched the report and were supported by available evidence. |
| SYN-05 | Fail | The system refused an answerable monitoring-period question after retrieving table evidence but missing the date range in prose. |
| SYN-07 | Partial | The refusal about absent GNSS2 was correct, but the cited events did not directly establish absence. |
| SYN-09 | Partial | Figure metadata and a local image path were returned, but a user opening the image was not observed. |

Local outputs, QA logs, uploaded reports and credentials are intentionally excluded from the public repository. The tutorial and released sample establish a runnable input and known checks; they do not independently reproduce the original restricted-source pipeline or validate every semantic event. For numerical reconstruction of the published ratings, use the separate [paper reproduction example](../paper_reproduction/README.md).
