"""Small synthetic journals: no player files, credentials, or wall-clock dependency."""
import json
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)


def stamp(seconds=0):
    return (NOW + timedelta(seconds=seconds)).strftime('%Y-%m-%dT%H:%M:%SZ')


def event(name, seconds=0, **fields):
    return dict(event=name, timestamp=stamp(seconds), **fields)


def sample_events(fid='F1', mission_id=100, name=None, system='Sol', station='Galileo'):
    """Return fresh complete records covering the tracker model inputs."""
    return [
        event('Commander', -60, FID=fid, Name=name or f'Commander {fid}'),
        event('LoadGame', -59, FID=fid, Commander=name or f'Commander {fid}'),
        event('FSDJump', -58, StarSystem=system),
        event('Docked', -57, StarSystem=system, StationName=station, MarketID=1),
        event('MissionAccepted', -50, MissionID=mission_id, Name='Mission_Massacre_Test',
              TargetFaction='Pirates', DestinationSystem='Achenar', Faction='Federation',
              KillCount=10, Reward=1_000_000, Wing=True, Expiry=stamp(86400)),
        event('Missions', -49, Active=[{'MissionID': mission_id}], Failed=[], Complete=[]),
    ]

def append_events(path, *events):
    with path.open('ab') as stream:
        for record in events:
            stream.write((json.dumps(record, ensure_ascii=False) + '\n').encode('utf-8'))


def write_journal(tmp_path, events, filename='Journal.2026-01-02T120000.01.log'):
    tmp_path.mkdir(parents=True, exist_ok=True)
    result = tmp_path / filename
    result.write_bytes(b'')
    append_events(result, *events)
    return result


def freeze_clock(monkeypatch, now=NOW):
    import model

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz is not None else now.astimezone().replace(tzinfo=None)

    monkeypatch.setattr(model, 'datetime', FrozenDateTime)


def make_model(tmp_path, events=None):
    from model import MissionModel
    write_journal(tmp_path, sample_events() if events is None else events)
    return MissionModel([str(tmp_path)])


def assert_tables_render(model):
    """Exercise every tracker table API without presentation snapshots."""
    model.update_data_missions(NOW)
    for fid in model.get_all_fids():
        rows, redirected, turn_in = model.get_data_active_missions(fid, NOW)
        assert all(len(row) == 9 or row == ['No active missions'] for row in rows)
        assert all(index < len(rows) for index in redirected + turn_in)
        distribution, in_system = model.get_data_distribution(fid)
        assert all(len(row) == 4 or len(row) == 1 for row in distribution)
        assert all(index < len(distribution) for index in in_system)
        stats, rewards = model.get_data_mission_stats(fid)
        assert isinstance(stats, list) and isinstance(rewards, list)
    assert isinstance(model.get_data_active_journals(), list)
