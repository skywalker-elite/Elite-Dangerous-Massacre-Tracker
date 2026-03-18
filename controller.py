import json
import os
import sys
import threading
import time
from typing import Callable, TYPE_CHECKING
import pyperclip
import re
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from webbrowser import open_new_tab
# from winotify import Notification TODO: for notification without popup
from datetime import datetime, timezone, timedelta, date
from os import makedirs, path, remove
from shutil import copyfile
from tkinter import Tk
import traceback
import tomllib
import pickle
import asyncio
import pandas as pd
from string import Template
from tkinter import Tk
# from pystray import Icon, Menu, MenuItem
from PIL import Image
from concurrent.futures import ThreadPoolExecutor
# from settings import Settings, SettingsValidationError
from model import MissionModel
from view import MissionView
from utility import getCurrentVersion, getLatestVersion, getPrereleaseUpdateVersion, getResourcePath, isOnPrerelease, isUpdateAvailable, getSettingsPath, getSettingsDefaultPath, getSettingsDir, getAppDir, getCachePath, open_file
# from decos import debounce
# from discord_handler import DiscordWebhookHandler
from config import UPDATE_INTERVAL, REDRAW_INTERVAL_FAST, REDRAW_INTERVAL_SLOW, REMIND_INTERVAL, SAVE_CACHE_INTERVAL

if TYPE_CHECKING: 
    import tksheet

class JournalEventHandler(FileSystemEventHandler):
    def __init__(self, controller: 'MissionController'):
        self.controller = controller
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.log'):
            self.controller._schedule_journal_update()
    on_created = on_modified

