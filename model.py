import hashlib
from typing import NamedTuple
import pandas as pd
from os import listdir, path
import re
import json
from datetime import datetime, timezone, timedelta
from humanize import naturaltime, naturaldelta
from random import random
import inspect
from utility import getHammerCountdown, getResourcePath, getJournalPath
from config import MISSION_CUTOFF

class JournalReader:
    _timestamp_pattern = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z')

    @classmethod
    def version_hash(cls) -> str:
        src = inspect.getsource(cls)
        return hashlib.md5(src.encode('utf-8')).hexdigest()

    def __init__(self, journal_paths:list[str], dropout:bool=False, droplist:list[str]=None):
        self.version = self.version_hash()
        
        self.journal_paths = journal_paths
        self.journal_processed = set()
        self.journal_latest = {}
        self.journal_latest_unknown_fid = {}
        self._journal_pending = {}
        # File progress is independent of account identity and displayed session status.
        self._journal_cursors = {}
        self._load_games = []
        self._missions = []
        self._missions_accepted = []
        self._missions_redirected = []
        self._missions_completed = []
        self._missions_failed = []
        self._missions_abandoned = []
        self._docked = []
        self._undocked = []
        self._fsd_jumps = []
        self.tracked_items = ["load_games", "missions", "missions_accepted", "missions_redirected", "missions_completed", "missions_failed", "missions_abandoned", "docked", "undocked", "fsd_jumps"]
        self._last_items_count = {item_type: len(getattr(self, f'_{item_type}')) for item_type in self.tracked_items}
        self._last_items_count_pending = {item_type: len(getattr(self, f'_{item_type}')) for item_type in self.tracked_items}
        self.dropout = dropout
        self.droplist = droplist
        if self.dropout == True:
            if self.droplist is None:
                print('Dropout mode active, journal data is randomly dropped')
                self.droplist = [i for i in range(10) if random() < 0.5]
                for i in self.droplist:
                    print(f'{self.tracked_items[i]} was dropped')
            else:
                print('Dropout mode active, journal data is dropped')
                self.droplist = [self.tracked_items.index(i) for i in self.droplist]
                for i in self.droplist:
                    print(f'{self.tracked_items[i]} was dropped')

    def read_journals(self):
        journals = []
        for journal_path in self.journal_paths:
            try:
                files = listdir(journal_path)
            except OSError as e:
                print(f'{journal_path} {e}')
                continue
            r = r'^Journal\.\d{4}-\d{2}-\d{2}T\d{6}\.\d{2}\.log$'
            journal_files = sorted([i for i in files if re.fullmatch(r, i)], reverse=False)
            journals += [path.join(journal_path, i) for i in journal_files]
        directory_order = {path.normcase(path.abspath(directory)): index
                           for index, directory in enumerate(self.journal_paths)}

        def journal_order(filename):
            # Directory enumeration can temporarily omit a known newer journal.
            directory = path.normcase(path.abspath(path.dirname(filename)))
            return directory_order.get(directory, -1), path.basename(filename)

        for journal in journals:
            newer_latest = {fid: info for fid, info in self.journal_latest.items()
                            if journal_order(info['filename']) > journal_order(journal)}
            if journal in self._journal_pending:
                pending = self._journal_pending[journal]
                # A delayed tail may reveal its FID only after a newer journal is active.
                self._read_journal(journal, pending['byte_pos'], pending['fid'], set(newer_latest))
            elif journal not in self.journal_processed:
                self._read_journal(journal)
            elif journal in self._journal_cursors:
                cursor = self._journal_cursors[journal]
                try:
                    has_updates = path.getsize(journal) > cursor['byte_pos']
                except OSError as e:
                    print(f'{journal} {e}')
                    continue
                if has_updates:
                    self._read_journal(journal, cursor['byte_pos'], cursor['fid'])
            # Older shared files may still grow without replacing a newer session's display.
            self.journal_latest.update(newer_latest)
            # Once a newer journal identifies the same commander, the old tail is final.
            for pending_path, pending in list(self._journal_pending.items()):
                latest = self.journal_latest.get(pending['fid'])
                if latest is not None and journal_order(latest['filename']) > journal_order(pending_path):
                    self._retire_pending_journal(pending_path)
    
    def _retire_pending_journal(self, journal_path:str):
        self._journal_pending.pop(journal_path, None)
        self._journal_cursors.pop(journal_path, None)
        self.journal_latest_unknown_fid.pop(journal_path, None)
        self.journal_processed.add(journal_path)

    def _remember_journal_cursor(self, journal_path:str, byte_pos:int, fid:str|None):
        self._journal_cursors[journal_path] = {'byte_pos': byte_pos, 'fid': fid}
        for info in self.journal_latest.values():
            if info['filename'] == journal_path:
                info['byte_pos'] = byte_pos
        if journal_path in self.journal_latest_unknown_fid:
            self.journal_latest_unknown_fid[journal_path]['byte_pos'] = byte_pos
        self.journal_processed.add(journal_path)

    def _read_journal(self, journal_path:str, byte_pos:int=0, fid_last:str|None=None,
                      superseded_fids:set[str]|None=None):
        items = []
        incomplete = False
        try:
            with open(journal_path, 'rb') as f:
                f.seek(byte_pos)
                while True:
                    byte_pos_new = f.tell()
                    line = f.readline()
                    if not line:
                        break
                    if not line.endswith(b'\n'):
                        incomplete = True
                        break
                    try:
                        item = json.loads(line.decode('utf-8'))
                        if not isinstance(item, dict) or not isinstance(item.get('event'), str) or not item['event']:
                            raise ValueError('Journal record must have an event name')
                        if item['event'] == 'Commander' and (not isinstance(item.get('FID'), str) or not item['FID']):
                            raise ValueError('Commander record must have an FID')
                        if item['event'] == 'MissionAccepted' and type(item.get('MissionID')) is not int:
                            raise ValueError('MissionAccepted record must have a MissionID')
                        self._timestamp_key(item)
                        items.append(item)
                    except (UnicodeDecodeError, ValueError, KeyError) as e:
                        # Skip damaged complete records; partial records wait for a newline.
                        print(f'{journal_path} {e}')
        except OSError as e:
            print(f'{journal_path} {e}')
            return

        if len(items) == 0:
            # Advance over malformed complete lines without changing known identity/status.
            self._remember_journal_cursor(journal_path, byte_pos_new, fid_last)
            if incomplete:
                self._journal_pending[journal_path] = {'byte_pos': byte_pos_new, 'fid': fid_last}
            else:
                self._journal_pending.pop(journal_path, None)
            return
        # An unknown-FID tail may reveal its identity only after its successor was read.
        # Retire it before parsing, so historical events cannot reach incremental consumers.
        fids = [item['FID'] for item in items if item['event'] == 'Commander']
        if superseded_fids:
            pending_fid = fids[0] if fids and all(fid == fids[0] for fid in fids) else fid_last
            if pending_fid in superseded_fids:
                self._retire_pending_journal(journal_path)
                return
        parsed_fid, is_active = self._parse_items(items, fid_last)
        if fids and parsed_fid is None:
            fid = None
        elif fid_last is None:
            fid = parsed_fid
        elif parsed_fid is not None and parsed_fid != fid_last:
            fid = None
        else:
            fid = fid_last
        self._remember_journal_cursor(journal_path, byte_pos_new, fid)
        if incomplete:
            self._journal_pending[journal_path] = {'byte_pos': byte_pos_new, 'fid': fid}
        else:
            self._journal_pending.pop(journal_path, None)
        if is_active:
            if fid is None:
                match = re.search(r'\d{4}-\d{2}-\d{2}T\d{6}', journal_path)
                if datetime.now() - datetime.strptime(match.group(0), '%Y-%m-%dT%H%M%S') < timedelta(hours=1): # allows one hour for fid to show up
                    self.journal_latest_unknown_fid[journal_path] = {'filename': journal_path, 'byte_pos': byte_pos_new, 'is_active': is_active}
                else:
                    self.journal_latest_unknown_fid.pop(journal_path, None)
            else:
                self.journal_latest_unknown_fid.pop(journal_path, None)
                self.journal_latest[fid] = {'filename': journal_path, 'byte_pos': byte_pos_new, 'is_active': is_active}
        else:
            self.journal_latest_unknown_fid.pop(journal_path, None)
            if fid is not None:
                self.journal_latest[fid] = {'filename': journal_path, 'byte_pos': byte_pos_new, 'is_active': is_active}
        self.journal_processed.add(journal_path)


    def _parse_items(self, items:list, fid_last:str|None) -> tuple[str|None, bool]:
        fid_parsed = None
        fid_temp = [i['FID'] for i in items if i['event'] =='Commander']
        if len(fid_temp) > 0:
            if all(i == fid_temp[0] for i in fid_temp):
                fid_parsed = fid_temp[0]
        fid = fid_parsed if fid_temp else fid_last
        for item in items:
            if item['event'] == 'LoadGame':
                self._load_games.append(item)
            if item['event'] == 'Missions':
                item['FID'] = fid
                self._missions.append(item)
            if item['event'] == 'MissionAccepted':
                item['FID'] = fid
                self._missions_accepted.append(item)
            if item['event'] == 'MissionRedirected':
                item['FID'] = fid
                self._missions_redirected.append(item)
            if item['event'] == 'MissionCompleted':
                item['FID'] = fid
                self._missions_completed.append(item)
            if item['event'] == 'MissionFailed':
                item['FID'] = fid
                self._missions_failed.append(item)
            if item['event'] == 'MissionAbandoned':
                item['FID'] = fid
                self._missions_abandoned.append(item)
            if item['event'] == 'Docked':
                item['FID'] = fid
                self._docked.append(item)
            if item['event'] == 'Undocked':
                item['FID'] = fid
                self._undocked.append(item)
            if item['event'] == 'FSDJump':
                item['FID'] = fid
                self._fsd_jumps.append(item)
                
        is_active = len(items) == 0 or items[-1]['event'] != 'Shutdown'
        return fid_parsed, is_active
    
    @classmethod
    def _timestamp_key(cls, item) -> str:
        timestamp = item['timestamp']
        if not isinstance(timestamp, str) or cls._timestamp_pattern.fullmatch(timestamp) is None:
            raise ValueError(f'Invalid journal timestamp {timestamp!r}: expected YYYY-MM-DDTHH:MM:SSZ')
        try:
            datetime.fromisoformat(timestamp[:-1])
        except ValueError as e:
            raise ValueError(f'Invalid journal timestamp {timestamp!r}: invalid date or time') from e
        return timestamp

    def _get_parsed_items(self):
        return [sorted(getattr(self, f'_{item_type}'), key=self._timestamp_key, reverse=True)
                for item_type in self.tracked_items]
    
    def get_items(self) -> list:
        self._last_items_count_pending = {item_type: len(getattr(self, f'_{item_type}')) for item_type in self.tracked_items}
        items = self._get_parsed_items()
        if self.dropout:
            for i in self.droplist:
                items[i] = type(items[i])()
        return items
    
    def get_new_items(self) -> list:
        items = []
        for item_type in self.tracked_items:
            items.append(getattr(self, f'_{item_type}')[self._last_items_count[item_type]:])
        self._last_items_count_pending = {item_type: len(getattr(self, f'_{item_type}')) for item_type in self.tracked_items}
        return items
    
    def update_items_count(self):
        self._last_items_count = self._last_items_count_pending.copy()

    def get_latest_active_journals(self) -> dict[str, str]|None:
        results = {}
        for fid, info in self.journal_latest.items():
            if info['is_active']:
                results[fid] = info['filename']
        return results if results else None
        
    def get_active_unknown_fid_journals(self) -> dict[str, str]|None:
        results = {}
        for journal, info in self.journal_latest_unknown_fid.items():
            if info['is_active']:
                results[journal] = info['filename']
        return results if results else None

