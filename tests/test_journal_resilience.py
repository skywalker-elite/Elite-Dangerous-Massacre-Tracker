"""Tracker adaptations of the source damaged-journal and shared-session regressions."""
import json
import pickle
from copy import deepcopy

import pytest

from model import MissionModel, JournalReader
from tests.journal_helpers import (NOW, append_events, assert_tables_render, event,
                                   freeze_clock, sample_events, write_journal)


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch):
    freeze_clock(monkeypatch)


def read_model(directory):
    result = MissionModel([str(directory)])
    assert_tables_render(result)
    return result


@pytest.mark.parametrize('position', [0, 4, 6], ids=['before', 'between', 'after'])
@pytest.mark.parametrize('broken', [b'{"event" "MissionAccepted"}\n', b'{"event":\n', b'not JSON\n'])
def test_missing_punctuation_is_skipped_and_later_events_survive(tmp_path, position, broken):
    events = sample_events()
    path = write_journal(tmp_path, events[:position])
    with path.open('ab') as stream:
        stream.write(broken)
    append_events(path, *events[position:])
    result = read_model(tmp_path)
    for _ in range(3):
        result.read_journals()
    assert result.get_missions('F1')[100]['Reward'] == 1_000_000
    assert len(result.journal_reader.get_items()[2]) == 1
    assert len(result.get_active_missions('F1')) == 1
    assert result.get_cmdr_current_location('F1') == ('Sol', 'Galileo')


@pytest.mark.parametrize('record', [None, [], 42, 'text', {}, {'evnt': 'MissionAccepted'},
                                  {'event': 'Commander'}, {'event': 'MissionAccepted', 'timestamp': '2026-01-02T12:00:00Z'}])
def test_structurally_damaged_record_does_not_block_next_valid_record(tmp_path, record):
    path = write_journal(tmp_path, sample_events())
    result = read_model(tmp_path)
    append_events(path, record, event('MissionRedirected', 1, MissionID=100))
    result.read_journals()
    assert result.get_missions('F1')[100]['Redirected'] is True
    assert_tables_render(result)


@pytest.mark.parametrize('position', [0, 4, 6])
def test_deleted_utf8_byte_does_not_abort_whole_file(tmp_path, position):
    events = sample_events()
    path = write_journal(tmp_path, events[:position])
    line = json.dumps(event('Music', MusicTrack='Café'), ensure_ascii=False).encode('utf-8')
    index = line.index('é'.encode('utf-8'))
    damaged = line[:index] + line[index + 1:]
    with path.open('ab') as stream:
        stream.write(damaged + b'\n')
    append_events(path, *events[position:])
    result = read_model(tmp_path)
    assert result.get_cmdr_name('F1') == 'Commander F1'
    assert result.get_missions('F1')[100]['Reward'] == 1_000_000


@pytest.mark.parametrize('timestamp', [None, 123, '2026-02-30T12:00:00Z', '2026-01-02T12:0:00Z', 'invalid'])
def test_invalid_timestamp_does_not_discard_valid_mission_state(tmp_path, timestamp):
    events = sample_events()
    damaged = deepcopy(events[4])
    damaged['timestamp'] = timestamp
    damaged['Reward'] = 123
    write_journal(tmp_path, events + [damaged])
    result = read_model(tmp_path)
    assert result.get_missions('F1')[100]['Reward'] == 1_000_000


def test_deleted_digit_that_remains_valid_is_used_as_written(tmp_path):
    records = sample_events()
    records[4]['Reward'] = 100_000
    write_journal(tmp_path, records)
    result = read_model(tmp_path)
    assert result.get_missions('F1')[100]['Reward'] == 100_000


def test_deleted_event_name_character_is_ignored_and_future_records_continue(tmp_path):
    records = sample_events()
    damaged = dict(records[4], event='MissionAccepte', Reward=100)
    write_journal(tmp_path, records + [damaged, event('MissionRedirected', 1, MissionID=100)])
    result = read_model(tmp_path)
    assert result.get_missions('F1')[100]['Redirected'] is True
    assert len(result.journal_reader.get_items()[2]) == 1


def test_partial_first_record_waits_for_completion_without_crashing(tmp_path):
    encoded = json.dumps(sample_events()[4]).encode('utf-8')
    path = write_journal(tmp_path, [])
    path.write_bytes(encoded[:20])
    reader = JournalReader([str(tmp_path)])
    reader.read_journals()
    with path.open('ab') as stream:
        stream.write(encoded[20:] + b'\n')
    reader.read_journals()
    reader.read_journals()
    assert len(reader.get_items()[2]) == 1


