# BodyBrain — recording-ready demo pitch

Target: approximately 8–9 minutes including screen actions. Quoted paragraphs
are narration. Screen cues and rehearsal instructions are not spoken.

This script follows the seven-point checklist supplied by the user. That
checklist is a preparation aid, not evidence of the organizers' grading rubric.

## Before recording

- Use the ordinary app on port 3016 for configured Cognee memory. The dataset
  apps on 3018/3019 deliberately disable external providers.
- Keep the recording on clearly fictional records. Do not reset or delete your
  existing workspace for the demo. Identify the new record by its unique title
  and check whether that exact record is cited before and after approval.
- Have the app, Cognee's relevant data/pipeline/search view, and the two ClawMax
  agents ready. Hide keys, private documents, notifications, and unrelated tabs.
- A completed Cognee indexing/search operation must actually be visible before
  saying it succeeded. Keep the retrieval-mode label visible. If it says local
  evidence, say local evidence; do not call that a Cognee result.
- The hosted ClawMax relay is currently blocked. Use the explicit status wording
  below. Earlier execution receipts may be shown as earlier results, but they
  do not demonstrate a fresh combined Cognee-to-ClawMax run.
- Read the actual answer on screen; do not dub in a result that did not appear.
- Keep the test suite results separate from the live task result. A passed test
  suite is not a claim of clinical validation.

### Demo input

Title: **DEMO — Source-check femur report — September 28**

```text
SYNTHETIC DEMO RECORD — not a real patient.
Report date: 2026-09-28
No fracture of the left femur.
This record is fictional and is used only to demonstrate source-linked recall.
```

Primary question: **What does this report document about the left femur?**

Negative-control question: **What medication dosage does this report prescribe?**

Expected evidence is the complete sentence “No fracture of the left femur.”
The software must not turn that into “fracture of the left femur” or invent a
medication dose. Before approval, this specific record must not be cited. Other
already-approved records may still legitimately appear in a nonempty workspace.

## 0:00–0:55 — 01: The real problem

**Screen:** Start on the body view, then open Records & memory. Add a small title
overlay: “BodyBrain — personal health memory with sources.”

> Before an appointment, a simple question can turn into a search through PDFs,
> visit notes, and personal reminders: what did my report actually say, and where
> is the original evidence?
>
> Health information is especially easy to misread when context gets separated
> from the source. “No fracture” and “fracture” refer to the same anatomy, but
> mean very different things.
>
> I built BodyBrain to make those records easier to find, review, and recall.
> The body is an interface into that memory: select an anatomical structure,
> explore the relevant records, and inspect the quotations behind an answer.
>
> In this demo, I’ll take one fictional report from import to reviewed memory,
> then answer a specific question and verify the source.

## 0:55–1:45 — 02: A working end-to-end task, part one

**Screen:** Paste the demo input, keep any hosted-agent opt-in unchecked for the
currently available local extraction path, and show the resulting review draft.

> My task is to recover exactly what this report documents about the left femur.
> The input is deliberately small so we can inspect every step. It says:
> “No fracture of the left femur.” This is a synthetic record, not a real patient.
>
> I import it into BodyBrain. The application extracts the text, preserves the
> source, and prepares findings for review. Here is the proposed passage and its
> anatomical association.
>
> This run is using local extraction. BodyBrain also implements a ClawMax
> ingestion agent, which can propose a review draft when hosted processing is
> explicitly selected and available. I’ll show the current agent status later.

## 1:45–2:40 — 03: The key human checkpoint

**Screen:** Show the pending status. Ask the primary question and check that this
new record is not cited. Return to review, inspect the original passage and the
left-femur mapping, then approve only the intended finding.

> This is the human checkpoint. An imported document is not automatically
> trusted memory, and an agent cannot approve its own finding.
>
> Before approval, this new report is excluded from the answer's evidence. I can
> still inspect its draft, but the question-answering path cannot treat it as an
> approved source.
>
> I compare the passage with the original and check the anatomy mapping. The
> word “No” must remain part of the quotation. If the mapping is wrong, I can
> change it; if I don't want a passage remembered, I can leave it unapproved.
>
> Only now do I approve this finding. That decision controls what becomes
> approved memory. It does not certify the medical accuracy of the source.

## 2:40–3:55 — 02: A working end-to-end task, part two

**Screen:** Show the record becoming indexed. Show real Cognee Add/Cognify/Search
evidence, then ask the primary question and open the returned source citation.
Speak the next three paragraphs only when those operations succeed visibly.

> With Cognee configured, BodyBrain sends the approved content for indexing.
> The memory flow is Add, then Cognify, then Search. I’m checking completed
> operations and a returned source identity, rather than relying on a connected
> badge.
>
> Now I ask the same question: “What does this report document about the left
> femur?” The answer presents the complete supporting quotation, together with
> the record and page reference. I can open the source and check it myself.
>
> That completes the task we started with: a new report has become reviewed,
> retrievable evidence. The useful result is the documented statement and the
> path back to it. The application is not making a new clinical determination.

**If Cognee does not complete:** replace those paragraphs with:

