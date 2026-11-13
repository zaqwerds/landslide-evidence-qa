# Landslide Report Knowledge Graph and Evidence-Constrained Question Answering

Public repository: [zaqwerds/landslide-evidence-qa](https://github.com/zaqwerds/landslide-evidence-qa).

This application parses landslide investigation reports, organizes engineering facts and their original sources in Neo4j, and answers questions using retrieved evidence. It supports report-specific selection so that evidence from different reports is not mixed.

The workflow is: report upload, text/table/figure parsing, ontology-guided knowledge extraction, conservative fusion, programmatic quality control, graph storage, evidence retrieval, and answer generation with source references.

The core application and optional paper companion materials are separate. `paper_data/` contains authorized public experimental results; `examples/paper_reproduction/` provides offline numerical reconstruction. Neither is needed to run the application. TextRAG is an independent comparison method and is not integrated into the core system.

## 1. Scope and language

- Inputs are DOCX reports or PDFs with selectable text. The implementation is primarily designed for Chinese landslide reports.
- Tables retain row/cell information, original values, units, and HTML/JSON carriers.
- Figures retain image files, captions, document positions, and metadata. The application does not perform OCR or visual content understanding.
- The web interface and generation prompts are Chinese. Chinese interface labels are included below so that English-speaking readers can locate the controls. Changing the documentation language does not change the prompts, database labels, or scientific behavior.
- Rule-based extraction is available for local testing. It is not the language-model extraction condition used in the paper.

## 2. Prerequisites and computational requirements

| Component | Requirement or current status |
| --- | --- |
| Python | Python 3.11; the local reference interpreter is 3.11.9 |
| Operating system | Current reference workstation: Windows 11 Home (Chinese edition), 64-bit, build 26200. Linux/macOS operation has not been independently validated for this release |
| Python dependencies | Install the pinned direct dependencies in `requirements.txt`. This is not a complete transitive lockfile |
| Neo4j | A separately installed, running instance is required for graph storage, result browsing, and graph QA. Configure its URI, username and password in the sidebar |
| Neo4j version | Recovered server logs on the October ablation date show Enterprise 2026.01.4 with Azul OpenJDK 21.0.12+8-LTS. Another local installation is 2026.10.2; it is not substituted for the historical record. Neo4j Desktop is separately versioned as 2.3.0. See the environment evidence below; no fresh database integration was performed |
| GPU | No dedicated GPU is required by the default cloud-API workflow. A separately hosted local model has its own hardware requirements |
| CPU and memory | Parsing, graph client operations, and rule-based extraction run locally. The reference workstation has an AMD Ryzen 5 5500U (6 cores/12 logical processors) and approximately 15.4 GiB of system-reported RAM. These are reference specifications, not measured minimum requirements |
| Storage | Allow space for the Python environment, uploaded reports, duplicated original carriers, checkpoints, logs, and the Neo4j database. Requirements scale with report size and image count; no minimum disk-space benchmark has been established |
| Network and costs | Cloud extraction and answer generation require network access and a user-funded API account. Provider latency, limits, model availability and charges are external to this software |
| Local model option | Supply your own running OpenAI-compatible endpoint. This repository does not bundle model weights or start a model server |

A parsing-only run can disable Neo4j writing. Such a run creates local files but does not create a graph that the QA tab can query. Scanned PDFs are retained as page images; they do not become searchable text.

The exact environment used for the release checks is recorded in [requirements-lock-windows-py311.txt](requirements-lock-windows-py311.txt). Use it for the tested Windows/Python 3.11 combination; the ordinary `requirements.txt` remains the direct-dependency list. See [VALIDATION.md](VALIDATION.md) for what was and was not tested.

[Environment information and evidence](docs/environment/README.md) separates the historical Neo4j startup logs, current workstation observations, the 147-package base-Python inventory and the 92-package isolated validation environment. A complete historical Python freeze was not recovered; neither current snapshot is presented as an October experiment snapshot.

## 3. Installation and launch

Run commands from the repository root. On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe launch_app.py
```

If using an existing Python 3.11 environment:

```text
python -m pip install -r requirements.txt
python launch_app.py
```

The browser should open at http://127.0.0.1:8501 . If it does not, open that address manually. The launcher binds to the local loopback address; do not expose this unauthenticated research interface to the Internet.

Start Neo4j separately before a graph-storage or QA run. The application tests a connection but does not install or start the database. Stop the web server with Ctrl+C in the terminal that launched it.

Release checks and their exact scope are recorded in [VALIDATION.md](VALIDATION.md). Offline checks do not establish live model-service or Neo4j integration, and the current release does not include an unrestricted copy of the original report.

## 4. Ontology preparation

A Turtle ontology is required for report processing, including rule-based processing.

1. Obtain an ontology that you are authorized to use.
2. Open the application and find **上传本体文件（TTL）** (Upload ontology file) in the sidebar.
3. Upload the TTL file. It is syntax-checked and saved locally as `input/ontology.ttl`.
4. The saved ontology is reused on later visits. Upload another TTL to replace it.

A syntactically valid Turtle file is not necessarily suitable for this application. The implemented class mappings and rules are designed for a landslide schema; check compatibility before using a different ontology.

`examples/demo_ontology.ttl` is a project-authored minimal demonstration ontology. It can exercise the upload mechanism and a small synthetic workflow, but it does not replace the full research ontology or reproduce its concept coverage.

The fictional DOCX and step-by-step checks for that workflow are provided in the [synthetic report tutorial](examples/synthetic_demo/README.md). They allow a source-to-output demonstration without disclosing the restricted case-study report.

The research ontology `KnowledgeSet_Landslide_CN.ttl` is not redistributed. Its recorded sources are the [provider's original file](https://github.com/zhiyuanxu839-bit/---/blob/master/KnowledgeSet_Landslide_CN.ttl) and [dataset page](https://www.noda.ac.cn/datasharing/datasetDetails/698941176acb974efd3a0c43). Check the provider's conditions yourself. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md); this project's MIT license does not relicense third-party material.

## 5. Inputs, outputs, and local storage

| Input | Meaning |
| --- | --- |
| DOCX | Native text, Word tables and embedded images; recommended for testing structured table handling |
| PDF | Selectable text, reconstructed tables and available images; extraction depends on PDF layout |
| TTL | User-supplied, compatible ontology or the limited demonstration ontology |
| Question | A natural-language question about the selected report |
| Model/database configuration | Provider, endpoint, model, credentials and processing options supplied through the sidebar |

Generated files remain on the machine running the application:

| Location | Contents and intended use |
| --- | --- |
| `input/` | Ingested report copies and the locally saved ontology |
| `uploads/` | Reports uploaded through the browser |
| `artifacts/` | Extracted table HTML/JSON and original image carriers, grouped by report |
| `output/<report_id>/runs/<run_id>/` | Configuration, parsed blocks, extracted records, fusion/quality-control decisions, accepted knowledge and run summaries |
| `output/qa_sessions/` | Answer sessions, retrieved evidence, generation metadata and source references |
| Neo4j | Report, text, table, cell, figure, event, property and source-association records |

Typical checkpoints include `01_document_blocks.json`, `02_multimodal_knowledge.json`, `03_fused_knowledge.json`, `04_validation.json`, `05_accepted_knowledge.json`, and `99_run_summary.json`. The final summary reports stage timings and record counts.

A report identifier is derived from file contents. Editing a report can produce a new identifier. Rebuilding identical contents replaces that report's graph instances while preserving other reports. Paths returned as evidence refer to local files, not public URLs.

## 6. Options in the web interface

### Connection and model settings

Select **正文抽取方式** (Text extraction mode): **大模型** (Language model) or **本地规则** (Local rules). Select a provider and enter its actual model name and API endpoint.

The prefilled provider/model names are editable defaults, not guarantees that the provider still serves those models. When **local** is selected, an already running compatible model endpoint is required. Selecting Local rules does not by itself start a local language model or provide generated QA answers.

Enter API credentials in **API Key**. A blank field falls back to the corresponding process environment variable. Enter Neo4j URI, user and password, then use **测试 Neo4j 连接** (Test Neo4j connection).

For the DeepSeek endpoint, request settings, failure behavior and the distinction between application defaults and the recorded three-run ablation, see [DeepSeek configuration and recorded experimental settings](docs/deepseek_configuration.md). The application defaults must not be substituted for historical experimental parameters.

### Processing and generation options

| Sidebar option | Default | Behavior |
| --- | --- | --- |
| 文字分段上限 | 0 | Maximum text blocks to process; 0 means all blocks |
| 每段最大字符数 | 1500 | Target maximum segment length; document structure can affect boundaries |
| 执行知识验证 | Enabled | Apply semantic consistency and schema/rule checks |
| 写入Neo4j | Enabled | Store the resulting report graph; disable for local processing only |
| 抽取温度 | 0.1 | Extraction request temperature |
| 单段抽取输出 Token 上限 | 4096 | Output-token cap for an extraction request, subject to provider support |
| 单次抽取请求超时（秒） | 120 | Extraction request timeout |
| 验证最低置信度 | 0.3 | Global floor; event-type-specific thresholds can be stricter |
| 回答温度 | 0.1 | QA generation request temperature |
| 回答输出 Token 上限 | 900 | QA output-token cap |
| 回答请求超时（秒） | 60 | QA generation request timeout |
| 最多检索证据数（0为自动） | 0 | 0 selects an adaptive budget; a positive value is a cap, not a requested exact count |
| 表格证据格式 | 结构化 | Preserve header/value/unit relationships; 传统文本 selects the legacy textual representation |

The adaptive selector currently limits the final evidence budget to 3-14 items. A manual cap cannot increase it beyond the automatic budget. Candidate queries are also bounded: 200 tables, 500 figures, 1000 text blocks and 1000 events per report. At most four matching rows per table are selected, or the first three when no row clearly matches. Serialized evidence is truncated to 16,000 characters before generation. These limits may reduce coverage for long reports or whole-table questions.

Quality-control thresholds and numerical ranges are heuristics. Passing them does not establish independent expert-verified correctness.

## 7. How-to: build and query your own report

1. Launch the web application and upload a compatible ontology in the sidebar.
2. Configure the extraction provider, endpoint, model and API key. For a no-API processing test, select **本地规则**.
3. Configure a dedicated Neo4j database and test the connection. If you only want local parsing/extraction outputs, uncheck **写入Neo4j**.
4. Open **报告处理** (Report processing). Choose **上传新报告** (Upload new report), select a DOCX/PDF, and click **开始解析并构建图谱** (Parse and build graph).
5. Wait for all processing stages. Inspect the completion summary, warnings, quality-control decisions and generated carriers. A completed run is not a guarantee that every engineering fact has been extracted correctly.
6. If Neo4j writing was enabled, open **结果浏览** (Result browsing), select the report, and inspect its tables, figures and events.
7. Open **图谱问答** (Graph QA), select the intended report, and enter a question. Evidence queries are restricted to that report.
8. Inspect the supporting paragraph/table/image, not just the fluency of the generated answer. Keep local carrier files available for source navigation.

The latest successfully built report becomes the preferred selection. Select the intended report explicitly when comparing different files.

## 8. How-to: use the synthetic example or your own authorized report

For a complete fictional input with a Word table, a schematic, nine example questions and known result checks, start with the [synthetic report tutorial](examples/synthetic_demo/README.md). This is a runnable **demonstration**, not the source report or a rerun of the paper's historical experiment. The documented smoke test includes one false refusal and other unresolved limitations.

The authors do not have the rights to distribute the complete original report and source data. Where access is necessary for research verification, contact the corresponding author using the contact details in the manuscript; access remains subject to the relevant rights holders' permission. See [DATA_AVAILABILITY.md](DATA_AVAILABILITY.md).

For a local processing check, select an authorized report with native text and a table whose contents you can inspect. Upload a compatible ontology, select **本地规则** (Local rules), and disable Neo4j writing. This exercises ingestion, parsing, rule extraction, fusion and quality control without a model API. Inspect the generated checkpoints and confirm that stored table cells retain the report's objects, values and units. The minimal demo ontology can test loading, but does not reproduce full research-schema coverage.

For graph storage and QA, start a dedicated Neo4j instance, configure its credentials, enable writing and rebuild the report. Select that report in the QA tab. Configure a generation API if you want model-composed answers rather than a template evidence list.

| Typical operation | What to inspect |
| --- | --- |
| Ask for a named monitoring point's value in a specified table | Correct object, indicator, value and unit; supporting table and cell provenance |
| Ask to locate a numbered figure | Matching caption and accessible original carrier, without invented visual interpretation |
| Ask for a measurement absent from your report | An explicit explanation of missing evidence, rather than an invented value |
| Open a returned HTML table or image | The file exists and supports the associated answer; local paths are not public URLs |

These are inspection criteria, not guaranteed generation outcomes. Event counts and model answers depend on the report, ontology and model service. To test numerical paper-result reconstruction without supplying a report, use the separate [offline example](examples/paper_reproduction/README.md).

## 9. Expected behavior and troubleshooting

| Situation | Expected behavior or action |
| --- | --- |
| No ontology is available | The sidebar requests a TTL; report processing will not start |
| No cloud API key is available in language-model mode | The application reports the missing configuration before extraction |
| Local rules are selected | Processing can proceed without cloud extraction; this is not the paper's LLM extraction setting |
| Neo4j writing is disabled | Local files are produced; there is no newly written graph for the QA tab to query |
| No evidence is retrieved | The answer states that the graph has no evidence able to answer the question |
| QA API is unavailable or no key is configured | The current implementation falls back to an evidence list; inspect generation metadata before treating it as an LLM-generated answer |
| A scanned PDF has no searchable text | Page images may be retained, but no OCR-derived text is generated |
| Several reports are loaded | Choose the report in the QA/results tab; do not assume the previous selection is still intended |
| A source link fails | Check that its local artifacts have not been moved or deleted |
| The browser does not open | Visit http://127.0.0.1:8501 manually; check whether another application occupies the port |
| Database connection fails | Check that the instance is running and that URI, username, password and server/client compatibility are correct |
| A large report misses information | Check candidate limits, evidence budget, row selection, truncation and extraction warnings before attributing the result to generation |

Two destructive maintenance buttons are independent: **清理Neo4j数据** (Clear Neo4j data) removes all report instances in the connected database, not only the selected report; **清理本地表格和图片** (Clear local tables/images) removes extracted local carriers and can break existing evidence links. Neither operation is required for normal report switching. Do not use them on a database or directory containing data you need to retain.

## 10. Reuse and paper-result reproducibility

Using another report exercises the same method on new data; it does not reproduce the original case-study measurements or scores.

The original field report, full original tables/images and verbatim source-evidence packages are not included. User authorization in this project does not permit public distribution of that report. The [fictional example](examples/synthetic_demo/README.md) exercises the released application, but it does not replace restricted source material. The actual basis for any data-access restriction should be documented in the manuscript's data-availability statement.

Authorized questions, reference answers, recorded answers, ratings and statistical tables are included in [paper_data/](paper_data/). They use the separate [CC BY 4.0 license](paper_data/LICENSE.md). English names and documentation accompany the original Chinese question/answer content. Existing redactions are recorded; ratings are unchanged. See the [evaluation definitions](paper_data/EVALUATION.md).

The independent [paper-result reconstruction example](examples/paper_reproduction/README.md) recalculates summaries and paired statistics without APIs, Neo4j or the source report. It is not required by the core application and does not regenerate answers, re-rate them or independently verify extraction/retrieval. Restricted-source access requests should be directed to the corresponding author as explained in [DATA_AVAILABILITY.md](DATA_AVAILABILITY.md).

Experimental scripts should record the code version, ontology version, model identifier, configuration and date. This open-source version contains generalization changes relative to the historical experiment implementation, including extraction-prompt cleanup and report-specific scoping. It is not represented as a byte-identical snapshot of the paper's historical code.

The application, fictional demonstration and authorized paper companion data are available in the [public repository](https://github.com/zaqwerds/landslide-evidence-qa). Cite the specific commit or release used when reconstructing results. Repository publication does not grant access to the restricted original report or imply that the open-source application is a byte-identical historical experiment snapshot.

## 11. Security, licensing, and publication checklist

Reports, uploaded ontologies, extracted evidence, prompts and answer logs may contain sensitive information. The application stores them locally and sends relevant report fragments to the configured model API when cloud processing is used. Confirm authorization before processing or sharing such data.

Neo4j passwords are excluded from the run configuration JSON. This is not a universal log-sanitization guarantee. Never publish credentials or local runtime directories. See [SECURITY.md](SECURITY.md).

The project code is released under the [MIT license](LICENSE), with the copyright notice identifying Zhong Junnan. Third-party materials remain under their own terms; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Contribution guidance is in [CONTRIBUTING.md](CONTRIBUTING.md).

Before public release:

- Confirm the license notice and third-party permissions.
- Inspect the tracked-file list, staged changes and full Git history for credentials and restricted material.
- Keep `input/`, `uploads/`, `artifacts/`, `output/`, virtual environments and caches excluded.
- Keep the external research ontology out of the repository; only the project-authored `examples/demo_ontology.ttl` is currently approved for inclusion.
- Read the restricted-source declaration and confirm that public results and the fictional demonstration are distinguished from unshared source data.
- Keep comments and docstrings in English without translating experimental prompt strings or database labels.
- Publish normal, browsable repository files, not a single ZIP/RAR/7z attachment as the sole submission artifact.
- Verify that reviewers can access the public repository and that the manuscript contains its actual URL.

Useful read-only checks:

```text
git ls-files
git diff --cached --stat
git log --all --name-only --pretty=format: -- KnowledgeSet_Landslide_CN.ttl
```

The last command should list no external ontology file; it requires an existing commit history. A previously tracked file is not removed from history merely by adding it to `.gitignore`.