@pytest.mark.parametrize('name', ['Commander', 'LoadGame', 'Missions', 'FSDJump', 'Docked', 'Shutdown',
                                'MissionAccepted', 'MissionRedirected', 'MissionCompleted',
                                'MissionFailed', 'MissionAbandoned', 'Undocked'])
def test_omitted_event_category_still_renders_all_tables(tmp_path, name):
    records = sample_events() + [event('MissionRedirected', -40, MissionID=100),
                                event('MissionCompleted', -39, MissionID=200),
                                event('MissionFailed', -38, MissionID=300),
                                event('MissionAbandoned', -37, MissionID=400),
                                event('Undocked', -36, StationName='Galileo', MarketID=1),
                                event('Shutdown')]
    write_journal(tmp_path, [record for record in records if record['event'] != name])
    result = read_model(tmp_path)
    assert len(result.journal_reader.get_items()[2]) == (0 if name == 'MissionAccepted' else 1)
    if name == 'Commander':
        assert all(record['FID'] is None for record in result.journal_reader._missions_accepted)
    if name == 'LoadGame':
        assert result.get_cmdr_name('F1') is None


@pytest.mark.parametrize('omitted', range(7))
def test_missing_single_incremental_event_keeps_other_updates_usable(tmp_path, omitted):
    records = sample_events()
    path = write_journal(tmp_path, records)
    result = read_model(tmp_path)
    updates = [event('LoadGame', 1, FID='F1', Commander='Renamed'),
               dict(records[4], timestamp=event('unused', 2)['timestamp'], MissionID=101),
               event('MissionRedirected', 3, MissionID=100),
               event('Undocked', 4, StationName='Galileo', MarketID=1),
               event('FSDJump', 5, StarSystem='Achenar'),
               event('Docked', 6, StarSystem='Achenar', StationName='Dawes Hub', MarketID=2),
               event('Missions', 7, Active=[{'MissionID': 100}, {'MissionID': 101}], Failed=[], Complete=[])]
    append_events(path, *(record for index, record in enumerate(updates) if index != omitted))
    for _ in range(2):
        result.read_journals()
    assert_tables_render(result)
    assert result.get_cmdr_name('F1') == ('Commander F1' if omitted == 0 else 'Renamed')
    assert result.get_cmdr_current_location('F1') == ('Achenar', None if omitted == 5 else 'Dawes Hub')
    assert len(result.journal_reader.get_items()[2]) == (1 if omitted == 1 else 2)
    assert result.get_missions('F1')[100]['Redirected'] is (omitted != 2)


@pytest.mark.parametrize('stage', ['initial', 'incremental'])
def test_missing_missions_recovers_when_acceptance_event_arrives(tmp_path, stage):
    records = sample_events()
    path = write_journal(tmp_path, [r for r in records if r['event'] != 'MissionAccepted'])
    if stage == 'initial':
        result = MissionModel([str(tmp_path)])
    else:
        reader = JournalReader([str(tmp_path)])
        reader.read_journals()
    append_events(path, records[4])
    if stage == 'incremental':
        result = MissionModel([str(tmp_path)], journal_reader=reader)
    result.read_journals()
    assert_tables_render(result)
    assert result.get_missions('F1')[100]['Reward'] == 1_000_000


@pytest.mark.parametrize('kind', ['empty', 'missing', 'healthy_and_missing', 'healthy_and_empty'])
def test_unavailable_journal_directory_recovers_when_file_arrives(tmp_path, kind):
    absent = tmp_path / 'absent'
    healthy = tmp_path / 'healthy'
    paths = [str(absent)]
    if 'empty' in kind:
        absent.mkdir()
    if kind.startswith('healthy'):
        write_journal(healthy, sample_events())
        paths.insert(0, str(healthy))
    reader = JournalReader(paths)
    reader.read_journals()
    if kind.startswith('healthy'):
        assert len(reader.get_items()[2]) == 1
    write_journal(absent, sample_events(fid='F2', mission_id=200))
    reader.read_journals()
    result = MissionModel(paths, journal_reader=reader)
    assert set(result.get_missions('F2')) == {200}
    assert_tables_render(result)


def test_disappearing_file_does_not_block_healthy_journal(tmp_path, monkeypatch):
    import model
    healthy = write_journal(tmp_path, sample_events())
    vanished = 'Journal.2026-01-02T120001.01.log'
    monkeypatch.setattr(model, 'listdir', lambda _: [healthy.name, vanished])
    result = MissionModel([str(tmp_path)])
    assert result.get_missions('F1')[100]['Reward'] == 1_000_000
    assert_tables_render(result)


