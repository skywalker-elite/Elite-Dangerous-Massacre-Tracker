from sys import platform

APP_NAME = "Elite Dangerous Massacre Tracker"

WINDOW_SIZE = "1080x600"
WINDOW_SIZE_TIMER = "300x120"
COMPACT_SHEET_AUTO_WIDTH_PADDING = 5
COMPACT_SHEET_AUTO_HEIGHT_PADDING = 4
MISSIONS_SUMMARY_FRAME_PADDING = 8
MISSIONS_SPLITTER_TOP_MARGIN = 48
MISSIONS_SPLITTER_BOTTOM_MARGIN = 48

UPDATE_INTERVAL = 500
UPDATE_INTERVAL_TIMER_STATS = 1000 * 30  # 30 seconds
REDRAW_INTERVAL_FAST = 200
REDRAW_INTERVAL_SLOW = 1000 * 60  # 1 minute
REMIND_INTERVAL = 500
SAVE_CACHE_INTERVAL = 1000 * 60 * 5  # 5 minutes

MISSION_CUTOFF = 21 # 21 days, cutoff for missions to process

font_sizes = {
    'tiny': 7 if platform != 'darwin' else 9,
    'small': 9 if platform != 'darwin' else 11,
    'normal': 11 if platform != 'darwin' else 13,
    'large': 13 if platform != 'darwin' else 15,
    'huge': 15 if platform != 'darwin' else 17,
    'giant': 17 if platform != 'darwin' else 19,
    'colossal': 19 if platform != 'darwin' else 21,
    'capital class signature detected': 21 if platform != 'darwin' else 23,
}