> This operation has not completed through Cognee, so I’m not counting it as a
> successful memory run. The application can still show explicitly labeled
> local evidence from approved records. Earlier independent Cognee indexing and
> retrieval passed; this recording shows the current result and its limitation.

## 3:55–4:50 — 06: What context the agent used

**Screen:** Show the two ClawMax agents and a small diagram:
`question + anatomy scope + approved source passages → evidence agent → validation`.
Show an earlier genuine completed execution receipt only if available; label it
“Earlier verified run.”

> BodyBrain separates two agent roles. The ingestion agent receives the source
> chosen for processing and relevant anatomy candidates. Its output is a draft
> that still needs human review.
>
> The evidence agent receives the current question, any selected anatomy scope,
> and a bounded set of approved passages with record identifiers, dates, and page
> references. That gives it a defined evidence set, rather than unrestricted
> access to the whole record collection.
>
> Returned citations must match the permitted, approved source quotations.
> Source text is treated as evidence, not as instructions to the agent.
>
> Earlier hosted ingestion and evidence runs completed. The current hosted relay
> is blocked by Cognee file-deletion and listing errors. The answer shown in the
> live application is not a fresh ClawMax-generated answer, and I’m not claiming
> that separate successful component tests prove a combined live agent run.

## 4:50–5:55 — 04: A repeatable success test

**Screen:** Keep a four-row pass checklist visible. Refresh, repeat the primary
question, inspect its citation, then ask the negative-control question.

> I defined success before looking at the answer.
>
> First, the new report must stay out of recall until I approve it. Second, after
> approval, the supporting quote must preserve the complete sentence, including
> “No,” and point to the correct source. Third, after refreshing the application,
> the approved record and its evidence must still be available.
>
> Fourth, I test a question the report cannot answer: “What medication dosage
> does this report prescribe?” There is no dosage in this source. A successful
> result must not invent one; a statement of insufficient evidence is useful
> behavior here.
>
> These are checks another person can repeat with the same synthetic input.
> Separately, the latest backend regression run passed 370 tests and 95 subtests.
> Those tests support the software behavior; they are not medical validation.

## 5:55–6:50 — 05: What changed after iteration

**Screen:** Show a compact before/after card and the relevant test names or audit
sections 34–35. Do not suggest that these were user-study results.

> Iteration changed both the data handling and the operational safeguards.
>
> In the clinical sample importer, events on the same day were originally
> ordered without using the full timestamp. That could select an earlier event.
> I changed selection to compare full timestamps and UTC offsets, and added
> regression cases for shuffled events and dates crossing midnight. The source's
> original displayed date is still preserved.
>
> Longer integration testing also exposed a different failure: when remote
> cleanup failed, the worker kept publishing heartbeats until the result listing
> filled up. The local fix makes room before publishing a replacement and tracks
> uncertain uploads for recovery. Its regression tests pass; deployment is
> paused, so I’m describing it as a tested local fix rather than a hosted repair.

## 6:50–7:50 — 07: Data and privacy choices

**Screen:** Show the synthetic label, review control, hosted-agent opt-in, and
source attribution. Keep credentials and actual environment files off screen.

> Every record in this demonstration is fictional. Original files and review
> state are stored locally, while configured cloud features have explicit data
> flows: Cognee receives approved content for memory, and opting into hosted
> ingestion sends the selected source for processing before approval. Human
> review gates memory use; it is not a promise that opted-in processing stays
> on the device.
>
> Provider credentials are configured separately and are excluded from the
> submission package. Hosted transcripts have separate retention, so deleting a
> local record is not a claim that every remote copy has disappeared. Failed
> cleanup remains visible for retry.
>
> The optional clinical and wearable samples are separate participants in
> separate workspaces. I do not present them as one person or infer that one
> dataset explains the other. The anatomy is an attributed reference model,
> not a patient-specific scan.

## 7:50–8:20 — Close with the demonstrated result

**Screen:** Return to the actual answer beside its source and the selected
anatomical structure. If the live memory stage failed, use the alternate close.

> BodyBrain connects a question to reviewed evidence and makes that evidence
> inspectable. We imported a report, made the human approval decision, retrieved
> its documented finding, and tested what happens when information is missing.
>
> The next operational step is restoring the hosted relay and verifying the
> combined agent workflow again. The product principle stays the same: users
> decide what becomes memory, and they can see the sources behind what comes
> back. That is BodyBrain.

**Alternate close if the live memory stage failed:**

> Today I demonstrated the local review and source-verification workflow, showed
> the component checks already completed, and identified the remaining live
> integration gap. The next step is a successful combined memory-and-agent run.
> BodyBrain's product principle is that users decide what becomes memory and can
> inspect the sources behind what comes back.

## On-screen repeatability card

| Check | Pass condition |
| --- | --- |
| Human gate | The new, pending report is not cited |
| Exact evidence | Approved answer cites “No fracture of the left femur.” from the correct record/page |
| Persistence | Refreshing retains the approved record and source citation availability |
| Missing information | A dosage question produces no invented medication or dose |

Record the observed outcome for each row. Do not prelabel a failed or unperformed
check as passed. Distinguish software behavior, provider connectivity, and actual
completed hosted execution throughout the recording.
