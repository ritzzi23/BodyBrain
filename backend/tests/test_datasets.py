import copy
import csv
from dataclasses import replace
import io
import json
from pathlib import Path
import zipfile

from fastapi.testclient import TestClient
import pytest

from bodybrain.config import Settings
from bodybrain.datasets import DatasetError, fitbit_drafts, import_batch, synthea_drafts
from bodybrain.main import create_app


def archive(path: Path, tables: dict):
    with zipfile.ZipFile(path, 'w') as output:
        for name, rows in tables.items():
            stream = io.StringIO()
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
            output.writestr(name, stream.getvalue())
    return path


def fitbit_tables():
    return {
        'dailyActivity_merged.csv': [
            {'Id': 'alice', 'ActivityDate': '4/12/2016', 'TotalSteps': '1234', 'VeryActiveMinutes': '0'},
            {'Id': 'alice', 'ActivityDate': '4/13/2016', 'TotalSteps': '2345', 'VeryActiveMinutes': '20'},
            {'Id': 'bob', 'ActivityDate': '4/13/2016', 'TotalSteps': '9999', 'VeryActiveMinutes': '60'},
        ],
        'sleepDay_merged.csv': [
            {'Id': 'alice', 'SleepDay': '4/12/2016 12:00:00 AM', 'TotalMinutesAsleep': '327', 'TotalTimeInBed': '346'},
            {'Id': 'alice', 'SleepDay': '4/12/2016 12:00:00 AM', 'TotalMinutesAsleep': '327', 'TotalTimeInBed': '346'},
            {'Id': 'bob', 'SleepDay': '4/13/2016 12:00:00 AM', 'TotalMinutesAsleep': '450', 'TotalTimeInBed': '460'},
        ],
    }


def test_fitbit_preserves_subject_dates_values_missingness_and_provenance(tmp_path):
    batch = fitbit_drafts(archive(tmp_path / 'sample.zip', fitbit_tables()), 'alice')
    first, second = batch['records']
    assert [r['event_date'] for r in batch['records']] == ['2016-04-12', '2016-04-13']
    assert 'Steps: 1234 steps.' in first['text']
    assert 'Very active: 0 minutes.' in first['text']
    assert 'Sleep: 327 minutes asleep; 346 minutes in bed.' in first['text']
    assert 'Sleep measurements are missing' in second['text']
    assert len(first['dataset_source']['source_rows']) == 2
    assert first['dataset_source']['source_rows'][0]['row'] == 1
    assert first['dataset_source']['archive_sha256'] == batch['archive_sha256']
    assert all('9999' not in r['text'] and '450 minutes' not in r['text'] for r in batch['records'])
    assert fitbit_drafts(tmp_path / 'sample.zip', 'alice', days=1)['records'][0]['event_date'] == '2016-04-13'


@pytest.mark.parametrize('change', ['negative', 'nan', 'fractional_steps', 'date', 'conflict', 'sleep_exceeds_bed', 'missing_column'])
def test_fitbit_rejects_ambiguous_or_invalid_input(tmp_path, change):
    tables = fitbit_tables()
    first = tables['dailyActivity_merged.csv'][0]
    if change == 'negative': first['TotalSteps'] = '-1'
    if change == 'nan': first['TotalSteps'] = 'NaN'
    if change == 'fractional_steps': first['TotalSteps'] = '2.5'
    if change == 'date': first['ActivityDate'] = '2/30/2016'
    if change == 'conflict': tables['dailyActivity_merged.csv'].append({**first, 'TotalSteps': '5678'})
    if change == 'sleep_exceeds_bed':
        tables['sleepDay_merged.csv'] = [{**tables['sleepDay_merged.csv'][0], 'TotalMinutesAsleep': '500'}]
    if change == 'missing_column':
        for row in tables['dailyActivity_merged.csv']: del row['TotalSteps']
    with pytest.raises(DatasetError):
        fitbit_drafts(archive(tmp_path / 'bad.zip', tables), 'alice')


def test_synthea_preserves_historical_meaning_and_limits_per_category(tmp_path):
    tables = {
        'patients.csv': [{'Id': 'p1'}, {'Id': 'p2'}],
        'conditions.csv': [
            {'PATIENT': 'p1', 'START': '2020-01-02', 'STOP': '', 'DESCRIPTION': 'Pain in left knee'},
            {'PATIENT': 'p1', 'START': '2021-01-03', 'STOP': '', 'DESCRIPTION': 'Pain in left ankle'},
            {'PATIENT': 'p2', 'START': '2022-01-01', 'STOP': '', 'DESCRIPTION': 'Other subject condition'},
        ],
        'medications.csv': [{'PATIENT': 'p1', 'START': '2021-01-03T12:00:00Z', 'STOP': '2021-01-05', 'DESCRIPTION': 'Example medication', 'REASONDESCRIPTION': 'Pain'}],
        'observations.csv': [{'PATIENT': 'p1', 'DATE': '2021-01-03T23:00:00-04:00', 'DESCRIPTION': 'Example laboratory observation', 'VALUE': '6.30', 'UNITS': '%', 'TYPE': 'numeric'}],
    }
    path = archive(tmp_path / 'synthea.zip', tables)
    batch = synthea_drafts(path, 'p1', per_kind=1)
    assert len(batch['records']) == 3
    assert all(r['event_date'] == '2021-01-03' for r in batch['records'])
    text = '\n'.join(r['text'] for r in batch['records'])
    assert 'left ankle' in text and 'left knee' not in text and 'Other subject' not in text
    assert '6.30 (%)' in text and 'does not establish a current prescription' in text
    with pytest.raises(DatasetError, match='patient ID'): synthea_drafts(path, 'absent')