def test_account_without_a_new_session_keeps_historical_data(tmp_path):
    write_journal(tmp_path, sample_events() + [event('Shutdown')], 'Journal.2026-01-01T120000.01.log')
    write_journal(tmp_path, sample_events(fid='F2', mission_id=200))
    result = read_model(tmp_path)
    assert set(result.data_missions) == {'F1', 'F2'}
    assert set(result.get_missions('F1')) == {100}
    assert result.journal_reader.get_latest_active_journals().keys() == {'F2'}


@pytest.mark.parametrize('separate_directories', [False, True])
def test_missing_newest_journal_keeps_session_metadata_during_older_appends(tmp_path, separate_directories):
    old_directory = tmp_path / 'old'
    new_directory = tmp_path / 'new' if separate_directories else old_directory
    older = write_journal(old_directory, sample_events() + [event('Shutdown')],
                          'Journal.2026-01-01T120000.01.log')
    newer = write_journal(new_directory, [event('Commander', FID='F1')])
    directories = [str(old_directory)] + ([str(new_directory)] if separate_directories else [])
    reader = JournalReader(directories)
    reader.read_journals()
    expected_latest = reader.journal_latest['F1'].copy()
    temporarily_hidden = newer.with_suffix('.held')
    newer.rename(temporarily_hidden)
    append_events(older, event('MissionRedirected', 1, MissionID=100))
    reader.read_journals()
    assert reader.journal_latest['F1'] == expected_latest
    assert reader.get_latest_active_journals() == {'F1': str(newer)}
    temporarily_hidden.rename(newer)
    reader.read_journals()
    append_events(older, event('MissionRedirected', 2, MissionID=100))
    reader.read_journals()
    reader.read_journals()
    assert reader.journal_latest['F1'] == expected_latest
    assert [record['timestamp'] for record in reader.get_items()[3]] == [event('unused', 2)['timestamp'], event('unused', 1)['timestamp']]
    assert reader._missions_accepted[0]['FID'] == 'F1'


def test_mixed_initial_accounts_keep_ids_but_do_not_guess_identity(tmp_path):
    first = sample_events()
    second = sample_events(fid='F2', mission_id=200)
    interleaved = [item for pair in zip(first, second) for item in pair]
    write_journal(tmp_path, interleaved)
    result = read_model(tmp_path)
    assert {record['MissionID'] for record in result.journal_reader._missions_accepted} == {100, 200}
    assert all(record['FID'] is None for record in result.journal_reader._missions_accepted)
    assert result.get_cmdr_current_location('F1') == (None, None)
    for _ in range(3):
        result.read_journals()
    assert len(result.journal_reader.get_items()[2]) == 2


def test_switching_accounts_in_shared_file_does_not_duplicate_consumption(tmp_path):
    shared = write_journal(tmp_path, sample_events())
    result = read_model(tmp_path)
    append_events(shared, *sample_events(fid='F2', mission_id=200))
    for _ in range(3):
        result.read_journals()
    assert len(result.journal_reader.get_items()[2]) == 2
    assert len(result.journal_reader.get_items()[0]) == 2
    assert set(result.get_missions('F2')) == {200}
    assert_tables_render(result)


def test_one_instance_shutdown_does_not_hide_other_instance_appends(tmp_path):
    records = sample_events() + [event('Commander', FID='F1'), event('Shutdown')]
    shared = write_journal(tmp_path, records)
    result = read_model(tmp_path)
    append_events(shared, event('MissionRedirected', 1, MissionID=100))
    result.read_journals()
    assert result.get_missions('F1')[100]['Redirected'] is True


def test_same_account_multiple_instances_without_shutdown_are_consumed_once(tmp_path):
    records = sample_events() + [event('Commander', FID='F1'), event('MissionRedirected', MissionID=100)]
    shared = write_journal(tmp_path, records)
    result = read_model(tmp_path)
    result.journal_reader = pickle.loads(pickle.dumps(result.journal_reader))
    append_events(shared, event('MissionRedirected', 1, MissionID=100))
    for _ in range(3):
        result.read_journals()
    assert result.get_missions('F1')[100]['Redirected'] is True
    assert len(result.journal_reader.get_items()[3]) == 2


def test_missing_commander_in_older_running_journal_still_accepts_mission_updates(tmp_path):
    records = [record for record in sample_events() if record['event'] != 'Commander']
    path = write_journal(tmp_path, records, 'Journal.2026-01-01T100000.01.log')
    result = read_model(tmp_path)
    append_events(path, event('MissionRedirected', 1, MissionID=100))
    result.read_journals()
    assert result.journal_reader._missions_accepted[0]['FID'] is None
    assert result.get_missions(None)[100]['Redirected'] is True
