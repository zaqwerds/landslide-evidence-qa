# DeepSeek configuration and recorded experimental settings

This document separates settings read from the application source from settings recorded during the paper experiments. Documentation was checked against the local files on 13 November 2026. No live API request was made during this check, and no credentials are included here.

## 1. Current application defaults

These are editable defaults in the current open-source application, not a claim about every historical run.

| Setting | Knowledge extraction | Evidence-based answer generation |
| --- | --- | --- |
| Provider | `deepseek` when DeepSeek is selected | `deepseek` when DeepSeek is selected |
| Default API base | `https://api.deepseek.com` | `https://api.deepseek.com` |
| Request endpoint | API base followed by `/chat/completions` | API base followed by `/chat/completions` |
| Request model identifier | `deepseek-chat` | `deepseek-chat` |
| `temperature` | `0.1` | `0.1` |
| `max_tokens` | `4096` | `900` |
| Client request timeout | `120` seconds | `60` seconds |
| `top_p` | Not explicitly sent | Omitted by default; sent only when a non-null value is supplied to the generator constructor |
| Message roles | `system` and `user` | `system` and `user` |
| Explicit `response_format` | Not sent; JSON output is requested in the prompt | Not sent |
| Explicit streaming, seed or penalty settings | Not sent | Not sent |

Here, `max_tokens` is the requested output-token limit, not the input context-window size or a guaranteed response length. The local records do not establish the provider's exact context-window limit. An omitted parameter must not be reported as an explicitly fixed numeric value.

The extraction instructions request structured JSON. A prompt request for JSON is distinct from setting an API-level structured-output mode. In QA, the default constrained prompt requires answers based on supplied evidence and evidence identifiers. A separate free-generation mode is used in the controlled comparison.

### Where the settings are defined

- [`extraction/event_extractor.py`](../extraction/event_extractor.py): provider defaults, extraction request payload and HTTP call.
- [`backend/pipeline.py`](../backend/pipeline.py): pipeline extraction defaults.
- [`qa/answer_generator.py`](../qa/answer_generator.py): QA constructor defaults, request payload, optional `top_p` and response metadata.
- [`webapp/app.py`](../webapp/app.py): editable model, endpoint, temperature, output-token limit and timeout fields.

To configure the application, select DeepSeek in the web sidebar, enter the endpoint and model identifier, and set the extraction and QA fields separately. Provide the API key through the password-style sidebar field or the `DEEPSEEK_API_KEY` environment variable. Never put an actual key in documentation, example configurations, public logs or version control.

### Failure behavior

Neither of the two inspected low-level HTTP call methods contains an automatic retry loop. This statement concerns those methods; it is not a reconstruction of all historical runner behavior.

The extraction HTTP method raises an error on a request failure. Local JSON repair and fallback parsing are response-processing steps, not additional API calls. The QA HTTP method records failure metadata and returns an empty result; its caller can return a template-based evidence list instead. That fallback must not be counted as a successful model-generated answer. Check `api_called`, `api_success` and the returned model-use flag when interpreting outputs.

## 2. Recorded three-run ablation used in the paper

The historical run identifier is `20261021_151058_897795`. Its configuration records a start time of **21 October 2026, 15:10:58** and its summary records completion at **15:40:34** on the same date. These are stored clock times; the records inspected here do not specify a UTC offset.

Recovered local server logs on that date identify Neo4j Enterprise **2026.01.4**, listening on localhost port 7687, consistent with the saved experiment URI. Its startup records Azul OpenJDK **21.0.12+8-LTS**. This is distinct from the newer 2026.10.2 installation and the current Neo4j Desktop 2.3.0 application. See [environment evidence](environment/README.md) for timestamps, provenance and the scope of this attribution.

The public answer-and-score CSV and all 690 original result records agree on the following settings:

| Recorded item | Value |
| --- | --- |
| Provider | `deepseek` |
| Requested model identifier | `deepseek-chat` |
| Response model identifier | `deepseek-flash` |
| `temperature` | `0` |
| `max_tokens` | `900` |
| `top_p` in the original generation metadata | `null`; the inspected request code omits this field when null |
| Recorded API success | `true` for all 690 answers |
| Condition A | Structured evidence with constrained generation; 100 questions, three runs, 300 answers |
| Condition B | Flattened table evidence with constrained generation; 30 table questions, three runs, 90 answers |
| Condition C | Structured evidence with free generation; 100 questions, three runs, 300 answers |

The requested and returned model identifiers are reported verbatim. They are not interchangeable, and neither identifier alone establishes an immutable model snapshot or exact backend release. Do not silently relabel the historical run using a provider's current model description. Temperature zero also does not guarantee identical outputs across repeated calls.

A and C are the controlled generation comparison using the same frozen evidence. A and B use the same underlying table cells in different representations. This offline frozen-evidence experiment is distinct from the end-to-end online KGQA benchmark.

### Evidence sources and limits

The public data file currently resides at:

[`paper_data/03_three_run_ablation/answers_and_scores.csv`](../paper_data/03_three_run_ablation/answers_and_scores.csv)

Its relevant fields are `requested_model`, `response_model`, `temperature`, `max_output_tokens`, `condition`, `repeat` (run index) and `api_success`. The Chinese question and answer text is retained as experimental source material. The [field crosswalk](../paper_data/field_crosswalk.csv) preserves the original Chinese field names.

The original local evidence inspected for this note comprises `实验配置.json`, `实验运行摘要.json` and `消融实验原始结果.jsonl` in the folder ending in the run identifier above. Those original records contain additional restricted report-derived material and are not copied into the public repository by this documentation update.

The inspected historical per-answer metadata does **not** record the request timeout or effective endpoint. The source-code defaults are documented in Section 1, but are not asserted as independently recorded historical values. Exact backend snapshot, effective provider-side defaults and context-window allocation were not established by these records. Parameters from this ablation must not be assigned automatically to the separate five-system benchmark, extraction runs or conversational-model tests.

For a methods description of this ablation, the supported statement is: “Generation requested `deepseek-chat` with temperature 0 and a maximum of 900 output tokens. All 690 response records identified the returned model as `deepseek-flash`. The `top_p` field was not explicitly set.” The statement does not identify a pinned model release.

## 3. Records to retain for new runs

Record the invocation date and timezone, endpoint without credentials, requested model, returned model, generation parameters, timeout, generation mode, table representation, evidence and prompt hashes, API success, fallback status and token usage. Keep credentials and restricted source text out of public metadata. Publish only data that the authors are authorized to share.

This section recommends future provenance fields; it does not claim that every field is already present in every current output.
