# Environment information and evidence

Local information was inspected on **13 November 2026**. Current observations, historical log evidence and the newly validated release environment are listed separately.

## 1. Current reference workstation

| Item | Observed value |
| --- | --- |
| Operating system | Microsoft Windows 11 Home, Chinese edition, 64-bit |
| Windows version/build | NT version 10.0.26200; build 26200 |
| Processor | AMD Ryzen 5 5500U with Radeon Graphics |
| CPU topology | 6 physical cores, 12 logical processors |
| Installed memory modules | 17,179,869,184 bytes, or 16 GiB (nominal 16 GB configuration), from physical-memory module capacities |
| System-reported physical memory | 16,483,872,768 bytes, approximately 15.35 GiB |
| Base Python installation inspected | Python 3.11.9, 64-bit |
| Neo4j Desktop application | 2.3.0, from the installed-application registry |
| Current system timezone | China Standard Time, UTC+08:00 |

Windows version APIs can report an NT version beginning with 10.0 on this Windows 11 machine. The operating-system caption and build were inspected together; the version string was not used to relabel it as Windows 10.

These are current reference-machine observations, not independently archived hardware/OS settings for every historical experiment. They are not minimum computational requirements. No dedicated GPU is needed by the default cloud-API pathway; no local model inference benchmark was performed.

## 2. Neo4j: historical server versus later installation

The computer contains multiple database installations. Neo4j Desktop's application version is not the Neo4j server version.

| Evidence | Observed value | Interpretation |
| --- | --- | --- |
| Historical installation `packaging_info` | Version 2026.01.4; Edition Enterprise | Installed server identity corroborating the historical log |
| Historical `neo4j.log`, line 942 | `2026-10-21 07:03:47.569+0000 INFO ======== Neo4j 2026.01.4 ========` | A local Neo4j 2026.01.4 server started on the ablation date |
| Same log, line 948 | `2026-10-21 07:03:52.008+0000 INFO Bolt enabled on localhost:7687.` | The server listened on the port used by the saved experiment configuration |
| Same instance `debug.log`, line 14169 | At `2026-10-21 07:03:47.852+0000`: OpenJDK 64-Bit Server VM; Azul Systems, Inc.; `21.0.12+8-LTS` | JVM version recorded for that server startup |
| Saved three-run ablation configuration | Run `20261021_151058_897795`; URI `neo4j://127.0.0.1:7687`; local recorded start `2026-10-21 15:10:58` | The recorded endpoint is consistent with the historical local listener |
| Historical server log on 27 October | Neo4j 2026.01.4, with the same localhost Bolt port | Corroborating server activity later in October |
| Another installation's `packaging_info` | Version 2026.10.2; Edition Enterprise | A newer server also exists locally |
| Newer installation's retained `neo4j.log`, line 6 | `2026-11-12 08:27:21.574+0000 INFO ======== Neo4j 2026.10.2 ========` | First startup in that installation's retained log; not evidence of using it for the October experiment |

The recovered historical local-server record therefore supports reporting **Neo4j Enterprise 2026.01.4** for the server active on the three-run ablation date, with **Azul OpenJDK 21.0.12+8-LTS**. Do not substitute 2026.10.2 merely because its version identifier refers to October. The evidence links the local listener and experiment configuration by date/port; it is not an independent per-query server-version record for every historical test.

The log timestamps explicitly use UTC. The current configured timezone is UTC+08:00; 07:03 UTC corresponds to 15:03 in that timezone. The experiment configuration itself did not store a timezone offset, so its original timestamp is retained without retroactively adding one.

No database was started, queried or modified to recover this information. Raw logs can contain private configuration and are not redistributed. Selected version evidence and source hashes are recorded in [version_evidence.json](version_evidence.json); local account names, instance UUIDs, credentials and complete log messages are omitted.

## 3. Dependency snapshots and their meaning

| File or source | Scope | What it establishes |
| --- | --- | --- |
| [`requirements.txt`](../../requirements.txt) | Current direct application dependencies | Intended installation requirements; not a complete historical environment |
| [`requirements-lock-windows-py311.txt`](../../requirements-lock-windows-py311.txt) | 92-package isolated release-validation environment | Exact installed package versions for the successful new Windows/Python 3.11.9 validation |
| [`base_python311_inventory_20261113.txt`](base_python311_inventory_20261113.txt) | 147 packages currently installed in the base Python 3.11.9 environment | Observation made on 13 November; includes packages unrelated to this application |
| Original application's local `requirements.txt` | Unpinned library names | Indicates intended libraries but does not establish their historical installed versions |

The base-environment inventory is not a recommended installation file or an October snapshot. It was obtained from installed-package metadata without installing, upgrading or removing packages in that base environment. The recorded names and versions contain no package download URLs or credentials.

Important packages currently observed in both the base installation and the release environment include python-docx 1.2.0, NumPy 2.4.4, pandas 3.0.3, SciPy 1.17.1, requests 2.33.1, py2neo 2021.2.4, RDFLib 7.6.0, Streamlit 1.61.1 and sentence-transformers 5.6.1. Their agreement does not prove that those exact versions were installed during the October experiments.

No full, timestamped historical Python dependency freeze was recovered in the inspected project requirements/environment files. The repository preserves that gap rather than presenting the current inventory as historical evidence. The conversational models' immutable backend versions also remain unestablished by the local material inspected here.

See [release validation](../../VALIDATION.md) for actual execution checks and [DeepSeek configuration](../deepseek_configuration.md) for recorded generation parameters.
