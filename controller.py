import json
import os
import sys
import threading
import time
from typing import Callable, TYPE_CHECKING
from realtime import PostgresChangesPayload, AsyncRealtimeClient, RealtimeSubscribeStates
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
from playsound3 import playsound
from tkinter import Tk
from pystray import Icon, Menu, MenuItem
from PIL import Image
from supabase import FunctionsHttpError
from concurrent.futures import ThreadPoolExecutor
# from settings import Settings, SettingsValidationError
from model import MissionModel
from view import MissionView
from utility import checkTimerFormat, getTimerStatDescription, getCurrentVersion, getLatestVersion, getLatestPrereleaseVersion, getResourcePath, isOnPrerelease, isUpdateAvailable, getSettingsPath, getSettingsDefaultPath, getSettingsDir, getAppDir, getCachePath, open_file, getInfoHash, getExpectedJumpTimer
# from decos import debounce
# from discord_handler import DiscordWebhookHandler
from config import UPDATE_INTERVAL, UPDATE_INTERVAL_TIMER_STATS, REDRAW_INTERVAL_FAST, REDRAW_INTERVAL_SLOW, REMIND_INTERVAL, SAVE_CACHE_INTERVAL

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
    def __init__(self, root:Tk, model:MissionModel):
        self.root = root
        self.model = model
        self.tray_icon = None
        self.view = MissionView(root)
        self.active_fid: str | None = 'F11601975'
        # self.load_settings(getSettingsPath())

        self.view.dropdown_cmdr_var.trace_add('write', lambda *args: setattr(self, 'active_fid', self.model.get_cmdr_fid(self.view.dropdown_cmdr_var.get())))
        self.view.button_open_journal.configure(command=self.button_click_open_journal)
        self.view.button_check_updates.configure(command=lambda: self.check_app_update(notify_is_latest=True))
        # self.view.button_reload_settings.configure(command=self.button_click_reload_settings)
        self.view.button_open_settings.configure(command=lambda: open_file(getSettingsPath()))
        # self.view.button_reset_settings.configure(command=self.button_click_reset_settings)
        self.view.button_open_settings_dir.configure(command=lambda: open_file(getSettingsDir()))
        # self.view.button_test_trade_post.configure(command=self.button_click_test_trade_post)
        # self.view.button_test_wine_unload.configure(command=self.button_click_test_wine_unload)
        # self.view.button_test_discord.configure(command=self.button_click_test_discord_webhook)
        # self.view.button_test_discord_ping.configure(command=self.button_click_test_discord_webhook_ping)
        self.view.button_clear_cache.configure(command=self.button_click_clear_cache)
        self.view.button_go_to_github.configure(command=lambda: open_new_tab(url='https://github.com/skywalker-elite/Elite-Dangerous-Carrier-Manager'))
        # self.view.checkbox_show_active_journals_var.trace_add('write', lambda *args: self.settings.set_config('UI', 'show_active_journals_tab', value=self.view.checkbox_show_active_journals_var.get()))
        # self.view.checkbox_minimize_to_tray_var.trace_add('write', lambda *args: self.settings.set_config('UI', 'minimize_to_tray', value=self.view.checkbox_minimize_to_tray_var.get()))
        # self.view.checkbox_minimize_to_tray.configure(command=lambda: self.setup_tray_icon())

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
        # self.redraw_slow()
        # self.update_timer_stat_loop()
        self.view.update_table_active_journals(self.model.get_data_active_journals())
        # self._start_realtime_listener()
        # self.check_app_update()
        self.minimize_hint_sent = False

        threading.Thread(target=self.save_cache, daemon=True).start()

        # if self.auth_handler.is_logged_in():
        #     self.on_sign_in(show_message=False)
        # else:
        #     self.on_sign_out(show_message=False)

        # self.auth_handler.register_auth_event_callback('SIGNED_IN', self.on_sign_in)
        # self.auth_handler.register_auth_event_callback('SIGNED_OUT', self.on_sign_out)

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
                             self.view.update_table_active_journals(self.model.get_data_active_journals())
                             )

    def set_current_version(self):
        self.view.label_version.configure(text=getCurrentVersion())
    
    def check_app_update(self, notify_is_latest:bool=False):
        if isUpdateAvailable():
            if isOnPrerelease():
                version_latest = getLatestPrereleaseVersion()
            else:
                version_latest = getLatestVersion()
            prompt = f'New version available: {version_latest}\nGo to download?'
            if self.view.show_message_box_askyesno('Update Available', prompt):
                if isOnPrerelease():
                    url = f'https://github.com/skywalker-elite/Elite-Dangerous-Carrier-Manager/releases/tag/{version_latest}'
                else:
                    url = 'https://github.com/skywalker-elite/Elite-Dangerous-Carrier-Manager/releases/latest'
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
        with ThreadPoolExecutor(max_workers=4) as pool:
            fut_update_missions = pool.submit(self.model.update_data_missions, now)
            fut_get_active_missions = pool.submit(self.model.get_data_active_missions, self.active_fid, now)
            fut_get_faction_distribution = pool.submit(self.model.get_data_distribution, self.active_fid)
            fut_get_mission_stats = pool.submit(self.model.get_data_mission_stats, self.active_fid)
            fut_get_active_journals = pool.submit(self.model.get_data_active_journals)
        fut_update_missions.result()
        active_missions, rows_to_highlight, rows_turn_in = fut_get_active_missions.result()
        faction_distribution = fut_get_faction_distribution.result()
        mission_stats = fut_get_mission_stats.result()
        active_journals = fut_get_active_journals.result()
        self.view.root.after(0, self.view.update_table_missions, active_missions, rows_to_highlight, rows_turn_in)
        self.view.root.after(0, self.view.update_table_faction_distribution, faction_distribution)
        self.view.root.after(0, self.view.update_table_mission_stats, mission_stats)
        self.view.root.after(0, self.view.update_table_active_journals, active_journals)

    # def update_tables_slow(self, now):
    #     with ThreadPoolExecutor(max_workers=4) as pool:
    #         fut_finance = pool.submit(self.model.get_data_finance)
    #         fut_trade = pool.submit(self.model.get_data_trade)
    #         fut_services = pool.submit(self.model.get_data_services)
    #         fut_misc = pool.submit(self.model.get_data_misc)
    #         fut_pending = pool.submit(self.model.get_rows_pending_decom)

    #     df_finance = fut_finance.result()
    #     df_trade, trade_pending = fut_trade.result()
    #     df_services = fut_services.result()
    #     df_misc = fut_misc.result()
    #     pending = fut_pending.result()

    #     self.view.update_table_finance(df_finance, pending)
    #     self.view.update_table_trade (df_trade, trade_pending)
    #     self.view.update_table_services(df_services, pending)
    #     self.view.update_table_misc   (df_misc, pending)

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

    # def button_click_post(self, trade_post_view: TradePostView, carrier_name:str, carrier_callsign:str, trade_type:str, commodity:str, system:str, amount:int|float):
    #     station = trade_post_view.cbox_stations.get()
    #     profit = trade_post_view.cbox_profit.get()
    #     pad_size = trade_post_view.cbox_pad_size.get()
    #     match pad_size:
    #         case 'L':
    #             pad_size = 'Large'
    #             pad_size_short = 'L'
    #         case 'M':
    #             pad_size = 'Medium'
    #             pad_size_short = 'M'
    #         case _:
    #             raise RuntimeError(f'Unexpected pad_size: {pad_size}')

    #     match trade_type:
    #         case 'loading':
    #             trade_type = 'load'
    #             trading_type = 'loading'
    #             demand_supply = 'demand'
    #             to_from = 'from'
    #         case 'unloading':
    #             trade_type = 'unload'
    #             trading_type = 'unloading'
    #             demand_supply = 'supply'
    #             to_from = 'to'
    #         case _:
    #             raise RuntimeError(f'Unexpected trade_type: {trade_type}')

    #     post_string = self.generate_trade_post_string(
    #         trade_type=trade_type,
    #         trading_type=trading_type,
    #         carrier_name=carrier_name,
    #         carrier_callsign=carrier_callsign,
    #         commodity=commodity,
    #         system=system,
    #         station=station,
    #         profit=profit,
    #         pad_size=pad_size,
    #         pad_size_short=pad_size_short,
    #         demand_supply=demand_supply,
    #         amount=amount,
    #         to_from=to_from
    #     )
    #     self.copy_to_clipboard(post_string, None, None, on_success=lambda: trade_post_view.popup.destroy())

    # def generate_trade_post_string(self, trade_type:str, trading_type:str, carrier_name:str, carrier_callsign:str, commodity:str, system:str, station:str, profit:str, pad_size:str, pad_size_short:str, demand_supply:str, amount:int|float, to_from:str) -> str:
    #     s = Template(self.settings.get('post_format', 'trade_post_string'))
    #     post_string = s.safe_substitute(
    #         trade_type=trade_type,
    #         trading_type=trading_type,
    #         carrier_name=carrier_name,
    #         carrier_callsign=carrier_callsign,
    #         commodity=commodity,
    #         system=system,
    #         station=station,
    #         profit=profit,
    #         pad_size=pad_size,
    #         pad_size_short=pad_size_short,
    #         demand_supply=demand_supply,
    #         amount=amount,
    #         to_from=to_from
    #     )
    #     return post_string

    # def generate_wine_unload_post_string(self, carrier_callsign:str, planetary_body:str, timed_unload:bool=False) -> str:
    #     if not timed_unload:
    #         s = Template(self.settings.get('post_format', 'wine_unload_string'))
    #         post_string = s.safe_substitute(carrier_callsign=carrier_callsign, planetary_body=planetary_body)
    #     else:
    #         s = Template(self.settings.get('post_format', 'wine_unload_timed_string'))
    #         post_string = s.safe_substitute(carrier_callsign=carrier_callsign, planetary_body=planetary_body)
    #     return post_string

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
    
    # def redraw_slow(self):
    #     try:
    #         now = datetime.now(timezone.utc)
    #         self.update_tables_slow(now)
    #     except Exception as e:
    #         if self.view.show_message_box_askretrycancel('Error', f'An error occurred\n{traceback.format_exc()}'):
    #             self.view.root.after(REDRAW_INTERVAL_SLOW, self.redraw_slow)
    #         else:
    #             self.view.root.destroy()
    #     else:
    #         self.view.root.after(REDRAW_INTERVAL_SLOW, self.redraw_slow)

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

    # def button_click_login(self):
    #     if not self.auth_handler.is_logged_in():
    #         threading.Thread(target=self.auth_handler.login, daemon=True).start()
    #     else:
    #         self.view.root.after(0, self.view.show_message_box_info, 'Info', f'Already logged in as {self.auth_handler.get_username()}')

    # def button_click_logout(self):
    #     if self.auth_handler.is_logged_in():
    #         if self.view.show_message_box_askyesno('Logout', f'Do you want to logout of {self.auth_handler.get_username()}?'):
    #             threading.Thread(target=self.auth_handler.logout, daemon=True).start()
    #     else:
    #         self.view.show_message_box_info('Info', 'Not logged in')

    # def button_click_verify_roles(self):
    #     in_ptn, roles = self.auth_handler.auth_PTN_roles()
    #     if in_ptn is None:
    #         self.view.show_message_box_warning('Error', 'Error while verifying roles, please try again later')
    #     elif not in_ptn:
    #         self.view.show_message_box_info('Not in PTN', 'You are not in the PTN Discord server, please make sure you are using the correct Discord account')
    #     elif not roles:
    #         self.view.show_message_box_info('Info', f'You are in the PTN, but have no elevated roles assigned.')
    #     else:
    #         roles_str = ', '.join(roles)
    #         self.view.show_message_box_info('Success!', f'You are in the PTN and have the following roles:\n {roles_str}')

    # def button_click_delete_account(self):
    #     if self.auth_handler.is_logged_in():
    #         if self.view.show_message_box_askyesno('Delete Account', 'Are you sure you want to delete your account?\n \
    #                                                 This action cannot be undone.'):
    #             if self.view.show_message_box_askyesno('Delete Account', 'This will also delete all your data, including all the jump timers you\'ve ever reported.\n \
    #                                                      Are you really sure you want to delete your account?'):
    #                 self.auth_handler.delete_account()
    #                 self.view.show_message_box_info('Success!', 'Your account and data has been deleted successfully')

    # def on_sign_out(self, show_message: bool=True):
    #     if show_message:
    #         self.view.show_message_box_info('Logged Out', 'You have been logged out')
    #     self.view.button_login.configure(text='Login with Discord')
    #     self.view.button_login.configure(command=lambda: threading.Thread(target=self.button_click_login, daemon=True).start())
    #     self.view.checkbox_enable_timer_reporting.configure(state='disabled')
    #     # self.view.checkbox_enable_timer_reporting_var.set(False)
    #     self.view.button_verify_roles.configure(state='disabled')
    #     self.view.button_delete_account.configure(state='disabled')
    #     self.view.button_report_timer_history.configure(state='disabled')

    # def on_sign_in(self, show_message: bool=True):
    #     if show_message:
    #         self.view.show_message_box_info('Logged In', f'You are now logged in as {self.auth_handler.get_username()}')
    #     self.view.button_login.configure(text=f'Logout of {self.auth_handler.get_username()}')
    #     self.view.button_login.configure(command=self.button_click_logout)
    #     self.view.checkbox_enable_timer_reporting.configure(state='normal')
    #     self.view.checkbox_enable_timer_reporting_var.set(self.settings.get('timer_reporting', 'enabled'))
    #     self.view.button_verify_roles.configure(state='normal')
    #     self.view.button_delete_account.configure(state='normal')
    #     self.view.button_report_timer_history.configure(state='normal')

    # def report_jump_timer(self, carrierID:int):
    #     if self.model.get_current_or_destination_system(carrierID) in ['HD 105341','HIP 58832']:
    #         print(f'Skipping jump timer report for N1 and N0')
    #         return
    #     if self.auth_handler.is_logged_in():
    #         jump_plot_timestamp = self.model.get_latest_jump_plot(carrierID)
    #         latest_departure_time = self.model.get_latest_departure(carrierID)
    #         payload = self.generate_timer_payload(carrierID, jump_plot_timestamp, latest_departure_time)
    #         # Report the jump timer to the server
    #         try:
    #             response = self.auth_handler.client.functions.invoke("submit-report", invoke_options={'body': payload})
    #             print('Report submitted successfully:', response.decode('utf-8'))
    #         except Exception as e:
    #             print(f"Error reporting jump timer: {e}")

    # def generate_timer_payload(self, carrierID:int, jump_plot_timestamp:datetime|None, latest_departure_time:datetime|None) -> dict:
    #     timer = self.model.get_jump_timer_in_seconds(jump_plot_timestamp, latest_departure_time)
    #     if timer is None:
    #         raise RuntimeError(f'Cannot generate timer payload, timer is None for {self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)})')
    #     payload = {
    #         "journal_timestamp": jump_plot_timestamp.isoformat(),
    #         "timer": timer,
    #         "info_hash": getInfoHash(journal_timestamp=jump_plot_timestamp, timer=timer, carrierID=carrierID)
    #     }
    #     return payload

    # def generate_timer_history(self) -> pd.DataFrame:
    #     payloads = []
    #     for carrierID in self.model.sorted_ids_display():
    #         jumps: pd.DataFrame = self.model.get_carriers()[carrierID]['jumps']
    #         for _, jump in jumps.iterrows():
    #             jump_plot_timestamp = jump['timestamp']
    #             departure_time = jump.get('DepartureTime', None)
    #             if departure_time is None:
    #                 continue
    #             payload = self.generate_timer_payload(carrierID, jump_plot_timestamp, departure_time)
    #             payloads.append(payload)
    #     df = pd.DataFrame(payloads, columns=['journal_timestamp', 'timer', 'info_hash'])
    #     return df

    # def report_timer_history(self) -> tuple[int|None, int|None, int|None]:
    #     if self.auth_handler.is_logged_in():
    #         df = self.generate_timer_history()
    #         if df.empty:
    #             return 0, None, None
    #         def _chunks(seq: list[dict[str, any]], size: int):
    #             for i in range(0, len(seq), size):
    #                 yield seq[i:i+size]
    #         totals = {"submitted": 0, "inserted": 0, "skipped": 0}
    #         for chunk in _chunks(df.to_dict(orient='records'), 500):
    #             response = self.auth_handler.client.functions.invoke("submit-bulk-report", invoke_options={'body': chunk})
    #             if type(response) is bytes:
    #                 response = json.loads(response.decode('utf-8'))
    #             if 'error' in response:
    #                 raise RuntimeError(f"Error reporting jump timer: {response.error}")
    #             if response.get('ok', None) is True:
    #                 totals['submitted'] += len(chunk)
    #                 totals['inserted'] += response.get('inserted', None)
    #                 totals['skipped'] += response.get('skipped', None)
    #             else:
    #                 print(f"Error reporting jump timer: {response}")
    #                 raise RuntimeError(f"Error reporting jump timer: {response}")
    #         return totals['submitted'], totals['inserted'], totals['skipped']
    #     return None, None, None

    # def button_click_report_timer_history(self):
    #     if not self.auth_handler.is_logged_in():
    #         return self.view.show_message_box_warning('Not logged in', 'You need to be logged in to report timer history')
    #     if not self.auth_handler.can_bulk_report():
    #         return self.view.show_message_box_warning(
    #             'Permission denied',
    #             'You need certain PTN roles to report jump timer history.\n'
    #             'Use "Verify PTN Roles" to refresh your roles if you recently got promoted.\n'
    #             'If you think you should have access, please contact the developer: Skywalker.'
    #         )
    #     if not self.view.show_message_box_askyesno(
    #         'Report timer history',
    #         'Caution: This will report every jump you have ever made (except the ignored carriers), do you want to continue?'
    #     ):
    #         return

    #     # spawn a background thread so the UI stays responsive
    #     thread_report_history = threading.Thread(target=self._run_report_timer_history, daemon=True)
    #     thread_report_history.start()

    # def _run_report_timer_history(self):
    #     try:
    #         submitted, inserted, skipped = self.report_timer_history()
    #         if submitted is None:
    #             box = 'warning'; title = 'Error'; msg = 'Error reporting jump timer history, please try again later'
    #         elif submitted > 0:
    #             box = 'info'; title = 'Success'; msg = f'Submitted {submitted} jump timers, {inserted} accepted, {skipped} skipped.'
    #         else:
    #             box = 'info'; title = 'No Data'; msg = 'No jump timers to report.'
    #     except FunctionsHttpError as e:
    #         if e.status == 429:
    #             box = 'warning'; title = 'Rate limited'; msg = 'You are being rate limited, please try again later'
    #         else:
    #             box = 'warning'; title = 'Error'; msg = f'Error reporting jump timer history\n{e.name} {e.status}: {e.message}'
    #     except Exception:
    #         box = 'warning'; title = 'Error'; msg = f'Error reporting jump timer history\n{traceback.format_exc()}'

    #     # back onto the Tk event loop to show the dialog
    #     self.view.root.after(0, lambda:
    #         getattr(self.view, f'show_message_box_{box}')(title, msg)
    #     )

    # def setup_tray_icon(self):
    #     if self.view.checkbox_minimize_to_tray_var.get():
    #         if sys.platform in ['win32', 'linux']:
    #             if self.tray_icon is None:
    #                 icon = Icon(
    #                     'Elite Dangerous Carrier Manager',
    #                     Image.open(getResourcePath(path.join('images','EDCM.png'))),
    #                     'EDCM',
    #                     Menu(
    #                         MenuItem('Show', self._on_show, default=True),
    #                         MenuItem('Quit', self._on_quit)
    #                     )
    #                 )
    #                 self.tray_icon = icon
    #                 if self.tray_icon.HAS_MENU:
    #                     threading.Thread(target=self.tray_icon.run, daemon=True).start()
    #                     self.root.bind('<Unmap>', lambda e: self._on_minimize() if self.root.state() == 'iconic' else None)
    #                 else:
    #                     self.view.show_message_box_warning('Error', 'System tray not supported on this system, minimize to tray disabled\n \
    #                                                     for more information, check the FAQ on the GitHub page.')
    #                     self.tray_icon = None
    #             else:
    #                 # tray icon already exists
    #                 pass
    #         else:
    #             self.view.show_message_box_warning('Error', 'System tray not supported on this system, minimize to tray disabled\n \
    #                                             for more information, check the FAQ on the GitHub page.')
    #             self.tray_icon = None
    #             self.view.checkbox_minimize_to_tray_var.set(False)
    #             self.view.checkbox_minimize_to_tray.config(state='disabled')
    #     else:
    #         if self.tray_icon is not None:
    #             self.tray_icon.stop()
    #             self.tray_icon = None
    #         self.root.unbind('<Unmap>')
    #         self.root.deiconify()

    # def _on_show(self, icon, item):
    #     self.root.after(0, self.root.deiconify)

    # def _on_quit(self, icon, item):
    #     icon.stop()
    #     self.root.after(0, self.root.destroy)

    # def _on_minimize(self):
    #     self._send_to_tray()

    # def _send_to_tray(self):
    #     if self.tray_icon.HAS_NOTIFICATION and not self.minimize_hint_sent:
    #         self.tray_icon.notify(
    #             'EDCM is still running. Click the tray icon to restore the window.',
    #             'EDCM Minimized to Tray'
    #         )
    #         self.minimize_hint_sent = True
    #     self.root.withdraw()

    # def save_window_size_on_resize(self):
    #     self.root.bind('<Configure>', self._on_configure)

    # @debounce(10)
    # def _on_configure(self, event):
    #     print('Saving window size:', f'{self.root.winfo_width()}x{self.root.winfo_height()}')
    #     threading.Thread(target=self.settings.set_config, args=('UI', 'window_size'), kwargs={'value': f'{self.root.winfo_width()}x{self.root.winfo_height()}'}, daemon=True).start()