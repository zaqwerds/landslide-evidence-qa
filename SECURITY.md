# Security and data handling

The application listens on `127.0.0.1:8501` by default and has no user authentication. It is intended for local research use. Do not expose it directly to the Internet or an untrusted shared network.

Uploaded ontologies, reports, extracted evidence, prompts and answers are stored under `input/`, `uploads/`, `artifacts/` and `output/`. Graph instances are stored in the configured Neo4j database. Cloud extraction and generation send relevant report fragments, questions and evidence to the configured API. Process only data that you are authorized to use and transmit.

Credentials entered in the interface are used for the running session. The run configuration excludes the Neo4j password; this does not guarantee that every output or exception is free of sensitive information. Treat runtime directories and the database as sensitive. Do not publish them. Review errors before sharing them.

Database cleanup removes all report instances in the connected database; local carrier cleanup removes extracted tables and images. Both can invalidate source links. Use a dedicated test database and retain data that must be preserved.

For vulnerabilities, use the repository's private reporting feature if available. Otherwise create an issue without exploit details or credentials and request a private contact channel. Do not publish exploitable details or restricted source material.

Source-report restrictions are explained in [DATA_AVAILABILITY.md](DATA_AVAILABILITY.md).
