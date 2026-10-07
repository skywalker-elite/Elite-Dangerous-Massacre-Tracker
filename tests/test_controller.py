"""Controller behavior with deterministic scheduling and isolated I/O."""
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock
import pickle
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import controller as module
from controller import MissionController, JournalEventHandler
from config import SAVE_CACHE_INTERVAL, UPDATE_INTERVAL


class Scheduler:
    """Run only explicitly selected callbacks; assert Tk stays on its owner thread."""

    def __init__(self):
        self.owner = threading.get_ident()
        self.pending = {}
        self.next_id = 0
        self.destroyed = False

    def after(self, delay, callback, *args):
        assert threading.get_ident() == self.owner
        self.next_id += 1
        self.pending[self.next_id] = (delay, callback, args)
        return self.next_id

    def after_cancel(self, handle):
        self.pending.pop(handle, None)

    def run_delay(self, delay):
        selected = [key for key, call in self.pending.items() if call[0] == delay]
        for key in selected:
            _, callback, args = self.pending.pop(key)
            callback(*args)

    def destroy(self):
        self.destroyed = True


@pytest.fixture
def ctl():
    obj = MissionController.__new__(MissionController)
    obj.root = Scheduler()
    obj._ui_callbacks = Queue()
    obj.model = Mock()
    obj.view = Mock(root=obj.root)
    obj.redraw_slow = Mock()
    obj.view.show_message_box_askretrycancel.return_value = False
    return obj


@pytest.mark.parametrize('method', ['on_created', 'on_modified'])
@pytest.mark.parametrize('name,is_dir,expected', [
    ('Journal.2026-01-02T120000.01.log', False, 1),
    ('notes.csv', False, 0), ('journal.log', True, 0),
])
def test_watcher_filters_non_journals(ctl, method, name, is_dir, expected):
    ctl._schedule_journal_update = Mock()
    getattr(JournalEventHandler(ctl), method)(
        SimpleNamespace(src_path=name, is_directory=is_dir))
    assert ctl._schedule_journal_update.call_count == expected


def test_watcher_burst_coalesces_then_accepts_next_update(ctl, capsys):
    ctl.update_journals = Mock()
    with ThreadPoolExecutor(max_workers=1) as worker:
        for _ in range(5):
            worker.submit(ctl._schedule_journal_update).result(timeout=5)
    assert not ctl.root.pending
    ctl._drain_ui_callbacks()
    ctl.root.run_delay(0)
    assert ctl.update_journals.call_count == 1
    ctl.view.update_table_active_journals.assert_called_once()
    ctl._schedule_journal_update()
    ctl._drain_ui_callbacks()
    ctl.root.run_delay(0)
    assert ctl.update_journals.call_count == 2
    assert 'Error running UI callback' not in capsys.readouterr().out


def test_ui_queue_is_fifo_and_bad_callback_does_not_drop_following_work(ctl, capsys):
    calls = []

    def fail():
        raise ValueError('callback test failure')

    ctl._queue_ui_callback(calls.append, 'first')
    ctl._queue_ui_callback(fail)
    ctl._queue_ui_callback(calls.append, 'last')
    ctl._drain_ui_callbacks()
    assert calls == ['first', 'last']
    assert 'callback test failure' in capsys.readouterr().out
    assert ctl._ui_callbacks.empty()
    assert any(call[0] == 50 for call in ctl.root.pending.values())


def test_ui_dispatch_after_window_destruction_is_safe(ctl):
    ctl.root.after = Mock(side_effect=module.TclError('window destroyed'))
    ctl._drain_ui_callbacks()
    assert ctl._ui_callbacks.empty()


@pytest.mark.parametrize('retry', [True, False])
def test_journal_update_error_obeys_retry_or_cancel(ctl, retry):
    ctl.model.read_journals.side_effect = OSError('temporarily unavailable')
    ctl.view.show_message_box_askretrycancel.return_value = retry
    ctl.update_journals()
    assert ctl.root.destroyed is not retry
    ctl.view.show_message_box_askretrycancel.assert_called_once()
    if retry:
        ctl.model.read_journals.side_effect = None
        ctl.root.run_delay(UPDATE_INTERVAL)
        assert ctl.model.read_journals.call_count == 2


def test_cache_write_roundtrip_and_failure_delivery_on_ui(ctl, tmp_path):
    ctl.model.journal_reader = {'events': ['retained']}
    target = tmp_path / 'cache' / 'journal.pickle'
    with ThreadPoolExecutor(max_workers=1) as worker:
        worker.submit(ctl._save_cache, str(target), True).result(timeout=5)
    assert pickle.loads(target.read_bytes()) == {'events': ['retained']}
    assert not ctl.root.pending
    ctl._drain_ui_callbacks()
    assert any(call[0] == SAVE_CACHE_INTERVAL for call in ctl.root.pending.values())
    with ThreadPoolExecutor(max_workers=1) as worker:
        worker.submit(ctl._save_cache, str(tmp_path), True).result(timeout=5)
    ctl.view.show_message_box_warning.assert_not_called()
    ctl._drain_ui_callbacks()
    ctl.view.show_message_box_warning.assert_called_once()


def test_cache_clear_removes_only_cache_and_reloads(ctl, tmp_path, monkeypatch):
    target = tmp_path / 'cache.pickle'
    target.write_bytes(b'old cache')
    unrelated = tmp_path / 'notes.csv'
    unrelated.write_text('important notes', encoding='utf-8')
    monkeypatch.setattr(module, 'getCachePath', lambda *args: str(target))
    ctl.reload = Mock()
    ctl.button_click_clear_cache()
    assert not target.exists()
    assert unrelated.read_text(encoding='utf-8') == 'important notes'
    ctl.reload.assert_called_once()
    ctl._drain_ui_callbacks()
    ctl.view.show_message_box_info.assert_called_once()


def test_cache_clear_missing_file_does_not_reload(ctl, tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'getCachePath', lambda *args: str(tmp_path / 'absent'))
    ctl.reload = Mock()
    ctl.button_click_clear_cache()
    ctl._drain_ui_callbacks()
    ctl.reload.assert_not_called()
    ctl.view.show_message_box_info.assert_called_once()


@pytest.mark.parametrize('success', [True, False])
def test_clipboard_success_callback_only_runs_after_copy(ctl, monkeypatch, success):
    copied = Mock(side_effect=None if success else module.pyperclip.PyperclipException('unavailable'))
    monkeypatch.setattr(module.pyperclip, 'copy', copied)
    callback = Mock()
    ctl.copy_to_clipboard('Mission 100', 'Copied', 'Ready', callback)
    copied.assert_called_once_with('Mission 100')
    assert callback.call_count == int(success)
    assert ctl.view.show_message_box_info.call_count == int(success)
    assert ctl.view.show_message_box_warning.call_count == int(not success)


@pytest.mark.parametrize('rows,allow_multiple,expected', [
    ((), False, None), ((2,), False, 2), ((1, 2), False, None),
    ((1, 2), True, (1, 2)),
])
def test_row_selection_has_explicit_multiple_selection_behavior(ctl, rows, allow_multiple, expected):
    ctl.view.sheet_missions.get_selected_rows.return_value = rows
    assert ctl.get_selected_row(allow_multiple=allow_multiple) == expected
