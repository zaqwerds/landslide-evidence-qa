# Data and code availability

## Restricted source report and complete source data

The authors do not have the rights to publicly distribute the complete original landslide investigation report or the complete source data. These materials are not included in this repository. The restriction also applies to original report figures, complete original tables and verbatim source-evidence packages that are not explicitly cleared for release.

Where access is necessary for research verification, please contact the corresponding author using the contact details in the associated manuscript. Any access is subject to authorization and the conditions of the relevant data rights holders. A request does not imply that access can be granted; the authors cannot guarantee redistribution permission.

## Public experimental results

The authors have confirmed authorization to release the curated experimental materials in [paper_data/](paper_data/), including questions, report-checked reference answers, recorded system answers, original ratings, the historical 35-question rater/adjudication records and statistical results. No separate provisional re-adjudicated dataset is included. These curated data are licensed under **CC BY 4.0**; see [paper_data/LICENSE.md](paper_data/LICENSE.md).

The experiments used a Chinese investigation report. Original Chinese questions, reference answers, system answers and source quotations are retained to avoid changing objects, values, units or rating evidence. Folder names, filenames, fields and evaluation-method documentation are provided in English. Existing redactions are documented; the ratings refer to the original, pre-redaction answers.

## Reproducibility scope

Released scores support offline reconstruction of numerical summaries and paired comparisons using [examples/paper_reproduction/](examples/paper_reproduction/). This example needs no Neo4j, model API or restricted report. It does not regenerate answers or independently establish that report-derived reference answers are correct.

Replaying the original parsing, extraction, retrieval and generation requires authorized access to the source report, relevant ontology, historical evidence packages and model service. Not all are provided here. A separate [fictional DOCX example and tutorial](examples/synthetic_demo/README.md) are provided to test the released application's source-to-output workflow. The example is not a substitute for the original case-study report, and the observed smoke-test limitations are documented. Users may also run the application on their own authorized, compatible reports following the README tutorial. The fictional input report and its recorded test document are licensed separately under [CC BY 4.0](examples/LICENSE.md); that permission does not apply to the restricted original report.

The open-source application includes generalization and documentation changes relative to the historical implementation. It is not a byte-identical archive of the experimental code. The five-system comparison describes the recorded application configurations; the A/C ablation is the matched frozen-evidence generation comparison.

## Code and third-party materials

Project-authored code is licensed under [MIT](LICENSE). Third-party materials retain their own terms. The external research ontology is not redistributed or relicensed; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The public code, fictional demonstration and authorized experimental materials are hosted at [https://github.com/zaqwerds/landslide-evidence-qa](https://github.com/zaqwerds/landslide-evidence-qa). Cite the specific commit or release used. The associated manuscript should include this repository URL; the original source-data restrictions above remain in effect.