@pytest.mark.parametrize(('newer', 'older', 'event_date'), [
    ('2021-01-03T20:00:00Z', '2021-01-03T09:00:00Z', '2021-01-03'),
    ('2021-01-03T23:00:00Z', '2021-01-04T00:30:00+02:00', '2021-01-03'),
])
def test_synthea_selects_latest_timestamp_independent_of_csv_order(tmp_path, newer, older, event_date):
    tables = {
        'patients.csv': [{'Id': 'p1'}],
        'observations.csv': [
            {'PATIENT': 'p1', 'DATE': newer, 'DESCRIPTION': 'Later observation', 'VALUE': '6.30', 'UNITS': '%', 'TYPE': 'numeric'},
            {'PATIENT': 'p1', 'DATE': older, 'DESCRIPTION': 'Earlier observation', 'VALUE': '5.70', 'UNITS': '%', 'TYPE': 'numeric'},
        ],
    }
    batch = synthea_drafts(archive(tmp_path / 'synthea.zip', tables), 'p1', per_kind=1)
    record, = batch['records']
    assert record['event_date'] == event_date
    assert 'Later observation' in record['text']
    assert 'Earlier observation' not in record['text']
    assert record['dataset_source']['source_rows'][0]['values']['DATE'] == newer
    assert record['dataset_source']['source_rows'][0]['row'] == 1


def test_duplicate_table_names_are_rejected_without_extraction(tmp_path):
    tables = fitbit_tables()
    tables['nested/dailyActivity_merged.csv'] = tables['dailyActivity_merged.csv']
    with pytest.raises(DatasetError, match='Expected one'):
        fitbit_drafts(archive(tmp_path / 'duplicate.zip', tables))


def test_dataset_import_review_recall_idempotence_and_workspace_isolation(tmp_path):
    batch = fitbit_drafts(archive(tmp_path / 'sample.zip', fitbit_tables()), 'alice')
    app = create_app(replace(Settings(), data_dir=tmp_path / 'lab', cognee_mode='disabled', clawmax_transport='dashboard',
                             clawmax_url='', clawmax_token='', api_token='', agent_token='', workspace_label='Fitbit sample'))
    service = app.state.service
    result = import_batch(service, batch)
    assert result['record_ids'] == import_batch(service, batch)['record_ids']
    assert len(service.store.records()) == 2
    with TestClient(app) as client:
        assert client.get('/api/health').json()['workspace_label'] == 'Fitbit sample'
        assert not client.post('/api/chat', json={'question': 'Steps'}).json()['citations']
        record_id = result['record_ids'][0]
        record = client.get(f'/api/records/{record_id}').json()
        assert record['status'] == 'pending_review'
        assert record['dataset_source']['subject_id'] == 'alice'
        assert client.get(f'/api/records/{record_id}/source').text == batch['records'][0]['text']
        finding = next(f for f in record['findings'] if f['quote'] == 'Steps: 1234 steps.')
        assert client.post(f'/api/records/{record_id}/approve', json={'finding_ids': [finding['id']]}).status_code == 200
        answer = client.post('/api/chat', json={'question': 'Steps'}).json()
        assert any(c['quote'] == 'Steps: 1234 steps.' and c['event_date'] == '2016-04-12' for c in answer['citations'])
        import_batch(service, batch)
        assert service.store.get(record_id)['status'] == 'approved'
    other = copy.deepcopy(batch)
    other['subject_id'] = 'bob'
    with pytest.raises(DatasetError): import_batch(service, other)
    assert len(service.store.records()) == 2


def test_import_refuses_personal_records_and_enabled_providers(tmp_path):
    batch = fitbit_drafts(archive(tmp_path / 'sample.zip', fitbit_tables()))
    app = create_app(replace(Settings(), data_dir=tmp_path / 'personal', cognee_mode='disabled', clawmax_transport='dashboard'))
    app.state.service.create_record(b'An existing personal record.', 'personal.txt', 'Personal', 'note')
    with pytest.raises(DatasetError, match='existing personal'):
        import_batch(app.state.service, batch)
    assert not (tmp_path / 'personal/dataset.json').exists()
    app.state.service.settings = replace(app.state.service.settings, cognee_mode='rest')
    with pytest.raises(DatasetError, match='providers disabled'):
        import_batch(app.state.service, batch)
