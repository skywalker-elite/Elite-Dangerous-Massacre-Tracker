import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from model import JournalReader


class JournalReaderTests(unittest.TestCase):
    EVENT_TYPES = (
        'LoadGame', 'Missions', 'MissionAccepted', 'MissionRedirected',
        'MissionCompleted', 'MissionFailed', 'MissionAbandoned',
        'Docked', 'Undocked', 'FSDJump',
    )

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.journal_path = Path(directory.name) / 'Journal.2025-04-11T022443.01.log'
        self.reader = JournalReader([directory.name])
        self.append_events({
            'event': 'Commander', 'FID': 'F123',
            'timestamp': '2025-04-11T02:24:43Z',
        })

    def append_events(self, *events):
        with self.journal_path.open('a', encoding='utf-8') as journal:
            for event in events:
                journal.write(json.dumps(event) + '\n')

    def mission_event(self, timestamp):
        return {'event': 'MissionAccepted', 'MissionID': 123, 'timestamp': timestamp, 'FID': 'F123'}

    def test_full_results_preserve_order_and_references(self):
        for timestamp in ('2025-04-11T02:24:44Z', '2025-04-11T02:24:45Z'):
            self.append_events(*(
                {'event': event_type, 'timestamp': timestamp, 'MissionID': 123}
                for event_type in self.EVENT_TYPES
            ))
        self.reader.read_journals()

        items = self.reader.get_items()

        self.assertEqual(len(items), len(self.EVENT_TYPES))
        for index, event_type in enumerate(self.EVENT_TYPES):
            with self.subTest(event_type=event_type):
                self.assertEqual([event['event'] for event in items[index]],
                                 [event_type, event_type])
                self.assertEqual([event['timestamp'] for event in items[index]],
                                 ['2025-04-11T02:24:45Z', '2025-04-11T02:24:44Z'])
                stored = getattr(self.reader, '_' + self.reader.tracked_items[index])
                self.assertIs(items[index][0], stored[1])
                self.assertIs(items[index][1], stored[0])
                self.assertIsNot(items[index], stored)

    def test_full_results_include_appended_events(self):
        older = self.mission_event('2025-04-11T02:24:44Z')
        newer = self.mission_event('2025-04-11T02:24:45Z')
        self.append_events(older)
        self.reader.read_journals()
        previous = self.reader.get_items()

        self.append_events(newer)
        self.reader.read_journals()
        self.assertEqual(self.reader.get_items()[2], [newer, older])
        self.assertEqual(previous[2], [older])
        self.reader.read_journals()
        self.assertEqual(self.reader.get_items()[2], [newer, older])

    def test_full_results_do_not_disrupt_incremental_reads(self):
        self.append_events(self.mission_event('2025-04-11T02:24:44Z'),
                           self.mission_event('2025-04-11T02:24:45Z'))
        self.reader.read_journals()
        self.reader.get_items()
        self.reader.update_items_count()

        newer = self.mission_event('2025-04-11T02:24:46Z')
        self.append_events(newer)
        self.reader.read_journals()
        self.reader.get_items()
        items = self.reader.get_new_items()
        self.assertEqual(items[2], [newer])
        self.assertTrue(all(not group for index, group in enumerate(items)
                            if index != 2))
        self.reader.update_items_count()
        self.assertTrue(all(not group for group in self.reader.get_new_items()))

    def test_dropout_does_not_modify_stored_data(self):
        reader = JournalReader(self.reader.journal_paths, dropout=True,
                               droplist=['missions_accepted', 'missions_redirected'])
        mission = self.mission_event('2025-04-11T02:24:44Z')
        load_game = {'event': 'LoadGame', 'timestamp': '2025-04-11T02:24:44Z'}
        self.append_events(mission, load_game)
        reader.read_journals()

        items = reader.get_items()
        self.assertEqual(items[2], [])
        self.assertEqual(items[3], [])
        self.assertEqual(items[0], [load_game])
        self.assertEqual(reader._missions_accepted, [mission])
        reader.update_items_count()
        self.assertTrue(all(not group for group in reader.get_new_items()))
        reader.dropout = False
        self.assertEqual(reader.get_items()[2], [mission])

    def test_missions_are_not_duplicated_on_repeated_reads(self):
        self.append_events(self.mission_event('2025-04-11T02:24:44Z'))
        self.reader.read_journals()
        self.reader.read_journals()
        self.assertEqual(len(self.reader.get_items()[2]), 1)


if __name__ == '__main__':
    unittest.main()
