# BodyBrain dataset samples

The first runnable integration uses **Synthea clinical CSVs** and the
**Crowd-sourced Fitbit daily activity/sleep CSVs**. They run in separate local
workspaces because their subjects are unrelated. They do not form a linked
patient history or demonstrate a connection between disease and exercise.

| Sample | Local app | Default selection |
| --- | --- | --- |
| Synthea | http://127.0.0.1:3018 | First source patient; latest four rows per supported clinical category, 22 records in the pinned archive |
| Fitbit | http://127.0.0.1:3019 | First source participant; latest seven activity days, May 6–12, 2016; matching sleep where present |

## Run

From the project root, using the existing Python environment and Node install:

```sh
npm run build
npm run datasets:prepare
npm run datasets:run
```

Preparation downloads about 31 MB from the official publishers, verifies pinned
SHA-256 hashes, and creates review drafts. Downloads and sample databases live
under ignored `.runtime/datasets/`. Subsequent preparations reuse verified files;
`npm run datasets:prepare -- --offline` requires them to already exist. Stop the
sample servers with Ctrl-C before preparing again. Preparation refuses to run
while these servers hold their workspace lock.

The ordinary app continues to use `.bodybrain` on port 3016. Each sample has its
own SQLite/source directory and browser origin. The sample launcher disables
dotenv, Cognee, and ClawMax for these processes, including inherited provider
configuration. No sample records are automatically uploaded to providers.

Open **Records & memory**, choose a record, inspect the normalized passages and
**Normalized source**, then approve only the passages you want in memory. Drafts do
not appear in answers or the timeline. After approval, try:

- Synthea: “What medications are recorded?” or “What care plans are recorded?”
- Fitbit: “What steps are recorded?” or “What sleep measurements are recorded?”

Answers use reviewed source excerpts. This integration does not add arithmetic
aggregation, diagnoses, treatment recommendations, or proof of recovery.
Keep these workspaces for their named source participant; normal manual record
creation is still available, so do not add unrelated personal records to a sample.

## Input coverage and provenance

Synthea imports `conditions.csv`, `medications.csv`, `encounters.csv`,
`procedures.csv`, `careplans.csv`, and `observations.csv`, selected by `PATIENT`.
`patients.csv` identifies the subject; synthetic names, addresses, and government
identifiers are not converted into records. Recent rows are chosen separately
per category using full timestamps and offsets when supplied, with CSV row order
breaking ties. Displayed event dates retain the source calendar day. This is a
bounded sample, not the complete patient history. Dates,
descriptions, values, and supplied units remain attributable to their CSV rows.
A medication entry is historical and is not labeled a current prescription.

Fitbit imports `dailyActivity_merged.csv` and optionally `sleepDay_merged.csv`,
joined by exact source participant ID and calendar date. It preserves steps,
activity minutes, and minutes asleep/in bed. Identical duplicate sleep rows are
not summed; conflicting daily duplicates and invalid values are rejected. Missing
sleep is labeled missing. Distance and calorie fields retain their source names
and values because the CSV headers do not specify their units. Calendar dates
are retained without inventing a timezone. Heart rate, HRV, minute-level streams,
GPS, and live device syncing are not included in this first adapter.

Every draft includes the publisher, source subject, archive SHA-256, member
filename, data-row number, original CSV fields, and an explicit transformation
notice. The record's **Open summary** link returns the **normalized TXT summary**;
the untouched publisher ZIP is retained under `.runtime/datasets/raw/`. The
record is not presented as a verbatim doctor report. Record backups contain the
summary and its row provenance; archive files are backed up separately.

Repeat imports of the same batch reuse records and retain approval state. A
workspace marker rejects a different archive, subject, or dataset. The adapters
are a CLI sample workflow; the ordinary upload form still accepts PDF/TXT/MD,
not arbitrary CSV, FHIR, Apple Health XML, Garmin FIT, or DICOM.

## Sources and attribution

- **Synthea:** The MITRE Corporation / Synthetic Health. The publisher provides
  synthetic data for unrestricted use. Cite Walonoski et al., *Synthea: An
  approach, method, and software mechanism for generating synthetic patients
  and the synthetic electronic health care record*, JAMIA 25(3), 2018,
  [DOI 10.1093/jamia/ocx079](https://doi.org/10.1093/jamia/ocx079).
  [Official downloads and usage statement](https://synthetichealth.github.io/downloads.html),
  [official CSV dictionary](https://github.com/synthetichealth/synthea/wiki/CSV-File-Data-Dictionary).
- **Fitbit:** Furberg, Robert; Brinton, Julia; Keating, Michael; Ortiz, Alexa
  (2016), *Crowd-sourced Fitbit datasets 03.12.2016–05.12.2016*, Zenodo,
  [DOI 10.5281/zenodo.53894](https://zenodo.org/records/53894).
  License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), verified
  from the publisher's record metadata. BodyBrain selects one participant and
  converts selected CSV rows into labeled summaries; these are adaptations.

Download URLs, exact byte sizes, hashes, and versions are in
[`sources.json`](sources.json). The Synthea URL is pinned to an official repository
commit; the Fitbit archive's published MD5 was also checked on initial download.

## Later dataset candidates

The supplied lists also identify RSNA LumbarDISC, SPIDER, nerve-root MRI,
VinDr-SpineXR, MIMIC, RadGraph, FitRec, PAMAP2, MHEALTH, ExtraSensory, CovIdentify,
PADS, and BigIdeasLab_STEP. They have not been downloaded or integrated by this
step. The same applies to Apple, Garmin, Google, WHOOP, Oura, and Strava connectors.

RSNA's [LumbarDISC publication](https://pubs.rsna.org/doi/10.1148/ryai.250480)
describes noncommercial access; imaging work also needs a viewer and explicit
coordinate/annotation handling. Generic atlas highlighting cannot establish
patient-specific registration. [MIMIC-IV](https://physionet.org/content/mimiciv/3.1/)
requires credentialed access; its permissions are not implied by this demo.
Any future composite demonstration must label fictional links and keep original
dataset identities and dates visible.
