# Isolated local browser checks

Run the production build, then start these commands in separate terminals:

```sh
npm run build
backend/.venv/bin/python scripts/browser-test-server.py
BODYBRAIN_API_URL=http://127.0.0.1:8082 node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 3017 --strictPort
```

Open http://127.0.0.1:3017 in a test browser profile. This API uses temporary
storage and disables real providers. Browser localStorage belongs to this test
origin and survives server shutdown. Use synthetic text only.

Verified September 28, 2026 through the rendered Chrome UI:

1. Open Records & memory, paste `No fracture of the left femur.` with the title
   `BROWSER CHECK — Synthetic femur`. Confirm it needs review.
2. Review and approve the finding. Ask `What does my record say about the left
   femur?` and confirm the exact quotation, record title, and page citation.
3. Reload the page, reopen Ask your records, and confirm the exchange and citation
   remain visible.
4. Check a narrow viewport: record controls and the dialog remain usable without
   horizontal page overflow. Restore the normal viewport afterward.
5. Select Heart, add `BROWSER CHECK — Synthetic note about the heart.`, and save.
   Confirm the browser note links to Records & memory and the new record has
   `Needs review` status. The note must not approve itself.

These are recorded interactive checks, not an automated browser regression
suite. Automated API/lifecycle and frontend-state tests run through
`npm run test:backend` and `npm run test:frontend`. Stop both test servers with
Ctrl-C when finished; the API's temporary directory is removed on normal exit.

## Dataset sample review checks

With the production build and `npm run datasets:run` running, open Synthea at
http://127.0.0.1:3018 and Fitbit at http://127.0.0.1:3019. These checks only inspect
existing sample records; they do not approve, delete, or import anything.

1. Open Records & memory in each app. Confirm the named sample workspace,
   separate-participant label, connected backend, and unconfigured Cognee.
   The default preparation contains 22 Synthea and 7 Fitbit records. Existing
   review decisions should remain unchanged.
2. Open a Synthea medication record. Confirm the historical-entry explanation,
   source calendar date, **Normalized source** button, and **Open summary** link.
   The source view must include the original CSV fields, member/row references,
   archive hash, and the normalization notice.
3. Open Fitbit's May 12, 2016 record. Confirm zero steps are preserved and missing
   sleep is explicitly distinguished from zero sleep. Its normalized source
   must retain the original date, participant, CSV row, and field values.
4. Inspect the rendered source view for clipped controls or overlapping text.
   Do not use the approval action as part of these read-only checks.

Verified through Chrome on September 28, 2026 after the source-label update.
The dataset API tests separately cover approval gating and exact-citation recall
using disposable fabricated records: `npm run test:backend -- -k test_datasets`.
