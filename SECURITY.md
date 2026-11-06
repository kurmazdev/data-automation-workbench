# Security

This application is designed for one user on a local computer. Bind the server to `127.0.0.1`; do not expose it directly to the internet. Hosting it for other users requires authentication, authorization, deployment isolation, and a separate security review.

Do not commit uploaded files, extracted records, database files, credentials, environment files, logs, or browser traces. The repository ignore rules exclude common runtime and tooling paths. Review the complete staged diff before every publication.

Report suspected vulnerabilities privately through the repository's security reporting feature when available. Do not put credentials, sensitive data, or exploitable details in a public issue. No private reporting address is embedded in this project.

Install dependencies from the documented manifests and lockfiles. Recheck advisories when updating dependencies; successful tests and a clean vulnerability scan do not establish that all possible vulnerabilities are absent.