class MissionModel:
    def __init__(self, journal_paths:list[str], journal_reader:JournalReader|None=None, dropout:bool=False, droplist:list[str]=None):
        self.journal_reader = journal_reader if journal_reader else JournalReader(journal_paths, dropout=dropout, droplist=droplist)
        self.dropout = dropout
        self.droplist = droplist
        self.data_missions = {}
        self.missions_updated = {}
        self.cmdr_names = {}
        self._load_game_times = {}
        self.cmdr_locations = {}
        self.missions = {}
        self.missions_accepted = {}
        self.missions_completed = {}
        self.missions_failed = {}
        self.missions_abandoned = {}
        self.journal_paths = journal_paths
        self.read_journals()

    def read_journals(self):
        # self.data_missions = {}
        self.journal_reader.read_journals()
        first_read = self.data_missions == {}
        load_games, missions, missions_accepted, missions_redirected, missions_completed, missions_failed, missions_abandoned, docked, undocked, fsd_jumps = self.journal_reader.get_items() if first_read else self.journal_reader.get_new_items()

        self.process_load_games(load_games)

        self.process_itinerary(docked, undocked, fsd_jumps)

        # self.process_fsd_jumps(fsd_jumps)

        self.process_missions(missions)
        
        self.process_missions_accepted(missions_accepted)

        self.process_missions_redirected(missions_redirected)

        self.process_missions_completed(missions_completed)

        self.process_missions_failed(missions_failed)

        self.process_missions_abandoned(missions_abandoned)

        self.update_data_missions(datetime.now(timezone.utc))

        self.journal_reader.update_items_count()

    def process_load_games(self, load_games, first_read:bool=True):
        for load_game in sorted(load_games, key=lambda item: item['timestamp']):
            fid = load_game['FID']
            timestamp = datetime.strptime(load_game['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
            if fid not in self._load_game_times or timestamp >= self._load_game_times[fid]:
                self._load_game_times[fid] = timestamp
                self.cmdr_names[fid] = load_game['Commander']

    def process_itinerary(self, docked, undocked, fsd_jumps, first_read:bool=True):
        df_events = pd.DataFrame(docked + undocked + fsd_jumps, columns=['timestamp', 'event', 'StationName', 'StarSystem', 'MarketID', 'FID'], )
        df_events['timestamp'] = df_events['timestamp'].apply(lambda x: datetime.strptime(x, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc))
        df_events = df_events.sort_values(by='timestamp', ascending=True).reset_index(drop=True)
        df_events = df_events.astype({'MarketID': 'Int64'})

        for fid in df_events['FID'].unique():
            df_fid = df_events[df_events['FID'] == fid].copy()
            if df_fid.empty:
                if fid not in self.cmdr_locations.keys():
                    self.cmdr_locations[fid] = pd.DataFrame(columns=['StarSystem', 'StationName', 'MarketID', 'DockedAt', 'UndockedAt', 'JumpedInAt'])
            else:
                df_old:pd.DataFrame = self.cmdr_locations.get(fid, pd.DataFrame(columns=['StarSystem', 'StationName', 'MarketID', 'DockedAt', 'UndockedAt', 'JumpedInAt'])).copy()
                df_old = df_old.astype({'MarketID': 'Int64'})
                itinerary = df_old.to_dict('records')
                for i in range(df_fid.shape[0]):
                    event = df_fid.iloc[i]
                    if event['event'] == 'Docked':
                        if len(itinerary) == 0 or pd.isna(event['StarSystem']) or pd.isna(itinerary[-1]['StarSystem']) or itinerary[-1]['StarSystem'] != event['StarSystem'] or pd.notna(itinerary[-1]['DockedAt']):
                            itinerary.append({'StarSystem': event['StarSystem'], 'StationName': event['StationName'], 'MarketID': event['MarketID'], 'DockedAt': event['timestamp'], 'UndockedAt': None, 'JumpedInAt': None})
                        else:
                            itinerary[-1]['DockedAt'] = event['timestamp']
                            itinerary[-1]['StationName'] = event['StationName']
                            itinerary[-1]['MarketID'] = event['MarketID']
                    elif event['event'] == 'Undocked':
                        if len(itinerary) == 0 or pd.isna(event['MarketID']) or pd.isna(itinerary[-1]['MarketID']) or itinerary[-1]['MarketID'] != event['MarketID'] or pd.notna(itinerary[-1]['UndockedAt']):
                            itinerary.append({'StarSystem': None, 'StationName': event['StationName'], 'MarketID': event['MarketID'], 'DockedAt': None, 'UndockedAt': event['timestamp'], 'JumpedInAt': None})
                        else:
                            itinerary[-1]['UndockedAt'] = event['timestamp']
                            itinerary[-1]['StationName'] = event['StationName']
                            if pd.notna(itinerary[-1]['StarSystem']) and itinerary[-1]['StationName'] == event['StationName']:
                                itinerary[-1]['StarSystem'] = itinerary[-1]['StarSystem']
                    elif event['event'] == 'FSDJump':
                        itinerary.append({'StarSystem': event['StarSystem'], 'StationName': None, 'MarketID': None, 'DockedAt': None, 'UndockedAt': None, 'JumpedInAt': event['timestamp']})
                    else:
                        raise ValueError(f'Unknown event type {event["event"]} in itinerary events')

                df_itinerary = pd.DataFrame(itinerary)
                df_itinerary = df_itinerary.astype({'MarketID': 'Int64'})
                self.cmdr_locations[fid] = df_itinerary.copy()

    # def process_fsd_jumps(self, fsd_jumps):
    #     df_jumps = pd.DataFrame(fsd_jumps, columns=['timestamp', 'Taxi', 'Multicrew', 'StarSystem', 'FID', 'Factions'])
    #     df_jumps['timestamp'] = df_jumps['timestamp'].apply(lambda x: datetime.strptime(x, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc))
    #     for fid in df_jumps['FID'].unique():
    #         df_jumps_fid = df_jumps[df_jumps['FID'] == fid].copy()
    #         if df_jumps_fid.empty:
    #             pass
    #         else:
    #             if __name__ == '__main__':
    #                 print(f'FSD Jump events for {self.cmdr_names.get(fid, "Unknown")} ({fid}):')
    #                 print(df_jumps_fid)
    #             if fid not in self.cmdr_locations.keys():
    #                 self.cmdr_locations[fid] = pd.DataFrame(columns=['StarSystem', 'StationName', 'MarketID', 'DockedAt', 'UndockedAt', 'JumpedInAt'])
    #             df_old = self.cmdr_locations[fid].copy()
    #             df_new = df_old.copy()
    #             for i, event in df_jumps_fid.iterrows():
    #                 if event['StarSystem'] not in df_new['StarSystem'].values:
    #                     df_new = pd.concat([df_new, pd.DataFrame([{
    #                         'StarSystem': event['StarSystem'],
    #                         'StationName': None,
    #                         'MarketID': None,
    #                         'DockedAt': None,
    #                         'UndockedAt': None,
    #                         'JumpedInAt': event['timestamp']
    #                     }])], ignore_index=True)
    #                 else:
    #                     idx = df_new[df_new['StarSystem'] == event['StarSystem']].index[0]
    #                     df_new.loc[idx, 'JumpedInAt'] = event['timestamp']
    #             self.cmdr_locations[fid] = df_new.copy()

    def initialize_mission_data(self, fid: str):
        if fid not in self.data_missions.keys():
            self.data_missions[fid] = {}
        if 'Missions' not in self.data_missions[fid].keys():
            self.data_missions[fid]['Missions'] = {}
        if 'Active' not in self.data_missions[fid].keys():
            self.data_missions[fid]['Active'] = []
        if 'Failed' not in self.data_missions[fid].keys():
            self.data_missions[fid]['Failed'] = []
        if 'Complete' not in self.data_missions[fid].keys():
            self.data_missions[fid]['Complete'] = []

    def process_missions(self, missions):
        if __name__ == '__main__':
            print('Missions:')
            print(*missions[:10], sep='\n')
        for mission in missions:
            self.initialize_mission_data(mission['FID'])
            self.data_missions[mission['FID']]['Active'] = [item['MissionID'] for item in mission['Active']]
            self.data_missions[mission['FID']]['Failed'] = [item['MissionID'] for item in mission['Failed']]
            self.data_missions[mission['FID']]['Complete'] = [item['MissionID'] for item in mission['Complete']]

    def process_missions_accepted(self, missions_accepted):
        if __name__ == '__main__':
            print('Missions Accepted:')
            print(*missions_accepted[:10], sep='\n')
        for mission in missions_accepted:
            if mission['Name'].startswith('Mission_Massacre') and datetime.strptime(mission['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) - timedelta(days=MISSION_CUTOFF):
                self.initialize_mission_data(mission['FID'])
                system, station = self.get_cmdr_location(mission['FID'], datetime.strptime(mission['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc))
                self.data_missions[mission['FID']]['Missions'][mission['MissionID']] = {
                    'TargetFaction': mission['TargetFaction'],
                    'DestinationSystem': mission['DestinationSystem'],
                    'System': system,
                    'Station': station,
                    'Faction': mission['Faction'],
                    'KillCount': mission['KillCount'],
                    'Reward': mission['Reward'],
                    'Wing': mission['Wing'],
                    'Expiry': datetime.strptime(mission['Expiry'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc),
                    'Redirected': False,
                }

    def process_missions_redirected(self, missions_redirected):
        if __name__ == '__main__':
            print('Missions Redirected:')
            print(*missions_redirected[:10], sep='\n')
        for mission in missions_redirected:
            if datetime.strptime(mission['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) - timedelta(days=MISSION_CUTOFF):
                self.initialize_mission_data(mission['FID'])
                if mission['MissionID'] in self.data_missions[mission['FID']]['Missions'].keys():
                    self.data_missions[mission['FID']]['Missions'][mission['MissionID']]['Redirected'] = True

    def process_missions_completed(self, missions_completed):
        if __name__ == '__main__':
            print('Missions Completed:')
            print(*missions_completed[:10], sep='\n')
        for mission in missions_completed:
            if datetime.strptime(mission['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) - timedelta(days=MISSION_CUTOFF):
                fid = mission['FID']
                self.initialize_mission_data(fid)
                missionID = mission['MissionID']
                if fid in self.data_missions.keys() and 'Missions' in self.data_missions[fid].keys():
                    self.data_missions[fid]['Missions'].pop(mission['MissionID'], None)
                    if missionID in self.data_missions[fid]['Active']:
                        self.data_missions[fid]['Active'].remove(mission['MissionID'])
                    if missionID in self.data_missions[fid]['Complete']:
                        self.data_missions[fid]['Complete'].remove(mission['MissionID'])

    def process_missions_failed(self, missions_failed):
        if __name__ == '__main__':
            print('Missions Failed:')
            print(*missions_failed[:10], sep='\n')
        for mission in missions_failed:
            if datetime.strptime(mission['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) - timedelta(days=MISSION_CUTOFF):
                fid = mission['FID']
                self.initialize_mission_data(fid)
                missionID = mission['MissionID']
                if fid in self.data_missions.keys() and 'Missions' in self.data_missions[fid].keys():
                    self.data_missions[fid]['Missions'].pop(mission['MissionID'], None)
                    if missionID in self.data_missions[fid]['Active']:
                        self.data_missions[fid]['Active'].remove(mission['MissionID'])
                    if missionID in self.data_missions[fid]['Complete']:
                        self.data_missions[fid]['Complete'].remove(mission['MissionID'])

    def process_missions_abandoned(self, missions_abandoned):
        if __name__ == '__main__':
            print('Missions Abandoned:')
            print(*missions_abandoned[:10], sep='\n')
        for mission in missions_abandoned:
            if datetime.strptime(mission['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) - timedelta(days=MISSION_CUTOFF):
                fid = mission['FID']
                self.initialize_mission_data(fid)
                missionID = mission['MissionID']
                if fid in self.data_missions.keys() and 'Missions' in self.data_missions[fid].keys():
                    self.data_missions[fid]['Missions'].pop(mission['MissionID'], None)
                    if missionID in self.data_missions[fid]['Active']:
                        self.data_missions[fid]['Active'].remove(mission['MissionID'])
                    if missionID in self.data_missions[fid]['Complete']:
                        self.data_missions[fid]['Complete'].remove(mission['MissionID'])

    def update_data_missions(self, now):
        missions = self.data_missions.copy()
        for fid in missions.keys():
            if 'Missions' in missions[fid].keys():
                active = []
                for missionID, mission in missions[fid]['Missions'].items():
                    if missionID in missions[fid]['Complete']:
                        continue
                    if missionID in missions[fid]['Failed']:
                        continue
                    if 'Expiry' in mission.keys() and now > mission['Expiry'] + timedelta(days=14):
                        continue
                    active.append(missionID)
                missions[fid]['Active'] = active

        self.data_missions_updated = missions.copy()

    def get_data_missions(self):
        return self.data_missions_updated.copy()

    def get_missions(self, fid):
        return self.get_data_missions()[fid]['Missions'].copy()
    
    def get_cmdr_name(self, fid:str) -> str|None:
        return self.cmdr_names.get(fid, None)
    
    def get_cmdr_fid(self, cmdr_name:str) -> str|None:
        for fid, name in self.cmdr_names.items():
            if name == cmdr_name:
                return fid
        return None
    
    def get_all_cmdr_names(self) -> list[str]:
        return [self.get_cmdr_name(fid) for fid in self.get_all_fids()]
    
    def get_all_fids(self) -> list[str]:
        return sorted(list(self.cmdr_names.keys()), key=lambda x: int(x.replace('F', '')))
    
    def get_cmdr_location(self, fid:str, time:datetime) -> tuple[str|None, str|None]:
        if fid not in self.cmdr_locations.keys():
            return None, None
        df = self.cmdr_locations[fid]
        df_docked = df[(df['DockedAt'].notna()) & (df['DockedAt'] <= time) & ((df['UndockedAt'].isna()) | (df['UndockedAt'] > time))]
        if df_docked.empty:
            df_jumped = df[(df['JumpedInAt'].notna()) & (df['JumpedInAt'] <= time)]
            if df_jumped.empty:
                return None, None
            return df_jumped.iloc[-1]['StarSystem'], None
        return df_docked.iloc[-1]['StarSystem'], df_docked.iloc[-1]['StationName']

    def get_cmdr_current_location(self, fid:str) -> tuple[str|None, str|None]:
        if fid not in self.cmdr_locations.keys() or self.cmdr_locations[fid].empty:
            return None, None
        last_location = self.cmdr_locations[fid].iloc[-1]
        if pd.isna(last_location['DockedAt']) or pd.notna(last_location['UndockedAt']):
            return last_location['StarSystem'], None
        return last_location['StarSystem'], last_location['StationName']

    def get_active_missions(self, fid):
        missions = {}
        if fid in self.get_data_missions().keys():
            if 'Missions' in self.get_data_missions()[fid].keys():
                for missionID in self.get_data_missions()[fid]['Active']:
                    if missionID in self.get_data_missions()[fid]['Missions'].keys():
                        missions[missionID] = self.get_data_missions()[fid]['Missions'][missionID].copy()
        return missions
    
    def generate_info_active_missions(self, fid, now):
        missions = self.get_active_missions(fid)
        missions_sorted = sorted(missions.items(), key=lambda x: x[0], reverse=True)
        info = {}
        for missionID, mission in missions_sorted:
            info[missionID] = {
                'TargetFaction': mission.get('TargetFaction', None),
                'DestinationSystem': mission.get('DestinationSystem', None),
                'System': mission.get('System', None),
                'Station': mission.get('Station', None),
                'Faction': mission.get('Faction', None),
                'Wing': mission.get('Wing', None),
                'KillCount': mission.get('KillCount', None),
                'Reward': mission.get('Reward', None),
                'Expires': mission.get('Expiry', None),
            }
        redirected = [i for i, (_, mission) in enumerate(missions_sorted) if mission.get('Redirected', False)]
        docked_system, docked_station = self.get_cmdr_current_location(fid)
        if docked_system is None or docked_station is None:
            return info, redirected, []
        at_location = [i for i, (_, mission) in enumerate(missions_sorted) if mission['System'] == docked_system and mission['Station'] == docked_station]
        turn_in_here = [i for i in redirected if i in at_location]
        return info, redirected, turn_in_here

    def get_data_active_missions(self, fid:str|None, now) -> tuple[list[list], list[int], list[int]]:
        if fid is None:
            return [['No active missions']], [], []
        missions, redirected, turn_in_here = self.generate_info_active_missions(fid, now)
        df = pd.DataFrame(missions).T
        if df.empty:
            return [['No active missions']], [], []
        df['Expires'] = df['Expires'].apply(lambda x: naturaltime(x) if isinstance(x, datetime) else '')
        df['Reward'] = df['Reward'].apply(lambda x: f"{x:,}" if pd.notna(x) else '')
        df['Wing'] = df['Wing'].apply(lambda x: 'Yes' if x else 'No')
        return df[['TargetFaction', 'DestinationSystem', 'System', 'Station', 'Faction', 'Wing', 'KillCount', 'Reward', 'Expires']].values.tolist(), redirected, turn_in_here
    
    def get_data_distribution(self, fid:str|None) -> tuple[list[list], list[int]]:
        if fid is None:
            return [['No active missions']], []
        missions = self.get_active_missions(fid)
        df = pd.DataFrame(missions).T
        if df.empty:
            return [['No active missions']], []
        df = df[df['Redirected'] == False]
        if df.empty:
            return [['No incomplete missions']], []
        distribution = df[['Faction', 'KillCount']].groupby('Faction').sum().reset_index()
        distribution = distribution.sort_values(by='KillCount', ascending=True).reset_index(drop=True)
        distribution.index += 1
        distribution['Difference'] = distribution['KillCount'].max() - distribution['KillCount']
        distribution['LowestReward'] = distribution['Faction'].apply(lambda x: f'{df[df["Faction"] == x]["Reward"].min():,}')
        current_system, _ = self.get_cmdr_current_location(fid)
        factions_in_system = df[df['System'] == current_system]['Faction'].unique().tolist()
        in_system = [i for i, faction in enumerate(distribution['Faction']) if faction in factions_in_system]
        return distribution.values.tolist(), in_system

    def get_data_mission_stats(self, fid:str|None) -> tuple[list[list], list[list]]:
        if fid is None:
            return [], []
        missions = self.get_active_missions(fid)
        df = pd.DataFrame(missions).T
        if df.empty:
            return [['No active missions']], [['No active missions']]
        df_redirected = df[df['Redirected'] == True]
        completed_kills = df_redirected[['Faction', 'KillCount']].groupby('Faction').sum().max()['KillCount'] if not df_redirected.empty else 0
        kill_count = df[['Faction', 'KillCount']].groupby('Faction').sum().max()['KillCount']
        total_kill_count = df['KillCount'].sum()
        total_reward = df['Reward'].sum()
        sharable_reward = df[df['Wing'] == True]['Reward'].sum()
        current_reward = df_redirected['Reward'].sum() if not df_redirected.empty else 0
        current_sharable_reward = df_redirected[df_redirected['Wing'] == True]['Reward'].sum() if not df_redirected.empty else 0
        stats = {
            'TotalMissions': df.shape[0],
            'WingMissions': df[df['Wing'] == True].shape[0],
            'ActiveMissions': df.shape[0] - df_redirected.shape[0],
            'KillCount': kill_count,
            'KillRemaining': kill_count - completed_kills,
            'TotalKillCount': total_kill_count,
            'KillRatio': f"{total_kill_count / kill_count:.2f}",
            'NumStations': df['Station'].nunique(),
        }
        stats_rewards = {
            'TotalReward': f"{total_reward:,}",
            'TotalSharableReward': f"{sharable_reward:,}",
            'CurrentReward': f"{current_reward:,}",
            'CurrentSharableReward': f"{current_sharable_reward:,}",
            'AverageReward': f"{total_reward / df.shape[0]:,.0f}",
            'AverageSharableReward': f"{sharable_reward / df[df['Wing'] == True].shape[0]:,.0f}" if df[df['Wing'] == True].shape[0] > 0 else 0,
        }
        return list(stats.items()), list(stats_rewards.items())

    class ActiveJournalInfo(NamedTuple):
        fid: str
        cmdr_name: str
        journal_file: str

    def generate_info_active_journals(self) -> list['MissionModel.ActiveJournalInfo']|None:
        active = self.journal_reader.get_latest_active_journals()
        if active is None:
            return None
        fids, journals = active.keys(), active.values()
        return [
            self.ActiveJournalInfo(
                fid=fid,
                cmdr_name=self.cmdr_names.get(fid, 'Unknown'),
                journal_file=journal,
            )
            for fid, journal in zip(fids, journals)
        ]

    def generate_info_active_unknown_fid_journals(self) -> list['MissionModel.ActiveJournalInfo']|None:
        active = self.journal_reader.get_active_unknown_fid_journals()
        if active is None:
            return None
        _, journals = active.keys(), active.values()
        return [
            self.ActiveJournalInfo(
                fid='Unknown (journal corrupted)',
                cmdr_name='Unknown',
                journal_file=journal,
            )
            for journal in journals
        ]
    
    def get_data_active_journals(self) -> list['MissionModel.ActiveJournalInfo']:
        active_journals = self.generate_info_active_journals()
        unknown_fid_journals = self.generate_info_active_unknown_fid_journals()
        if active_journals is None and unknown_fid_journals is None:
            return [self.ActiveJournalInfo('N/A', 'N/A', 'No active journals detected')]
        elif unknown_fid_journals is None:
            return active_journals.copy()
        elif active_journals is None:
            return unknown_fid_journals.copy()
        else:
            return active_journals.copy() + unknown_fid_journals.copy()

    def get_active_journal_paths(self) -> list[str]|None:
        active_journals = self.journal_reader.get_latest_active_journals()
        unknown_fid_journals = self.journal_reader.get_active_unknown_fid_journals()
        paths = []
        if active_journals is not None:
            paths += list(active_journals.values())
        if unknown_fid_journals is not None:
            paths += list(unknown_fid_journals.values())

        return paths if paths else None

if __name__ == '__main__':
    # journal_reader = JournalReader(getJournalPath())
    # journal_reader.read_journals()
    # print(*[i[:10] for i in journal_reader.get_items()], sep='\n\n')
    model = MissionModel([getJournalPath()])
    print(*list(model.get_missions('F11601975').values())[:10], sep='\n')
    print(pd.DataFrame(model.get_missions('F11601975')).T)
    print(pd.DataFrame(model.get_active_missions('F11601975')).T)
    print('---'*10)
    print(pd.DataFrame(model.get_data_active_missions('F11601975', datetime.now(timezone.utc))[0]))
    print('---'*10)
    print(model.get_data_distribution('F11601975'))
    print(model.get_data_mission_stats('F11601975'))
    print(model.get_all_cmdr_names())
    print(model.get_all_fids())
    print(model.get_cmdr_name('F11601975'))
    print(model.get_cmdr_location('F11601975', datetime(2025, 10, 9, 21, 20, 42, tzinfo=timezone.utc)))
    print(model.get_cmdr_location('F11601975', datetime.now(timezone.utc)))
    print(model.get_cmdr_current_location('F11601975'))
    print(model.get_cmdr_location('F11829203', datetime(2025, 10, 31, 3, 00, 00, tzinfo=timezone.utc)))
    # print(model.get_data_missions()['F11601975']['Complete'])
    