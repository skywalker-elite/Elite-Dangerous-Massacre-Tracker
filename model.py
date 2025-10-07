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
# from config import 

class JournalReader:
    @classmethod
    def version_hash(cls) -> str:
        src = inspect.getsource(cls)
        return hashlib.md5(src.encode('utf-8')).hexdigest()

    def __init__(self, journal_paths:list[str], dropout:bool=False, droplist:list[str]=None):
        self.version = self.version_hash()
        
        self.journal_paths = journal_paths
        self.journal_processed = []
        self.journal_latest = {}
        self.journal_latest_unknown_fid = {}
        self._load_games = []
        self._missions = []
        self._missions_accepted = []
        self._missions_redirected = []
        self._missions_completed = []
        self._missions_failed = []
        self._missions_abandoned = []
        self.tracked_items = ["load_games", "missions", "missions_accepted", "missions_redirected", "missions_completed", "missions_failed", "missions_abandoned"]
        self._last_items_count = {item_type: len(getattr(self, f'_{item_type}')) for item_type in self.tracked_items}
        self._last_items_count_pending = {item_type: len(getattr(self, f'_{item_type}')) for item_type in self.tracked_items}
        self.items = []
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
        latest_journal_info = {}
        for key, value in zip(self.journal_latest.keys(), self.journal_latest.values()):
            latest_journal_info[value['filename']] = {'fid': key, 'line_pos': value['line_pos'], 'is_active': value['is_active']}
        journals = []
        for journal_path in self.journal_paths:
            files = listdir(journal_path)
            r = r'^Journal\.\d{4}-\d{2}-\d{2}T\d{6}\.\d{2}\.log$'
            journal_files = sorted([i for i in files if re.fullmatch(r, i)], reverse=False)
            assert len(journal_files) > 0, f'No journal files found in {journal_path}'
            journals += [path.join(journal_path, i) for i in journal_files]
        for journal in journals:
            if journal not in self.journal_processed:
                self._read_journal(journal)
            elif journal in latest_journal_info.keys():
                if latest_journal_info[journal]['is_active']:
                    self._read_journal(journal, latest_journal_info[journal]['line_pos'], latest_journal_info[journal]['fid'])
            elif journal in self.journal_latest_unknown_fid.keys():
                self._read_journal(journal, self.journal_latest_unknown_fid[journal]['line_pos'])
        self.items = self._get_parsed_items()
    
    def _read_journal(self, journal_path:str, line_pos:int|None=None, fid_last:str|None=None):
        # print(journal)
        items = []
        with open(journal_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            line_pos_new = len(lines)
            lines = lines[line_pos:]
            # if line_pos is not None:
            #     print(*lines, sep='\n')
            for i in lines:
                try:
                    items.append(json.loads(i))
                except json.decoder.JSONDecodeError as e: # ignore ill-formated entries
                    print(f'{journal_path} {e}')
                    continue
        
        parsed_fid, is_active = self._parse_items(items)
        if fid_last is None:
            fid = parsed_fid
        elif parsed_fid is not None and parsed_fid != fid_last:
            fid = None
        else:
            fid = fid_last
        if is_active:
            if fid is None:
                match = re.search(r'\d{4}-\d{2}-\d{2}T\d{6}', journal_path)
                if datetime.now() - datetime.strptime(match.group(0), '%Y-%m-%dT%H%M%S') < timedelta(hours=1): # allows one hour for fid to show up
                    self.journal_latest_unknown_fid[journal_path] = {'filename': journal_path, 'line_pos': line_pos_new, 'is_active': is_active}
                else:
                    self.journal_latest_unknown_fid.pop(journal_path, None)
            else:
                self.journal_latest_unknown_fid.pop(journal_path, None)
                self.journal_latest[fid] = {'filename': journal_path, 'line_pos': line_pos_new, 'is_active': is_active}
        else:
            self.journal_latest_unknown_fid.pop(journal_path, None)
            if fid is not None:
                self.journal_latest[fid] = {'filename': journal_path, 'line_pos': line_pos_new, 'is_active': is_active}
        if journal_path not in self.journal_processed:
            self.journal_processed.append(journal_path)


    def _parse_items(self, items:list) -> tuple[str|None, bool]:
        fid = None
        fid_temp = [i['FID'] for i in items if i['event'] =='Commander']
        if len(fid_temp) > 0:
            if all(i == fid_temp[0] for i in fid_temp):
                fid = fid_temp[0]
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
                
        is_active = len(items) == 0 or items[-1]['event'] != 'Shutdown'
        return fid, is_active
    
    def _get_parsed_items(self):
        return [sorted(getattr(self, f'_{item_type}'), key=lambda x: datetime.strptime(x['timestamp'], '%Y-%m-%dT%H:%M:%SZ'), reverse=True)
                for item_type in self.tracked_items]
    
    def get_items(self) -> list:
        self._last_items_count_pending = {item_type: len(getattr(self, f'_{item_type}')) for item_type in self.tracked_items}
        if self.dropout:
            items = self.items.copy()
            for i in self.droplist:
                items[i] = type(items[i])()
            return items
        return self.items.copy()
    
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
        self.missions = {}
        self.missions_accepted = {}
        self.missions_completed = {}
        self.missions_failed = {}
        self.missions_abandoned = {}
        self.journal_paths = journal_paths
        self.read_journals()

    def read_journals(self):
        self.data_missions = {}
        self.journal_reader.read_journals()
        load_games, missions, missions_accepted, missions_redirected, missions_completed, missions_failed, missions_abandoned = self.journal_reader.get_items()

        self.process_load_games(load_games, first_read=True)
        
        self.process_missions(missions)
        
        self.process_missions_accepted(missions_accepted)

        self.process_missions_redirected(missions_redirected)

        self.process_missions_completed(missions_completed)

        self.process_missions_failed(missions_failed)

        self.process_missions_abandoned(missions_abandoned)

        self.update_data_missions(datetime.now(timezone.utc))

    def process_load_games(self, load_games, first_read:bool=True):
        for load_game in load_games:
            if not first_read or load_game['FID'] not in self.cmdr_names.keys():
                self.cmdr_names[load_game['FID']] = load_game['Commander']

    def process_missions(self, missions):
        if __name__ == '__main__':
            print('Missions:')
            print(*missions[:10], sep='\n')
        for mission in missions:
            if mission['FID'] not in self.data_missions.keys():
                self.data_missions[mission['FID']] = {}
                self.data_missions[mission['FID']]['Active'] = [item['MissionID'] for item in mission['Active']]
                self.data_missions[mission['FID']]['Failed'] = [item['MissionID'] for item in mission['Failed']]
                self.data_missions[mission['FID']]['Complete'] = [item['MissionID'] for item in mission['Complete']]

    def process_missions_accepted(self, missions_accepted):
        if __name__ == '__main__':
            print('Missions Accepted:')
            print(*missions_accepted[:10], sep='\n')
        for mission in missions_accepted:
            if mission['Name'].startswith('Mission_Massacre'):
                if mission['FID'] not in self.data_missions.keys():
                    self.data_missions[mission['FID']] = {}
                    self.data_missions[mission['FID']]['Missions'] = {}
                if 'Missions' not in self.data_missions[mission['FID']].keys():
                    self.data_missions[mission['FID']]['Missions'] = {}
                self.data_missions[mission['FID']]['Missions'][mission['MissionID']] = {
                    'TargetFaction': mission['TargetFaction'],
                    'DestinationSystem': mission['DestinationSystem'],
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
            fid = mission['FID']
            missionID = mission['MissionID']
            if fid in self.data_missions.keys() and 'Missions' in self.data_missions[fid].keys() and missionID in self.data_missions[fid]['Missions'].keys():
                self.data_missions[fid]['Missions'][missionID]['Redirected'] = True

    def process_missions_completed(self, missions_completed):
        if __name__ == '__main__':
            print('Missions Completed:')
            print(*missions_completed[:10], sep='\n')
        for mission in missions_completed:
            fid = mission['FID']
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
            fid = mission['FID']
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
            fid = mission['FID']
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
                for missionID, mission in missions[fid]['Missions'].items():
                    if missionID in missions[fid]['Complete']:
                        continue
                    if missionID in missions[fid]['Failed']:
                        continue
                    if 'Expiry' in mission.keys() and now > mission['Expiry']:
                        continue
                    missions[fid]['Active'].append(missionID)

        self.data_missions_updated = missions.copy()

    def get_data_missions(self):
        return self.data_missions_updated.copy()

    def get_missions(self, fid):
        return self.get_data_missions()[fid]['Missions'].copy()
    
    def get_active_missions(self, fid):
        missions = {}
        if fid in self.get_data_missions().keys():
            if 'Missions' in self.get_data_missions()[fid].keys():
                for missionID in self.get_data_missions()[fid]['Active']:
                    missions[missionID] = self.get_data_missions()[fid]['Missions'][missionID]
        return missions
    
    def generate_info_active_missions(self, fid, now):
        missions = self.get_active_missions(fid)
        info = {}
        for missionID, mission in missions.items():
            info[missionID] = {
                'TargetFaction': mission.get('TargetFaction', None),
                'DestinationSystem': mission.get('DestinationSystem', None),
                'Faction': mission.get('Faction', None),
                'Wing': mission.get('Wing', None),
                'KillCount': mission.get('KillCount', None),
                'Reward': mission.get('Reward', None),
                'Expires': mission.get('Expiry', None),
            }
        redirected = [i for i, mission in enumerate(missions.values()) if mission.get('Redirected', False)]
        return info, redirected

    def get_data_active_missions(self, fid, now) -> tuple[list[list], list[int]]:
        missions, redirected = self.generate_info_active_missions(fid, now)
        df = pd.DataFrame(missions).T
        df['Expires'] = df['Expires'].apply(lambda x: naturaltime(x) if isinstance(x, datetime) else '')
        df['Reward'] = df['Reward'].apply(lambda x: f"{x:,}" if pd.notna(x) else '')
        df['Wing'] = df['Wing'].apply(lambda x: 'Yes' if x else 'No')
        return df.values.tolist(), redirected
    
    def generate_info_distribution(self, fid):
        missions = self.get_active_missions(fid)
        df = pd.DataFrame(missions).T
        if df.empty:
            return None
        distribution = df[['Faction', 'KillCount']].groupby('Faction').sum().reset_index()
        distribution = distribution.sort_values(by='KillCount', ascending=True).reset_index(drop=True)
        distribution.index += 1
        distribution['Difference'] = distribution['KillCount'].max() - distribution['KillCount']
        return distribution.values.tolist()
    
    def get_data_mission_stats(self, fid):
        missions = self.get_active_missions(fid)
        df = pd.DataFrame(missions).T
        if df.empty:
            return None
        df_redirected = df[df['Redirected'] == True]
        stats = {
            'TotalMissions': df.shape[0],
            'ActiveMissions': df.shape[0] - df_redirected.shape[0],
            'KillCount': df[['Faction', 'KillCount']].groupby('Faction').sum().max()['KillCount'],
            'KillRemaining': df[['Faction', 'KillCount']].groupby('Faction').sum().max()['KillCount'] - df_redirected[['Faction', 'KillCount']].groupby('Faction').sum().max()['KillCount'],
            'TotalKillCount': df['KillCount'].sum(),
            'KillRatio': f"{df['KillCount'].sum() / df[['Faction', 'KillCount']].groupby('Faction').sum().max()['KillCount']:.2f}",
            'TotalReward': f"{df['Reward'].sum():,}",
            'CurrentReward': f"{df_redirected['Reward'].sum():,}",
        }
        return list(stats.items())

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
            return active_journals
        elif active_journals is None:
            return unknown_fid_journals
        else:
            return active_journals + unknown_fid_journals
    
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
    print(pd.DataFrame(model.generate_info_active_missions('F11601975', datetime.now(timezone.utc))).T)
    print(pd.DataFrame(model.generate_info_distribution('F11601975')))
    print(pd.DataFrame(model.get_data_mission_stats('F11601975')))
    print(model.get_data_missions()['F11601975']['Complete'])
    