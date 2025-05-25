import pandas as pd
from os import listdir, path
import re
import json
from datetime import datetime, timezone, timedelta
from humanize import naturaltime
from random import random
from utility import getHMS, getHammerCountdown, getResourcePath, getJournalPath
# from config import 

class JournalReader:
    def __init__(self, journal_path:str, dropout:bool=False):
        self.journal_path = journal_path
        self.journal_processed = []
        self.journal_latest = {}
        self.journal_latest_unknown_fid = {}
        self._load_games = []
        self._missions = []
        self._missions_accepted = []
        self._missions_completed = []
        self._missions_failed = []
        self._missions_abandoned = []
        self.items = []
        self.dropout = dropout
        if self.dropout:
            print('Dropout mode active, journal data is randomly dropped')
            self.droplist = [i for i in range(6) if random() < 0.5]
            for i in self.droplist:
                print(f'{["load_games", "missions", "missions_accepted", "missions_completed", "missions_failed", "missions_abandoned"][i]} was dropped')

    def read_journals(self):
        latest_journal_info = {}
        for key, value in zip(self.journal_latest.keys(), self.journal_latest.values()):
            latest_journal_info[value['filename']] = {'fid': key, 'line_pos': value['line_pos'], 'is_active': value['is_active']}
        files = listdir(self.journal_path)
        r = r'^Journal\.\d{4}-\d{2}-\d{2}T\d{6}\.\d{2}\.log$'
        journals = sorted([i for i in files if re.fullmatch(r, i)], reverse=False)
        assert len(journals) > 0, f'No journal files found in {self.journal_path}'
        for journal in journals:
            if journal not in self.journal_processed:
                self._read_journal(journal)
            elif journal in latest_journal_info.keys():
                if latest_journal_info[journal]['is_active']:
                    self._read_journal(journal, latest_journal_info[journal]['line_pos'], latest_journal_info[journal]['fid'])
            elif journal in self.journal_latest_unknown_fid.keys():
                self._read_journal(journal, self.journal_latest_unknown_fid[journal]['line_pos'])
        self.items = self._get_parsed_items()
        assert len(self.items[4]) > 0, 'No carrier found, if you do have a carrier, try logging in and opening the carrier management screen'
    
    def _read_journal(self, journal:str, line_pos:int|None=None, fid_last:str|None=None):
        # print(journal)
        items = []
        with open(path.join(self.journal_path, journal), 'r', encoding='utf-8') as f:
            lines = f.readlines()
            line_pos_new = len(lines)
            lines = lines[line_pos:]
            # if line_pos is not None:
            #     print(*lines, sep='\n')
            for i in lines:
                try:
                    items.append(json.loads(i))
                except json.decoder.JSONDecodeError as e: # ignore ill-formated entries
                    print(f'{journal} {e}')
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
                match = re.search(r'\d{4}-\d{2}-\d{2}T\d{6}', journal)
                if datetime.now() - datetime.strptime(match.group(0), '%Y-%m-%dT%H%M%S') < timedelta(hours=1): # allows one hour for fid to show up
                    self.journal_latest_unknown_fid[journal] = {'filename': journal, 'line_pos': line_pos_new, 'is_active': is_active}
                else:
                    self.journal_latest_unknown_fid.pop(journal, None)
            else:
                self.journal_latest_unknown_fid.pop(journal, None)
                self.journal_latest[fid] = {'filename': journal, 'line_pos': line_pos_new, 'is_active': is_active}
        else:
            self.journal_latest_unknown_fid.pop(journal, None)
            if fid is not None:
                self.journal_latest[fid] = {'filename': journal, 'line_pos': line_pos_new, 'is_active': is_active}
        if journal not in self.journal_processed:
            self.journal_processed.append(journal)


    def _parse_items(self, items:list) -> tuple[str, bool]:
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
        return [sorted(i, key=lambda x: datetime.strptime(x['timestamp'], '%Y-%m-%dT%H:%M:%SZ'), reverse=True) 
                for i in [self._load_games, self._missions, self._missions_accepted, self._missions_completed, self._missions_failed, self._missions_abandoned]]
    
    def get_items(self) -> list:
        self._last_items_count = {item_type: len(getattr(self, f'_{item_type}')) for item_type in ['load_games', 'missions', 'missions_accepted', 'missions_completed', 'missions_failed', 'missions_abandoned']}
        if self.dropout:
            items = self.items.copy()
            for i in self.droplist:
                items[i] = type(items[i])()
            return items
        return self.items.copy()
    
    def get_new_items(self) -> list:
        items = []
        for item_type in ['load_games', 'missions', 'missions_accepted', 'missions_completed', 'missions_failed', 'missions_abandoned']:
            items.append(getattr(self, f'_{item_type}')[self._last_items_count[item_type]:])
        self._last_items_count = {item_type: len(getattr(self, f'_{item_type}')) for item_type in ['load_games', 'missions', 'missions_accepted', 'missions_completed', 'missions_failed', 'missions_abandoned']}
        return items

