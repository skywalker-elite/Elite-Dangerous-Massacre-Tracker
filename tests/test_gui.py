"""Finite real-Tk/model smoke coverage adapted for the tracker tables."""
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from controller import MissionController
from model import MissionModel
from view import MissionView
from tests.journal_helpers import (
    NOW, append_events, event, freeze_clock, sample_events, write_journal,
)

pytestmark = [pytest.mark.gui, pytest.mark.integration]


def build_app(tk_root, tmp_path, monkeypatch, events=None):
    freeze_clock(monkeypatch)
    journal = write_journal(tmp_path / 'journals', sample_events() if events is None else events)
    model = MissionModel([str(journal.parent)])
    view = MissionView(tk_root)
    ctl = MissionController.__new__(MissionController)
    ctl.root = tk_root
    ctl.model = model
    ctl.view = view
    ctl.active_fid = 'F1'
    ctl._ui_callbacks = Queue()
    def unexpected_popup(*args, **kwargs):
        pytest.fail(f'Unexpected GUI warning: {args!r}')
    monkeypatch.setattr(view, 'show_message_box_askretrycancel', unexpected_popup)
    monkeypatch.setattr(view, 'show_message_box_warning', unexpected_popup)
    return ctl, journal


def render_tables(ctl):
    ctl.update_tables_fast(NOW)
    ctl.update_tables_slow(NOW)
    ctl.view.update_table_active_journals(ctl.model.get_data_active_journals())
    ctl.update_time(NOW)
    ctl.root.update_idletasks()
    ctl.root.update()


@pytest.mark.parametrize('missing_event', [None, 'Commander', 'LoadGame', 'Missions'])
def test_real_model_renders_all_tables_and_processes_incremental_update(tk_root, tmp_path, monkeypatch, missing_event):
    events = [record for record in sample_events() if record['event'] != missing_event]
    ctl, journal = build_app(tk_root, tmp_path, monkeypatch, events)
    render_tables(ctl)
    for name in ('missions', 'faction_distribution', 'mission_stats', 'mission_stats_rewards'):
        rows = getattr(ctl.view, 'sheet_' + name).get_sheet_data()
        assert rows, name
    assert len(ctl.view.sheet_active_journals.get_sheet_data()) == 1
    append_events(journal, event('Undocked', 1, StationName='Galileo', MarketID=1),
                  event('FSDJump', 2, StarSystem='Achenar'))
    ctl._perform_journal_update()
    render_tables(ctl)
    if missing_event != 'Commander':
        assert 'Achenar' in ctl.view.label_cmdr_location.cget('text')
    ctl._perform_journal_update()
    render_tables(ctl)
    assert len(ctl.view.sheet_missions.get_sheet_data()) == 1
    assert len(ctl.model.journal_reader.get_items()[2]) == 1


def test_malformed_json_record_does_not_close_gui_or_lose_next_update(tk_root, tmp_path, monkeypatch):
    ctl, journal = build_app(tk_root, tmp_path, monkeypatch)
    with journal.open('ab') as stream:
        stream.write(b'{"event": "MissionRedirected"\n')
    append_events(journal, event('MissionRedirected', 1, MissionID=100))
    ctl.update_journals()
    render_tables(ctl)
    assert tk_root.winfo_exists()
    assert ctl.model.get_missions('F1')[100]['Redirected'] is True
    assert len(ctl.view.sheet_missions.get_sheet_data()) == 1


def test_active_journal_tab_can_be_shown_and_hidden(tk_root):
    view = MissionView(tk_root)
    for shown in (True, False, True):
        view.checkbox_show_active_journals_var.set(shown)
        view.toggle_active_journals_tab()
        assert view.tab_controler.tab(view.tab_active_journals, 'state') == ('normal' if shown else 'hidden')


def test_initial_mixed_accounts_do_not_invent_identity_in_gui(tk_root, tmp_path, monkeypatch):
    events = sample_events() + sample_events(fid='F2', mission_id=200)
    ctl, _ = build_app(tk_root, tmp_path, monkeypatch, events)
    for fid in ('F1', 'F2'):
        ctl.active_fid = fid
        render_tables(ctl)
        assert ctl.view.sheet_missions.get_sheet_data() == [['No active missions']]
    assert {record['MissionID'] for record in ctl.model.journal_reader._missions_accepted} == {100, 200}
    assert all(record['FID'] is None for record in ctl.model.journal_reader._missions_accepted)


def test_append_from_second_instance_does_not_duplicate_records_in_gui(tk_root, tmp_path, monkeypatch):
    ctl, journal = build_app(tk_root, tmp_path, monkeypatch)
    append_events(journal, *sample_events(fid='F2', mission_id=200))
    for _ in range(3):
        ctl._perform_journal_update()
        render_tables(ctl)
    for fid, mission_id in (('F1', 100), ('F2', 200)):
        ctl.active_fid = fid
        render_tables(ctl)
        assert set(ctl.model.get_active_missions(fid)) == {mission_id}
        assert len(ctl.view.sheet_missions.get_sheet_data()) == 1
    assert len(ctl.model.journal_reader.get_items()[2]) == 2


def test_damaged_utf8_is_ignored_without_closing_gui(tk_root, tmp_path, monkeypatch):
    ctl, journal = build_app(tk_root, tmp_path, monkeypatch)
    with journal.open('ab') as stream:
        stream.write(b'{"event":"Music","MusicTrack":"caf\xc3"}\n')
    append_events(journal, event('MissionRedirected', 1, MissionID=100))
    error_dialog = Mock(return_value=False)
    monkeypatch.setattr(ctl.view, 'show_message_box_askretrycancel', error_dialog)
    closed = Mock()
    ctl.view.root = SimpleNamespace(after=tk_root.after, after_idle=tk_root.after_idle, destroy=closed)
    ctl.update_journals()
    error_dialog.assert_not_called()
    closed.assert_not_called()
    render_tables(ctl)
    assert ctl.model.get_missions('F1')[100]['Redirected'] is True


def test_missing_journal_keeps_gui_open_and_recovers_when_file_returns(tk_root, tmp_path, monkeypatch):
    ctl, journal = build_app(tk_root, tmp_path, monkeypatch)
    render_tables(ctl)
    original = journal.read_bytes()
    journal.unlink()
    error_dialog = Mock(return_value=False)
    monkeypatch.setattr(ctl.view, 'show_message_box_askretrycancel', error_dialog)
    closed = Mock()
    ctl.view.root = SimpleNamespace(after=tk_root.after, after_idle=tk_root.after_idle, destroy=closed)
    ctl.update_journals()
    closed.assert_not_called()
    journal.write_bytes(original)
    append_events(journal, event('MissionRedirected', 1, MissionID=100))
    ctl.update_journals()
    render_tables(ctl)
    assert ctl.model.get_missions('F1')[100]['Redirected'] is True
