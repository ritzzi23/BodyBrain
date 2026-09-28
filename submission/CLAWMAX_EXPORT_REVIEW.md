# ClawMax export review

Original file: `bodybrain-2026-09-28.zip` (unchanged).

- Native ClawMax workspace export, format version 1.0.0.
- Workspace name: BodyBrain.
- Exported: September 28, 2026, 15:35:35 UTC.
- Size: 29,487 bytes; 53 archive entries including directories.
- SHA-256: `f458aeecb55734092aa4fde0d26a47d84b169ca41f88ce2e5d2794189005f323`.
- Contains `bodybrain-ingestion` and `bodybrain-evidence`, both workflow
  definitions, and the BodyBrain organization template.
- Contains nonsecret provider defaults, including the existing Cognee tenant URL,
  test dataset name, and selected model. These settings are configuration, not
  credentials or proof of current runtime readiness.

ZIP integrity, duplicate-member, path-traversal, and symbolic-link checks passed.
No configured local credential values or common provider-key/private-key/JWT
patterns were found. The USER and memory files inspected contain placeholders
and empty daily notes; no chat transcript or source-document files are present.
The six notifications record workspace artifact creation. The export also
contains two diagnostic Python scripts; they were inspected, not executed.
This is a bounded inspection, not a guarantee against every possible secret form.

## What it does not contain

The archive does not contain the complete React/FastAPI application, anatomy
assets, the shared `bodybrain` skill implementation, or the detached hosted relay
worker and ledger. The agent tool files reference the shared skill, so provide
the accompanying project source for reproducibility. Those implementations are
under `integrations/clawmax/` in the source package.

The native export manifest explicitly says automatic import/restore is not yet
implemented in this ClawMax version. Describe this as an exported workspace for
review/manual recovery, not a tested one-click restoration. Provider credentials
must be supplied separately through the target runtime's supported mechanism.

## Submission files

- Use the original native export for the portal's ClawMax ZIP upload option.
- The combined source submission includes an identical copy at
  `BodyBrain/submission/clawmax/bodybrain-2026-09-28.zip`, plus the full project,
  setup instructions, this review, and the submission guide.
- Current hosted relay limitations are documented in SUBMISSION_GUIDE.md.
- No files were uploaded, pushed, or submitted during this review.