class MissionModel:
    def __init__(self, journal_path:str, dropout:bool=False):
        self.journal_reader = JournalReader(journal_path, dropout=dropout)
        self.dropout = dropout
        self.missions = {}
        self.missions_updated = {}
        self.journal_path = journal_path
        self.read_journals()

    def read_journals(self):
        self.data_missions = {}
        self.journal_reader.read_journals()
        load_games, missions, missions_accepted, missions_completed, missions_failed, missions_abandoned = self.journal_reader.get_items()

        cmdr_names = {}
        for load_game in load_games:
            if load_game['FID'] not in cmdr_names.keys():
                cmdr_names[load_game['FID']] = load_game['Commander']
        
        for mission in missions:
            if mission['FID'] not in self.data_missions.keys():
                self.data_missions[mission['FID']] = {}
            self.data_missions[mission['FID']]['Active'] = mission['Active']
            self.data_missions[mission['FID']]['Failed'] = mission['Failed']
            self.data_missions[mission['FID']]['Complete'] = mission['Complete']

        
        for mission in missions_accepted:
            if mission['Name'].startswith('Mission_Massacre'):
                if mission['FID'] not in self.missions.keys():
                    self.missions[mission['FID']] = {}
                self.missions[mission['FID']][mission['MissionID']] = {
                    'TargetFaction': mission['TargetFaction'],
                    'DestinationSystem': mission['DestinationSystem'],
                    'Faction': mission['Faction'],
                    'KillCount': mission['KillCount'],
                    'Reward': mission['Reward'],
                    'Wing': mission['Wing'],
                    'Expiry': mission['Expiry'],
                }

        self.missions = self.missions.copy()

    def update_missions(self, now):
        missions = self.missions.copy()
        for missionID in missions.keys():
            pass
        self.missions_updated = missions.copy()

    def get_missions(self):
        return self.missions_updated.copy()
    
    def get_data(self, now):
        return [self.generateInfo(self.get_carriers()[carrierID], now) for carrierID in self.sorted_ids()]
    
    def generateInfo(self, fid, now):
        pass

if __name__ == '__main__':
    # journal_reader = JournalReader(getJournalPath())
    # journal_reader.read_journals()
    # print(*[i[:10] for i in journal_reader.get_items()], sep='\n\n')
    model = MissionModel(getJournalPath())
    print(pd.DataFrame(model.missions['F11601975']).T)
    print(model.data_missions)
    # now = datetime.now(timezone.utc)
    # model.update_carriers(now)
    # print(pd.DataFrame(model.get_data(now), columns=[
    #         'Carrier Name', 'Carrier ID', 'Fuel', 'Current System', 'Body',
    #         'Status', 'Destination System', 'Body', 'Timer'
    #     ]))
    