class MissionController:
    def __init__(self, root: Tk, model: MissionModel):
        self.root = root
        self.model = model
        self.tray_icon = None
        self.view = MissionView(root)
        self.active_fid: str | None = None
        # self.load_settings(getSettingsPath())

        self.view.dropdown_cmdr_var.trace_add('write', lambda *args: setattr(self, 'active_fid', self.model.get_cmdr_fid(self.view.dropdown_cmdr_var.get())))
        self.view.dropdown_cmdr_var.trace_add('write', lambda *args: self.redraw_slow())
        self.view.button_open_journal.configure(command=self.button_click_open_journal)
        self.view.button_check_updates.configure(command=lambda: self.check_app_update(notify_is_latest=True))
        # self.view.button_reload_settings.configure(command=self.button_click_reload_settings)
        # self.view.button_open_settings.configure(command=lambda: open_file(getSettingsPath()))
        # self.view.button_reset_settings.configure(command=self.button_click_reset_settings)
        # self.view.button_open_settings_dir.configure(command=lambda: open_file(getSettingsDir()))
        self.view.button_clear_cache.configure(command=self.button_click_clear_cache)
        self.view.button_go_to_github.configure(command=lambda: open_new_tab(url='https://github.com/skywalker-elite/Elite-Dangerous-Massacre-Tracker'))
        # self.view.checkbox_show_active_journals_var.trace_add('write', lambda *args: self.settings.set_config('UI', 'show_active_journals_tab', value=self.view.checkbox_show_active_journals_var.get()))

        # initial load
        self.update_journals()
        self.view.dropdown_cmdr['values'] = self.model.get_all_cmdr_names()
        self.view.dropdown_cmdr.current(0)

        self._observer = Observer()
        handler = JournalEventHandler(self)
        for jp in self.model.journal_paths:
            watch_dir = jp if os.path.isdir(jp) else os.path.dirname(jp)
            self._observer.schedule(handler, watch_dir, recursive=False)
        self._observer.daemon = True
        self._observer.start()

        self.set_current_version()
        self.redraw_fast()
        self.redraw_slow()
        self.view.update_table_active_journals(self.model.get_data_active_journals())
        self.check_app_update()
        self.minimize_hint_sent = False

        threading.Thread(target=self.save_cache, daemon=True).start()

        # self.save_window_size_on_resize()

    def _schedule_journal_update(self):
        # coalesce rapid events
        if getattr(self, '_journal_update_pending', False):
            return
        self._journal_update_pending = True
        threading.Thread(target=self._perform_journal_update, daemon=True).start()

    def _perform_journal_update(self):
        self.update_journals()
        self._journal_update_pending = False
        self.view.root.after(0, 
                             lambda: self.redraw_slow()
                             )

    def set_current_version(self):
        self.view.label_version.configure(text=getCurrentVersion())
    
    def check_app_update(self, notify_is_latest:bool=False):
        if isUpdateAvailable():
            if isOnPrerelease():
                version_latest = getPrereleaseUpdateVersion()
            else:
                version_latest = getLatestVersion()
            prompt = f'New version available: {version_latest}\nGo to download?'
            if self.view.show_message_box_askyesno('Update Available', prompt):
                if isOnPrerelease():
                    url = f'https://github.com/skywalker-elite/Elite-Dangerous-Massacre-Tracker/releases/tag/{version_latest}'
                else:
                    url = 'https://github.com/skywalker-elite/Elite-Dangerous-Massacre-Tracker/releases/latest'
                open_new_tab(url=url)
        elif notify_is_latest:
            version_current = getCurrentVersion()
            self.view.show_message_box_info('No update available', f'You are using the latest version: {version_current}')
    
    # def load_settings(self, settings_file:str):
    #     try:
    #         self.settings = Settings(settings_file=settings_file)
    #     except FileNotFoundError as e:
    #         if settings_file == getSettingsDefaultPath():
    #             raise e
    #         else:
    #             if self.view.show_message_box_askyesno('Settings file not found', 'Do you want to create a new settings file?'):
    #                 makedirs(getAppDir(), exist_ok=True)
    #                 copyfile(getSettingsDefaultPath(), settings_file)
    #                 if self.view.show_message_box_askyesno('Success!', 'Settings file created using default settings. \nDo you want to edit it now?'):
    #                     try:
    #                         open_file(settings_file)
    #                     except Exception as e:
    #                         self.view.show_message_box_warning('Error', f'Could not open settings file:\n{e}')
    #                     self.view.show_message_box_info_no_topmost('Waiting', 'Click OK when you are done editing and saved the file')
    #                 self.settings = Settings(settings_file=settings_file)
    #             else:
    #                 self.view.show_message_box_info('Settings', 'Using default settings')
    #                 self.settings = Settings(settings_file=getSettingsDefaultPath())
    #     except tomllib.TOMLDecodeError as e:
    #         if settings_file == getSettingsDefaultPath():
    #             raise e
    #         else:
    #             self.view.show_message_box_warning('Settings file corrupted', f'Using default settings\n{e}')
    #             self.settings = Settings(settings_file=getSettingsDefaultPath())
    #     except SettingsValidationError as e:
    #         if settings_file == getSettingsDefaultPath():
    #             raise e
    #         else:
    #             self.view.show_message_box_warning('Settings file validation failed', f'{e}\nUsing default settings')
    #             self.settings = Settings(settings_file=getSettingsDefaultPath())
    #     finally:
    #         if self.settings.validation_warnings:
    #             self.view.show_message_box_warning('Settings file warnings', f'{"\n".join(self.settings.validation_warnings)}')
    #         self.webhook_handler = DiscordWebhookHandler(self.settings.get('discord', 'webhook'), self.settings.get('discord', 'userID'))
    #         self.model.reset_ignore_list()
    #         self.model.reset_sfc_whitelist()
    #         self.model.add_sfc_whitelist(self.settings.get('squadron_carriers', 'whitelist'))
    #         self.model.add_ignore_list(self.settings.get('advanced', 'ignore_list'))
    #         self.model.set_custom_order(self.settings.get('advanced', 'custom_order'))
    #         self.model.set_squadron_abbv_mapping(self.settings.get('name_customization', 'squadron_abbv'))
    #         self.model.read_journals() # re-read journals to apply ignore list and custom order
    #         self.view.set_font_size(self.settings.get('font_size', 'UI'), self.settings.get('font_size', 'table'))
    #         self.root.geometry(self.settings.get('UI', 'window_size'))
    #         self.view.checkbox_show_active_journals_var.set(self.settings.get('UI', 'show_active_journals_tab'))
    #         self.view.checkbox_minimize_to_tray_var.set(self.settings.get('UI', 'minimize_to_tray'))
    #         self.setup_tray_icon()


    # def button_click_reload_settings(self):
    #     try:
    #         self.load_settings(getSettingsPath())
    #         self.view.show_message_box_info('Success!', 'Settings reloaded')
    #     except Exception as e:
    #         self.view.show_message_box_warning('Error', f'Error while reloading settings\n{traceback.format_exc()}')
    
    # def button_click_reset_settings(self):
    #     if self.view.show_message_box_askyesno('Reset settings', 'Do you want to reset the settings to default?'):
    #         try:
    #             copyfile(getSettingsDefaultPath(), getSettingsPath())
    #             self.load_settings(getSettingsPath())
    #             self.view.show_message_box_info('Success!', 'Settings reset to default')
    #         except Exception as e:
    #             self.view.show_message_box_warning('Error', f'Error while resetting settings\n{traceback.format_exc()}')
    
    def update_tables_fast(self, now):
        pass
        # with ThreadPoolExecutor(max_workers=4) as pool:
        #     fut_update_missions = pool.submit(self.model.update_data_missions, now)
        #     fut_get_active_missions = pool.submit(self.model.get_data_active_missions, self.active_fid, now)
        #     fut_get_faction_distribution = pool.submit(self.model.get_data_distribution, self.active_fid)
        #     fut_get_mission_stats = pool.submit(self.model.get_data_mission_stats, self.active_fid)
        #     fut_get_active_journals = pool.submit(self.model.get_data_active_journals)
        # fut_update_missions.result()
        # active_missions, rows_to_highlight, rows_turn_in = fut_get_active_missions.result()
        # faction_distribution = fut_get_faction_distribution.result()
        # mission_stats = fut_get_mission_stats.result()
        # active_journals = fut_get_active_journals.result()
        # self.view.root.after(0, self.view.update_table_missions, active_missions, rows_to_highlight, rows_turn_in)
        # self.view.root.after(0, self.view.update_table_faction_distribution, faction_distribution)
        # self.view.root.after(0, self.view.update_table_mission_stats, mission_stats)
        # self.view.root.after(0, self.view.update_table_active_journals, active_journals)

    def update_tables_slow(self, now):
        # self.model.update_data_missions(now)
        # active_missions, rows_to_highlight, rows_turn_in = self.model.get_data_active_missions(self.active_fid, now)
        # faction_distribution = self.model.get_data_distribution(self.active_fid)
        # mission_stats, mission_stats_rewards = self.model.get_data_mission_stats(self.active_fid)
        # active_journals = self.model.get_data_active_journals()
        # self.view.update_table_missions(active_missions, rows_to_highlight, rows_turn_in)
        # self.view.update_table_faction_distribution(faction_distribution)
        # self.view.update_table_mission_stats(mission_stats)
        # self.view.update_table_mission_stats_rewards(mission_stats_rewards)
        # self.view.update_table_active_journals(active_journals)
        with ThreadPoolExecutor(max_workers=5) as pool:
            fut_update_missions = pool.submit(self.model.update_data_missions, now)
            fut_get_active_missions = pool.submit(self.model.get_data_active_missions, self.active_fid, now)
            fut_get_faction_distribution = pool.submit(self.model.get_data_distribution, self.active_fid)
            fut_get_mission_stats = pool.submit(self.model.get_data_mission_stats, self.active_fid)
            fut_get_active_journals = pool.submit(self.model.get_data_active_journals)
        fut_update_missions.result()
        active_missions, rows_to_highlight, rows_turn_in = fut_get_active_missions.result()
        faction_distribution, rows_in_system = fut_get_faction_distribution.result()
        mission_stats, mission_stats_rewards = fut_get_mission_stats.result()
        active_journals = fut_get_active_journals.result()
        self.view.root.after(0, self.view.update_table_missions, active_missions, rows_to_highlight, rows_turn_in)
        self.view.root.after(0, self.view.update_table_faction_distribution, faction_distribution, rows_in_system)
        self.view.root.after(0, self.view.update_table_mission_stats, mission_stats)
        self.view.root.after(0, self.view.update_table_mission_stats_rewards, mission_stats_rewards)
        self.view.root.after(0, self.view.update_table_active_journals, active_journals)

    def update_time(self, now):
        self.view.update_time(now.strftime('%H:%M:%S'))
    
    def update_journals(self):
        try:
            self.model.read_journals()  # Re-read journals and update model's data
        except Exception as e:
            if self.view.show_message_box_askretrycancel('Error', f'An error occurred during journal update\n{traceback.format_exc()}'):
                self.view.root.after(UPDATE_INTERVAL, self.update_journals)
            else:
                self.view.root.destroy()

    def copy_to_clipboard(self, text: str, success_title: str|None, success_message: str|None, on_success: Callable[[], None]|None=None):
        try:
            pyperclip.copy(text)
        except pyperclip.PyperclipException as e:
            self.view.show_message_box_warning('Error', f'Error while copying to clipboard\n{e}')
        else:
            if success_title and success_message:
                self.view.show_message_box_info(success_title, success_message)
            if on_success:
                on_success()

    def button_click_open_journal(self):
        selected_row = self.get_selected_row(sheet=self.view.sheet_active_journals)
        if selected_row is not None:
            active_journal_paths = self.model.get_active_journal_paths()
            if not active_journal_paths:
                self.view.show_message_box_warning('Warning', 'No active journals found')
            else:
                journal_file = active_journal_paths[selected_row]
                open_file(journal_file)
        else:
            self.view.show_message_box_warning('Warning', 'Please select one row.')
    
    def redraw_fast(self):
        try:
            now = datetime.now(timezone.utc)
            self.update_tables_fast(now)
            self.update_time(now)
        except Exception as e:
            if self.view.show_message_box_askretrycancel('Error', f'An error occurred\n{traceback.format_exc()}'):
                self.view.root.after(REDRAW_INTERVAL_FAST, self.redraw_fast)
            else:
                self.view.root.destroy()
        else:
            self.view.root.after(REDRAW_INTERVAL_FAST, self.redraw_fast)
    
    def redraw_slow(self):
        try:
            now = datetime.now(timezone.utc)
            self.update_tables_slow(now)
        except Exception as e:
            if self.view.show_message_box_askretrycancel('Error', f'An error occurred\n{traceback.format_exc()}'):
                self.view.root.after(REDRAW_INTERVAL_SLOW, self.redraw_slow)
            else:
                self.view.root.destroy()
        else:
            self.view.root.after(REDRAW_INTERVAL_SLOW, self.redraw_slow)

    def get_selected_row(self, sheet=None, allow_multiple:bool=False) -> int|tuple[int]:
        if sheet is None:
            sheet = self.view.sheet_missions
        selected_rows = sheet.get_selected_rows(get_cells=False, get_cells_as_rows=True, return_tuple=True)
        if selected_rows:
            if allow_multiple:
                return selected_rows
            elif len(selected_rows) == 1:
                return selected_rows[0]
            else:
                return None
        else:
            return None
        
    def save_cache(self):
        cache_path = getCachePath(self.model.journal_reader.version, self.model.journal_reader.journal_paths)
        if cache_path is not None:
            makedirs(path.dirname(cache_path), exist_ok=True)
            try:
                self._save_cache(cache_path)
            except Exception as e:
                self.view.root.after(0, self.view.show_message_box_warning, 'Error', f'Error while saving cache\n{traceback.format_exc()}')
            else:
                self.view.root.after(SAVE_CACHE_INTERVAL, lambda: threading.Thread(target=self.save_cache, daemon=True).start())
        else:
            self.view.root.after(0, self.view.show_message_box_warning, 'Warning', 'Cache path is not set, cannot save cache')

    def _save_cache(self, cache_path:str):
        if cache_path is not None:
            makedirs(path.dirname(cache_path), exist_ok=True)
            with open(cache_path, 'wb') as f:
                pickle.dump(self.model.journal_reader, f)

    def button_click_clear_cache(self):
        cache_path = getCachePath(self.model.journal_reader.version, self.model.journal_reader.journal_paths)
        if cache_path is not None and path.exists(cache_path):
            try:
                remove(cache_path)
            except Exception as e:
                self.view.show_message_box_warning('Error', f'Error while clearing cache\n{traceback.format_exc()}')
            else:
                self.view.show_message_box_info('Success!', 'Cache cleared, EDMT will reload all journals now')
                self.reload()
        else:
            self.view.show_message_box_info('Info', 'No cache file found')

    def reload(self):
        progress_win, progress_bar = self.view.show_indeterminate_progress_bar('Reloading', 'Reloading all journals, this may take a while depending on the size of your journals')
        thread_reload = threading.Thread(target=self._reload, daemon=True)
        thread_reload.start()
        while thread_reload.is_alive():
            progress_win.update()
            time.sleep(0.0001)
        progress_win.destroy()
        self.save_cache()

    def _reload(self):
        self.model = MissionModel(journal_paths=self.model.journal_paths, journal_reader=None, dropout=self.model.dropout, droplist=self.model.droplist)
        # self.model.register_status_change_callback(self.status_change)
        self.model.read_journals()

    # def save_window_size_on_resize(self):
    #     self.root.bind('<Configure>', self._on_configure)

    # @debounce(10)
    # def _on_configure(self, event):
    #     print('Saving window size:', f'{self.root.winfo_width()}x{self.root.winfo_height()}')
    #     threading.Thread(target=self.settings.set_config, args=('UI', 'window_size'), kwargs={'value': f'{self.root.winfo_width()}x{self.root.winfo_height()}'}, daemon=True).start()