"""Tracker adaptations of model contracts, itinerary, updates, and cache equivalence."""
import pickle
from datetime import timedelta

import pytest

from model import MissionModel
from tests.journal_helpers import (NOW, append_events, assert_tables_render, event,
                                   freeze_clock, make_model, sample_events, write_journal)


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch):
    freeze_clock(monkeypatch)


@pytest.fixture
def missions(tmp_path):
    return make_model(tmp_path)


def refresh(model, path, *records, now=NOW):
    append_events(path, *records)
    model.read_journals()
    model.update_data_missions(now)


def test_complete_journal_has_expected_missions_rewards_and_tables(missions):
    assert missions.get_cmdr_name('F1') == 'Commander F1'
    assert missions.get_cmdr_fid('Commander F1') == 'F1'
    assert missions.get_cmdr_fid('missing') is None
    assert missions.get_all_fids() == ['F1']
    assert set(missions.get_active_missions('F1')) == {100}
    mission = missions.get_missions('F1')[100]
    assert mission['Reward'] == 1_000_000
    assert mission['KillCount'] == 10
    assert mission['TargetFaction'] == 'Pirates'
    assert (mission['System'], mission['Station']) == ('Sol', 'Galileo')
    rows, redirected, turn_in = missions.get_data_active_missions('F1', NOW)
    assert rows[0][:8] == ['Pirates', 'Achenar', 'Sol', 'Galileo', 'Federation', 'Yes', 10, '1,000,000']
    assert redirected == turn_in == []
    assert missions.get_data_distribution('F1') == ([['Federation', 10, 0, '1,000,000']], [0])
    stats, rewards = missions.get_data_mission_stats('F1')
    assert dict(stats)['TotalMissions'] == 1
    assert dict(stats)['KillRemaining'] == 10
    assert dict(rewards)['TotalReward'] == '1,000,000'
    assert_tables_render(missions)


def test_incremental_mission_redirect_updates_highlights(tmp_path):
    missions = make_model(tmp_path)
    path = next(tmp_path.glob('Journal.*.log'))
    refresh(missions, path, event('MissionRedirected', 1, MissionID=100))
    rows, redirected, turn_in = missions.get_data_active_missions('F1', NOW)
    assert len(rows) == 1
    assert redirected == turn_in == [0]
    stats, rewards = missions.get_data_mission_stats('F1')
    assert dict(stats)['ActiveMissions'] == 0
    assert dict(stats)['KillRemaining'] == 0
    assert dict(rewards)['CurrentReward'] == '1,000,000'
    missions.read_journals()
    assert missions.get_missions('F1')[100]['Redirected'] is True


@pytest.mark.parametrize('terminal_event', ['MissionCompleted', 'MissionFailed', 'MissionAbandoned'])
def test_terminal_update_removes_mission_and_preserves_journal_history(tmp_path, terminal_event):
    missions = make_model(tmp_path)
    path = next(tmp_path.glob('Journal.*.log'))
    refresh(missions, path, event(terminal_event, 1, MissionID=100))
    assert missions.get_active_missions('F1') == {}
    assert missions.get_data_active_missions('F1', NOW) == ([['No active missions']], [], [])
    assert len(missions.journal_reader.get_items()[2]) == 1
    missions.read_journals()
    assert missions.get_active_missions('F1') == {}
    assert_tables_render(missions)


def test_itinerary_docking_undocking_and_jump_times(tmp_path):
    missions = make_model(tmp_path)
    path = next(tmp_path.glob('Journal.*.log'))
    assert missions.get_cmdr_location('F1', NOW - timedelta(seconds=57)) == ('Sol', 'Galileo')
    refresh(missions, path, event('Undocked', 1, StationName='Galileo', MarketID=1),
            event('FSDJump', 2, StarSystem='Achenar'),
            event('Docked', 3, StarSystem='Achenar', StationName='Dawes Hub', MarketID=12))
    assert missions.get_cmdr_location('F1', NOW + timedelta(seconds=1)) == ('Sol', None)
    assert missions.get_cmdr_location('F1', NOW + timedelta(seconds=2)) == ('Achenar', None)
    assert missions.get_cmdr_current_location('F1') == ('Achenar', 'Dawes Hub')
    assert missions.get_cmdr_current_location('missing') == (None, None)


def test_missing_mission_events_have_empty_tables(tmp_path):
    missions = make_model(tmp_path, [r for r in sample_events() if r['event'] != 'MissionAccepted'])
    assert missions.get_active_missions('F1') == {}
    assert missions.get_data_active_missions('F1', NOW) == ([['No active missions']], [], [])
    assert missions.get_data_distribution('F1') == ([['No active missions']], [])
    assert_tables_render(missions)


def test_full_incremental_and_cache_resume_have_equivalent_supported_outputs(tmp_path):
    records = sample_events()
    updates = [event('LoadGame', 1, FID='F1', Commander='Renamed'),
               event('Undocked', 2, StationName='Galileo', MarketID=1),
               event('FSDJump', 3, StarSystem='Achenar'),
               dict(records[4], timestamp=event('unused', 4)['timestamp'], MissionID=101)]
    full = make_model(tmp_path / 'full', records + updates)
    incremental = make_model(tmp_path / 'incremental', records)
    refresh(incremental, next((tmp_path / 'incremental').glob('Journal.*.log')), *updates)
    cached_seed = make_model(tmp_path / 'cached', records)
    cached_reader = pickle.loads(pickle.dumps(cached_seed.journal_reader))
    cached = MissionModel([], journal_reader=cached_reader)
    refresh(cached, next((tmp_path / 'cached').glob('Journal.*.log')), *updates)
    for item in (full, incremental, cached):
        assert item.get_cmdr_current_location('F1') == ('Achenar', None)
        assert item.get_cmdr_name('F1') == 'Renamed'
        assert set(item.get_active_missions('F1')) == {100, 101}
        assert item.get_missions('F1')[100]['Reward'] == 1_000_000
        assert item.get_missions('F1')[101]['System'] == 'Achenar'
        assert item.get_missions('F1')[101]['Station'] is None
        assert dict(item.get_data_mission_stats('F1')[1])['TotalReward'] == '2,000,000'
        assert_tables_render(item)


def test_initial_and_incremental_redirection_agree(tmp_path):
    update = event('MissionRedirected', 1, MissionID=100)
    full = make_model(tmp_path / 'full', sample_events() + [update])
    incremental = make_model(tmp_path / 'incremental')
    refresh(incremental, next((tmp_path / 'incremental').glob('Journal.*.log')), update)
    for item in (full, incremental):
        assert item.get_missions('F1')[100]['Redirected'] is True
        assert item.get_data_active_missions('F1', NOW)[1:] == ([0], [0])


def test_delayed_archive_load_preserves_newer_name_but_accepts_fresh_updates(tmp_path):
    archive = write_journal(tmp_path, sample_events() + [event('Shutdown', -40)],
                            'Journal.2026-01-01T120000.01.log')
    write_journal(tmp_path, [event('Commander', FID='F1'),
                            event('LoadGame', 20, FID='F1', Commander='Current')])
    missions = MissionModel([str(tmp_path)])
    refresh(missions, archive, event('LoadGame', 10, FID='F1', Commander='Old'))
    assert missions.get_cmdr_name('F1') == 'Current'
    refresh(missions, archive, event('LoadGame', 30, FID='F1', Commander='Fresh'))
    assert missions.get_cmdr_name('F1') == 'Fresh'
    assert_tables_render(missions)
