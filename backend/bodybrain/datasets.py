"""Bounded, source-preserving adapters for the selected public CSV samples.

These produce review drafts, not diagnoses or reconstructed clinical reports.
Each batch belongs to one dataset and one source subject.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


class DatasetError(ValueError):
    pass


SOURCES = {
    'synthea': {
        'name': 'Synthea sample clinical history',
        'url': 'https://synthetichealth.github.io/downloads.html',
        'license': 'Synthetic data; unrestricted use according to the publisher',
        'citation': 'Walonoski et al. Synthea. JAMIA 25(3), 2018. DOI: 10.1093/jamia/ocx079',
        'population': 'Synthetic patient; not a real person',
    },
    'fitbit': {
        'name': 'Crowd-sourced Fitbit datasets, April–May 2016',
        'url': 'https://zenodo.org/records/53894',
        'license': 'CC BY 4.0',
        'citation': 'Furberg, Brinton, Keating, Ortiz (2016). DOI: 10.5281/zenodo.53894',
        'population': 'Public study participant; not the BodyBrain user and not a Synthea patient',
    },
}


def archive_digest(path: Path) -> str:
    if path.stat().st_size > 40_000_000:
        raise DatasetError('Sample archive exceeds 40 MB')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_table(archive: zipfile.ZipFile, filename: str, required: set[str], *, optional=False):
    candidates = [i for i in archive.infolist() if PurePosixPath(i.filename).name.lower() == filename.lower()]
    if not candidates and optional:
        return []
    if len(candidates) != 1:
        raise DatasetError(f'Expected one {filename} table')
    info = candidates[0]
    if info.file_size > 20_000_000 or info.flag_bits & 1:
        raise DatasetError(f'{filename} is oversized or encrypted')
    # Read named members without extracting paths to the filesystem.
    with archive.open(info) as stream:
        reader = csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8-sig'), strict=True)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames) or not required.issubset(reader.fieldnames):
            raise DatasetError(f'Unexpected columns in {filename}')
        rows = []
        for number, row in enumerate(reader, 1):
            if number > 250_000 or None in row or any(v is None or len(v) > 5000 or '\x00' in v for v in row.values()):
                raise DatasetError(f'Malformed or excessive rows in {filename}')
            rows.append({'file': info.filename, 'row': number, 'values': row})
        return rows


def iso_day(value: str) -> str:
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T.*)?', value):
        raise DatasetError('Invalid source date')
    try:
        if 'T' in value:
            datetime.fromisoformat(value.replace('Z', '+00:00'))
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError as exc:
        raise DatasetError('Invalid source date') from exc


def fitbit_day(value: str, *, sleep=False) -> str:
    try:
        return datetime.strptime(value, '%m/%d/%Y %I:%M:%S %p' if sleep else '%m/%d/%Y').date().isoformat()
    except ValueError as exc:
        raise DatasetError('Invalid Fitbit date') from exc


def source_order(value: str) -> datetime:
    """Order validated source dates without discarding available time/offsets."""
    instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    # Date-only/naive values retain calendar ordering. This comparison default
    # is never written back as an asserted source time or timezone.
    return instant if instant.tzinfo is not None else instant.replace(tzinfo=timezone.utc)


def metric(value: str, *, integer=False) -> str:
    try:
        number = Decimal(value)
        if not number.is_finite() or number < 0 or (integer and number != number.to_integral_value()):
            raise InvalidOperation
    except InvalidOperation as exc:
        raise DatasetError('Invalid nonnegative measurement') from exc
    return value  # Preserve source precision, including explicit zero values.


def draft(dataset: str, subject: str, digest: str, day: str, kind: str, lines: list[str], rows: list[dict]) -> dict:
    source = SOURCES[dataset]
    text = '\n\n'.join([
        f"DATASET SAMPLE — {source['population']}.",
        f'Event date: {day}\nDataset: {source["name"]}\nSource subject ID: {subject}',
        'BodyBrain normalized these structured CSV values. They are not a verbatim clinician report. Human review is required.',
        *lines,
        'Provenance (CSV row numbers count data rows, excluding the header):\n' + '\n'.join(f"{r['file']} — data row {r['row']}" for r in rows),
        f"Publisher: {source['url']}\nArchive SHA-256: {digest}\nAttribution: {source['citation']}\nTerms: {source['license']}",
        'Original CSV field values:\n' + json.dumps([r['values'] for r in rows], ensure_ascii=False, sort_keys=True, indent=2),
    ])
    if len(text) > 150_000:
        raise DatasetError('Normalized record exceeds the record size limit')
    description = rows[0]['values'].get('DESCRIPTION', '')
    detail = f": {description[:90]}{'…' if len(description) > 90 else ''}" if description else ''
    return {
        'title': f'SAMPLE {dataset.title()} — {kind}{detail} — {day}',
        'text': text, 'event_date': day, 'record_type': f'dataset_{dataset}_{kind.lower().replace(" ", "_")}',
        'dataset_source': {'dataset': dataset, 'subject_id': subject, 'archive_sha256': digest,
                           'source_url': source['url'], 'source_rows': rows, 'transformation': 'bodybrain.csv.v1'},
    }


SYNTHEA_TABLES = {
    'conditions.csv': ('Condition', 'START'),
    'medications.csv': ('Medication entry', 'START'),
    'encounters.csv': ('Encounter', 'START'),
    'procedures.csv': ('Procedure', 'START'),
    'careplans.csv': ('Care plan', 'START'),
    'observations.csv': ('Observation', 'DATE'),
}


def synthea_drafts(path: Path, subject: str | None = None, per_kind: int = 4) -> dict:
    if not 1 <= per_kind <= 25:
        raise DatasetError('Choose 1–25 records per clinical category')
    digest = archive_digest(path)
    with zipfile.ZipFile(path) as archive:
        patients = read_table(archive, 'patients.csv', {'Id'})
        if not patients:
            raise DatasetError('No synthetic patients found')
        subject = subject or patients[0]['values']['Id']
        if sum(r['values']['Id'] == subject for r in patients) != 1:
            raise DatasetError('Select one existing unique Synthea patient ID')
        drafts, counts = [], {}
        for filename, (kind, date_column) in SYNTHEA_TABLES.items():
            rows = read_table(archive, filename, {'PATIENT', date_column, 'DESCRIPTION'}, optional=True)
            selected = [(iso_day(r['values'][date_column]), r) for r in rows if r['values']['PATIENT'] == subject]
            counts[filename] = len(selected)
            for day, row in sorted(selected, key=lambda item: (source_order(item[1]['values'][date_column]), item[1]['row']))[-per_kind:]:
                fields = row['values']
                lines = [f"{kind} recorded: {fields['DESCRIPTION']}."]
                if kind == 'Observation':
                    if not {'VALUE', 'UNITS', 'TYPE'}.issubset(fields):
                        raise DatasetError('Observation value/unit/type columns are required')
                    units = fields['UNITS'] or 'unit not supplied'
                    lines.append(f"Recorded value: {fields['VALUE']} ({units}); source type: {fields['TYPE']}.")
                if fields.get('REASONDESCRIPTION'):
                    lines.append(f"Recorded reason: {fields['REASONDESCRIPTION']}.")
                if fields.get('STOP'):
                    iso_day(fields['STOP'])
                    lines.append(f"Source stop date/time: {fields['STOP']}.")
                if kind == 'Medication entry':
                    lines.append('This historical medication entry does not establish a current prescription or instructions to take it.')
                drafts.append(draft('synthea', subject, digest, day, kind, lines, [row]))
    if not drafts:
        raise DatasetError('No supported clinical events for this patient')
    return {'dataset': 'synthea', 'subject_id': subject, 'archive_sha256': digest, 'available_rows': counts,
            'selection': f'Most recent {per_kind} source rows per supported category; not a complete clinical history',
            'records': sorted(drafts, key=lambda r: (r['event_date'], r['title'], r['text']))}


def fitbit_drafts(path: Path, subject: str | None = None, days: int = 7) -> dict:
    if not 1 <= days <= 366:
        raise DatasetError('Choose 1–366 daily summaries')
    digest = archive_digest(path)
    with zipfile.ZipFile(path) as archive:
        activity = read_table(archive, 'dailyActivity_merged.csv', {'Id', 'ActivityDate', 'TotalSteps'})
        sleep = read_table(archive, 'sleepDay_merged.csv', {'Id', 'SleepDay', 'TotalMinutesAsleep', 'TotalTimeInBed'}, optional=True)
    if not activity:
        raise DatasetError('No daily activity rows found')
    subject = subject or activity[0]['values']['Id']
    def by_day(rows, is_sleep=False):
        result = {}
        for row in rows:
            fields = row['values']
            if fields['Id'] != subject:
                continue
            day = fitbit_day(fields['SleepDay' if is_sleep else 'ActivityDate'], sleep=is_sleep)
            if day in result:
                if result[day]['values'] != fields:
                    raise DatasetError('Conflicting duplicate daily rows; resolve before import')
                continue  # Identical duplicates must not double-count sleep.
            result[day] = row
        return result
    activity_days, sleep_days = by_day(activity), by_day(sleep, True)
    if not activity_days:
        raise DatasetError('No activity for the selected Fitbit participant')
    records = []
    for day in sorted(activity_days)[-days:]:
        row = activity_days[day]
        fields = row['values']
        lines = [f"Steps: {metric(fields['TotalSteps'], integer=True)} steps."]
        for column, label in [('VeryActiveMinutes', 'Very active'), ('FairlyActiveMinutes', 'Fairly active'), ('LightlyActiveMinutes', 'Lightly active'), ('SedentaryMinutes', 'Sedentary')]:
            if fields.get(column):
                lines.append(f'{label}: {metric(fields[column], integer=True)} minutes.')
        if fields.get('Calories'):
            lines.append(f"Calories source field: {metric(fields['Calories'])}; the CSV does not specify a unit.")
        if fields.get('TotalDistance'):
            lines.append(f"TotalDistance source field: {metric(fields['TotalDistance'])}; the CSV does not specify a unit.")
        source_rows = [row]
        if day in sleep_days:
            source_rows.append(sleep_days[day])
            values = sleep_days[day]['values']
            asleep, in_bed = metric(values['TotalMinutesAsleep'], integer=True), metric(values['TotalTimeInBed'], integer=True)
            if Decimal(asleep) > Decimal(in_bed):
                raise DatasetError('Minutes asleep exceeds time in bed')
            lines.append(f'Sleep: {asleep} minutes asleep; {in_bed} minutes in bed.')
        else:
            lines.append('Sleep measurements are missing for this date; this does not mean zero sleep.')
        lines.append('Source calendar dates are preserved; timezone and wear completeness are not supplied. No recovery or disease inference is made.')
        records.append(draft('fitbit', subject, digest, day, 'Daily activity', lines, source_rows))
    return {'dataset': 'fitbit', 'subject_id': subject, 'archive_sha256': digest,
            'available_rows': {'activity_days': len(activity_days), 'sleep_days': len(sleep_days)},
            'selection': f'Most recent {days} available activity days, with same-subject/date sleep where present', 'records': records}


def import_batch(service, batch: dict) -> dict:
    """Import a single-subject batch only into a matching, provider-disabled lab."""
    if service.settings.cognee_mode != 'disabled' or service.relay or service.clawmax_ingest.configured or service.clawmax_evidence.configured:
        raise DatasetError('Dataset labs must have external providers disabled')
    identity = {k: batch[k] for k in ('dataset', 'subject_id', 'archive_sha256')}
    # Validate every subject before writing any workspace metadata or records.
    for record in batch['records']:
        source = record['dataset_source']
        if any(source[k] != identity[k] for k in identity):
            raise DatasetError('Cross-subject or cross-dataset record rejected')
    marker = service.settings.data_dir / 'dataset.json'
    if marker.exists():
        if {k: json.loads(marker.read_text())[k] for k in identity} != identity:
            raise DatasetError('This workspace belongs to a different dataset, subject, or archive')
    elif service.store.records():
        raise DatasetError('Choose an empty dataset workspace; existing personal records cannot be mixed in')
    else:
        from .db import write_private_source
        write_private_source(marker, (json.dumps({**identity, 'selection': batch['selection']}, indent=2) + '\n').encode())
    ids = []
    for record in batch['records']:
        saved = service.create_record(record['text'].encode(), 'dataset-summary.txt', record['title'], record['record_type'], record['event_date'])
        if saved['status'] == 'pending_review':
            service.store.update(saved['id'], expected_status='pending_review', title=record['title'], dataset_source=record['dataset_source'])
        ids.append(saved['id'])
    return {**identity, 'record_ids': ids, 'records': len(ids), 'selection': batch['selection'], 'review_required': True}
