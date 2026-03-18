import tkinter as tk
from tkinter import ttk
from tksheet import Sheet
from typing import Literal
import tkinter.font as tkfont
from popups import show_message_box_info, show_message_box_warning, show_message_box_info_no_topmost, show_non_blocking_info, show_message_box_askyesno, show_message_box_askretrycancel, show_indeterminate_progress_bar, center_window_relative_to_parent, apply_theme_to_titlebar
from config import WINDOW_SIZE_TIMER, COMPACT_SHEET_AUTO_HEIGHT_PADDING, COMPACT_SHEET_AUTO_WIDTH_PADDING, MISSIONS_SPLITTER_BOTTOM_MARGIN, MISSIONS_SUMMARY_FRAME_PADDING, font_sizes

class MissionView:
    def __init__(self, root: tk.Tk, window_size:str|None=None):
        self.root = root

        style = ttk.Style(self.root)
        # Removing the focus border around tabs
        style.layout("Tab",
                    [('Notebook.tab', {'sticky': 'nswe', 'children':
                        [('Notebook.padding', {'side': 'top', 'sticky': 'nswe', 'children':
                            #[('Notebook.focus', {'side': 'top', 'sticky': 'nswe', 'children':
                                [('Notebook.label', {'side': 'top', 'sticky': ''})],
                            #})],
                        })],
                    })]
                    )

        self.sheet_colors = {
            'table_bg':    '#1c1c1e',  # main window surface
            'header_bg':   "#202021",  # secondary surface
            'header_fg':   '#f3f3f5',  # light text
            'index_bg':    '#202021',  # secondary surface
            'index_fg':    "#C2C2C4",  # dim light text
            'top_left_bg':  '#202021',  # secondary surface
            'cell_bg':     '#1c1c1e',  # main window surface
            'cell_fg':     '#f3f3f5',  # light text
            'selected_bg': '#0a84ff',  # Fluent accent blue
            'selected_fg': '#ffffff',  # white text on selection
        }
        if window_size is not None:
            self.root.geometry(window_size)

        style = ttk.Style()
        style.element_create('Danger.TButton', 'from', 'sun-valley-dark', 'Button.TButton')
        style.layout('Danger.TButton', style.layout('Button.TButton'))
        style.configure('Danger.TButton', foreground='red')

        # TopBar
        self.top_bar = ttk.Frame(self.root)
        self.top_bar.pack(side='top', fill='x')
        
        # Clock
        self.clock_utc = ttk.Label(self.top_bar, width=8)
        self.clock_utc.pack(side='right', anchor='ne')

        # Version
        self.label_version = ttk.Label(self.top_bar)
        self.label_version.pack(side='left', anchor='nw', padx=10)

        self.tab_controler = ttk.Notebook(root)
        self.tab_missions = ttk.Frame(self.tab_controler)
        # self.tab_stats = ttk.Frame(self.tab_controler)
        self.tab_options = ScrollableFrame(self.tab_controler)
        self.tab_active_journals = ttk.Frame(self.tab_controler)

        self.tab_controler.add(self.tab_missions, text='Missions')
        # self.tab_controler.add(self.tab_stats, text='Statistics')
        self.tab_controler.add(self.tab_active_journals, text='Active Journals', state='hidden')
        self.tab_controler.add(self.tab_options, text='Options')

        # Make the grid expand when the window is resized
        def configure_tab_grid(tab):
            tab.rowconfigure(0, pad=1, weight=1)
            tab.columnconfigure(0, pad=1, weight=1)

        for tab in [self.tab_missions, self.tab_active_journals, self.tab_options]:
            configure_tab_grid(tab)

        self.tab_controler.pack(expand=True, fill='both')

        self.missions_split_user_positioned = False
        self.missions_sash_fit_pending = False
        self.last_missions_sash_pos: int | None = None
        self.missions_sash_dragging = False
        self.missions_sash_drag_offset = 0
        self.missions_sash_drag_start_pos: int | None = None
        self.auto_width_sheets: list[Sheet] = []

        self.tab_missions.rowconfigure(0, weight=1)
        self.tab_missions.rowconfigure(1, weight=0)

        self.paned_missions = ttk.Panedwindow(self.tab_missions, orient='vertical')
        self.paned_missions.grid(row=0, column=0, sticky='nswe')
        self.paned_missions.bind('<Configure>', self.on_missions_paned_configure)
        self.paned_missions.bind('<ButtonPress-1>', self.on_missions_sash_pressed)
        self.paned_missions.bind('<B1-Motion>', self.on_missions_sash_dragged)
        self.paned_missions.bind('<ButtonRelease-1>', self.on_missions_sash_released)

        self.frame_missions_top = ttk.Frame(self.paned_missions, padding=5)
        self.frame_missions_top.rowconfigure(0, weight=1)
        self.frame_missions_top.columnconfigure(0, weight=1)

        self.frame_below_missions = ScrollableFrame(self.paned_missions, padding=5)
        self.frame_below_missions_content = ttk.Frame(self.frame_below_missions.scrollable_frame)
        self.frame_below_missions_content.pack(anchor='nw')

        self.paned_missions.add(self.frame_missions_top, weight=1)
        self.paned_missions.add(self.frame_below_missions, weight=0)

        # Initialize the tksheet.Sheet widget
        self.sheet_missions = Sheet(self.frame_missions_top, name='sheet_missions', empty_horizontal=0, empty_vertical=0)

        # Set column headers
        self.sheet_missions.headers([
            'TargetFaction', 'TargetSystem', 'System', 'Station', 'Faction', 'Wing', 'KillCount', 'Reward', 'Expires'
        ])

        self.sheet_missions.grid(row=0, column=0, sticky='nswe')
        self.configure_sheet(self.sheet_missions)
        self.sheet_missions['G:H'].align('right', redraw=False)

        self.sheet_faction_distribution = Sheet(self.frame_below_missions_content, name='sheet_faction_distribution', empty_horizontal=0, empty_vertical=0)
        self.sheet_faction_distribution.headers(['Faction', 'KillCount', 'Diff', 'LowestReward'])
        self.sheet_faction_distribution.hide('top_left')
        self.sheet_faction_distribution.hide('row_index')
        self.configure_sheet(self.sheet_faction_distribution)
        self.sheet_faction_distribution['B:D'].align('right', redraw=False)
        self.hide_sheet_scrollbars(self.sheet_faction_distribution)
        self.sheet_faction_distribution.grid(row=0, column=0, sticky='n', padx=5, pady=5)

        self.separator_stats_1 = ttk.Separator(self.frame_below_missions_content, orient='vertical')
        self.separator_stats_1.grid(row=0, column=1, sticky='ns', padx=5, pady=5)

        self.sheet_mission_stats = Sheet(self.frame_below_missions_content, name='sheet_mission_stats', empty_horizontal=0, empty_vertical=0)
        self.sheet_mission_stats.hide('header')
        self.sheet_mission_stats.hide('top_left')
        self.sheet_mission_stats.hide('row_index')
        self.configure_sheet(self.sheet_mission_stats)
        self.sheet_mission_stats['B'].align('right', redraw=False)
        self.hide_sheet_scrollbars(self.sheet_mission_stats)
        self.sheet_mission_stats.grid(row=0, column=2, sticky='n', padx=5, pady=5)

        self.separator_stats_2 = ttk.Separator(self.frame_below_missions_content, orient='vertical')
        self.separator_stats_2.grid(row=0, column=3, sticky='ns', padx=5, pady=5)

        self.sheet_mission_stats_rewards = Sheet(self.frame_below_missions_content, name='sheet_mission_stats_rewards', empty_horizontal=0, empty_vertical=0)
        self.sheet_mission_stats_rewards.hide('header')
        self.sheet_mission_stats_rewards.hide('top_left')
        self.sheet_mission_stats_rewards.hide('row_index')
        self.configure_sheet(self.sheet_mission_stats_rewards)
        self.sheet_mission_stats_rewards['B'].align('right', redraw=False)
        self.hide_sheet_scrollbars(self.sheet_mission_stats_rewards)
        self.sheet_mission_stats_rewards.grid(row=0, column=4, sticky='n', padx=5, pady=5)
        self.auto_width_sheets = [
            self.sheet_faction_distribution,
            self.sheet_mission_stats,
            self.sheet_mission_stats_rewards,
        ]
        self.frame_below_missions.bind_mousewheel_recursive()

        self.bottom_bar = ttk.Frame(self.tab_missions)
        self.bottom_bar.grid(row=1, column=0, sticky='ew')

        self.label_cmdr_location = ttk.Label(self.bottom_bar, text='CMDR Location: Unknown')
        self.label_cmdr_location.pack(side='left', padx=5, pady=5)
        
        self.dropdown_cmdr_var = tk.StringVar()
        self.dropdown_cmdr = ttk.Combobox(self.bottom_bar, textvariable=self.dropdown_cmdr_var, state='readonly')
        self.dropdown_cmdr.pack(side='right', padx=5, pady=5)
        def on_cmdr_selected(e):
            self.dropdown_cmdr.selection_clear()
            self.sheet_missions.focus_set()
        self.dropdown_cmdr.bind("<<ComboboxSelected>>", lambda e: on_cmdr_selected(e))
        # # Buttons
        # # Post trade
        # self.button_post_trade = ttk.Button(self.bottom_bar, text='Post Trade')
        # # self.button_post_trade.grid(row=0, column=0, sticky='sw')
        # self.button_post_trade.pack(side='left')
        # # Hammertime
        # self.button_get_hammer = ttk.Button(self.bottom_bar, text='Get Hammer Time')
        # # self.button_get_hammer.grid(row=0, column=1, sticky='s')
        # self.button_get_hammer.pack(side='left')
        # # Manual timer
        # self.button_manual_timer = ttk.Button(self.bottom_bar, text='Enter Swap Timer')
        # self.button_manual_timer.pack(side='left')
        # # Clear timer
        # self.button_clear_timer = ttk.Button(self.bottom_bar, text='Clear Timer')
        # self.button_clear_timer.pack(side='left')
        # # Departure notice
        # self.button_post_departure = ttk.Button(self.bottom_bar, text='Post Departure')
        # self.button_post_departure.pack(side='left')

        # Options tab
        self.labelframe_EDMT = ttk.Labelframe(self.tab_options.scrollable_frame, text='EDMT')
        self.labelframe_EDMT.grid(row=0, column=0, padx=10, pady=10, sticky='w')
        self.button_check_updates = ttk.Button(self.labelframe_EDMT, text='Check for Updates')
        self.button_check_updates.pack(side='left', padx=10, pady=10, anchor='w')
        self.button_go_to_github = ttk.Button(self.labelframe_EDMT, text='Go to GitHub Repo')
        self.button_go_to_github.pack(side='left', padx=10, pady=10, anchor='w')
        self.button_clear_cache = ttk.Button(self.labelframe_EDMT, text='Clear Cache and Reload')
        self.button_clear_cache.pack(side='left', padx=10, pady=10, anchor='w')
        self.checkbox_show_active_journals_var = tk.BooleanVar()
        self.checkbox_show_active_journals_var.trace_add('write', lambda *args: self.toggle_active_journals_tab())
        self.checkbox_show_active_journals = ttk.Checkbutton(
            self.labelframe_EDMT,
            text='Show Active Journals Tab',
            variable=self.checkbox_show_active_journals_var,
        )
        self.checkbox_show_active_journals.pack(side='left', padx=10, pady=10, anchor='w')

        # self.labelframe_settings = ttk.Labelframe(self.tab_options.scrollable_frame, text='Settings')
        # self.labelframe_settings.grid(row=2, column=0, padx=10, pady=10, sticky='w')
        # self.button_reload_settings = ttk.Button(self.labelframe_settings, text='Reload Settings File')
        # self.button_reload_settings.pack(side='left', padx=10, pady=10, anchor='w')
        # self.button_open_settings = ttk.Button(self.labelframe_settings, text='Open Settings File')
        # self.button_open_settings.pack(side='left', padx=10, pady=10, anchor='w')
        # self.button_open_settings_dir = ttk.Button(self.labelframe_settings, text='Open Settings Directory')
        # self.button_open_settings_dir.pack(side='left', padx=10, pady=10, anchor='w')
        # self.button_reset_settings = ttk.Button(self.labelframe_settings, text='Reset Settings to Defaults', style='Danger.TButton')
        # self.button_reset_settings.pack(side='left', padx=10, pady=10, anchor='w')

        # Active Journals tab
        self.sheet_active_journals = Sheet(self.tab_active_journals, name='sheet_active_journals')
        self.sheet_active_journals.grid(row=0, column=0, columnspan=3, sticky='nswe')

        # Set column headers
        self.sheet_active_journals.headers(['FID', 'CMDR Name', 'Journal File'])
        
        self.configure_sheet(self.sheet_active_journals)

        self.bottom_bar_active_journals = ttk.Frame(self.tab_active_journals)
        self.bottom_bar_active_journals.grid(row=1, column=0, columnspan=3, sticky='ew')
        self.tab_active_journals.grid_rowconfigure(1, weight=0)
        # Buttons
        self.button_open_journal = ttk.Button(self.bottom_bar_active_journals, text='Open Journal File')
        self.button_open_journal.pack(side='left')

    def configure_sheet(self, sheet:Sheet):
        sheet.change_theme('dark', redraw=False)
        sheet.set_options(**self.sheet_colors)
        # Enable column resizing to match window resizing
        sheet.enable_bindings('single_select', 'drag_select', 'column_select', 'row_select', 'arrowkeys', 'copy', 'find', 'ctrl_click_select', 'right_click_popup_menu', 'rc_select')
        sheet.column_width_resize_enabled = False
        sheet.row_height_resize_enabled = False

    def hide_sheet_scrollbars(self, sheet: Sheet):
        sheet.hide('x_scrollbar')
        sheet.hide('y_scrollbar')

    def set_font_size(self, font_size:str, font_size_table:str):
        size = font_sizes.get(font_size, font_sizes['normal'])
        size_table = font_sizes.get(font_size_table, font_sizes['normal'])

        # 1) resize all tksheets
        for sheet in [self.sheet_missions, self.sheet_faction_distribution, self.sheet_active_journals, self.sheet_mission_stats, self.sheet_mission_stats_rewards]:
            sheet.font(('Calibri', size_table, 'normal'))
            sheet.header_font(('Calibri', size_table, 'normal'))
            sheet.set_all_column_widths()
            if sheet in self.auto_width_sheets:
                sheet.set_all_row_heights(redraw=False)
                self.fit_sheet_to_content(sheet)
        self.schedule_missions_summary_pane_fit()

        # 2) resize all Tk widgets via named‐fonts
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            f = tkfont.nametofont(name)
            f.configure(size=size)

        # 3) resize all ttk widgets via style
        style = ttk.Style(self.root)
        # catch everything that uses the “.” fallback
        style.configure(".", font=("Calibri", size, "normal"))
        # explicitly re-configure the most common widget styles
        for cls in (
            "TButton", "TLabel", "TEntry", "TCombobox",
            "TNotebook.Tab", "TLabelframe.Label", "TLabelframe"
        ):
            style.configure(cls, font=("Calibri", size, "normal"))

        # 4) global default for any new tk/ttk widget
        self.root.option_add("*Font", ("Calibri", size, "normal"))

        # 5) some pure-tk popups (Combobox listbox, Menu) still need an option_add
        self.root.option_add("*Listbox*Font", ("Calibri", size, "normal"))
        self.root.option_add("*Menu*Font",    ("Calibri", size, "normal"))

    def update_table(self, table:Sheet, data, highlight_rows:dict[str, int]|None=None):
        table.set_sheet_data(data, reset_col_positions=False)
        table.dehighlight_all(redraw=False)
        if highlight_rows is not None:
            for color, rows in highlight_rows.items():
                table.highlight_rows(rows, fg=color, redraw=False)
        table.set_all_column_widths()
        if table in self.auto_width_sheets:
            table.set_all_row_heights(redraw=False)
            self.fit_sheet_to_content(table)
            self.schedule_missions_summary_pane_fit()

    def get_sheet_content_width(self, sheet: Sheet) -> int:
        width = sum(int(column_width) for column_width in sheet.get_column_widths())
        if sheet.MT.show_index:
            width += int(sheet.RI.current_width)
        if sheet.yscroll_showing:
            width += int(sheet.yscroll.winfo_width() or sheet.yscroll.winfo_reqwidth())
        return width + COMPACT_SHEET_AUTO_WIDTH_PADDING

    def get_sheet_content_height(self, sheet: Sheet) -> int:
        row_heights = [int(row_height) for row_height in sheet.get_row_heights()]
        height = sum(row_heights) if row_heights else int(sheet.MT.get_default_row_height())
        if sheet.MT.show_header:
            height += int(sheet.CH.current_height)
        if sheet.xscroll_showing:
            height += int(sheet.xscroll.winfo_height() or sheet.xscroll.winfo_reqheight())
        return height + COMPACT_SHEET_AUTO_HEIGHT_PADDING

    def fit_sheet_to_content(self, sheet: Sheet):
        sheet.update_idletasks()
        width = self.get_sheet_content_width(sheet)
        height = self.get_sheet_content_height(sheet)
        if width <= 0 or height <= 0:
            return
        sheet.height_and_width(width=width, height=height)
        sheet.update_idletasks()

        # Scrollbars can appear or disappear after the first size pass, so recalculate once.
        adjusted_width = self.get_sheet_content_width(sheet)
        adjusted_height = self.get_sheet_content_height(sheet)
        if adjusted_width > 0 and adjusted_height > 0 and (adjusted_width != width or adjusted_height != height):
            sheet.height_and_width(width=adjusted_width, height=adjusted_height)

    def schedule_missions_summary_pane_fit(self, force: bool = False):
        if self.missions_sash_fit_pending:
            return
        self.missions_sash_fit_pending = True
        self.root.after_idle(lambda: self.fit_missions_summary_pane(force=force))

    def get_missions_summary_min_height(self) -> int:
        self.frame_below_missions_content.update_idletasks()
        required_content_height = int(self.frame_below_missions_content.winfo_reqheight())
        if required_content_height <= 0:
            return 0
        return required_content_height + self.frame_below_missions.get_vertical_padding() + MISSIONS_SUMMARY_FRAME_PADDING

    def get_missions_sash_size(self) -> int:
        if len(self.paned_missions.panes()) < 2:
            return 0
        self.paned_missions.update_idletasks()
        sash_position = int(self.paned_missions.sashpos(0))
        bottom_y = int(self.frame_below_missions.winfo_y())
        if bottom_y > sash_position:
            return bottom_y - sash_position

        total_height = int(self.paned_missions.winfo_height())
        bottom_height = int(self.frame_below_missions.winfo_height())
        return max(0, total_height - sash_position - bottom_height)

    def clamp_missions_sash_position(self, preferred_position: int | None = None) -> int | None:
        self.paned_missions.update_idletasks()
        if len(self.paned_missions.panes()) < 2:
            return None

        total_height = int(self.paned_missions.winfo_height())
        sash_size = self.get_missions_sash_size()
        if total_height <= 1:
            return None

        min_sash_position = max(
            0,
            total_height - sash_size - self.get_missions_summary_min_height(),
        )
        max_sash_position = max(
            min_sash_position,
            total_height - sash_size - MISSIONS_SPLITTER_BOTTOM_MARGIN,
        )
        if preferred_position is None:
            preferred_position = int(self.paned_missions.sashpos(0))
        clamped_position = max(min_sash_position, min(int(preferred_position), max_sash_position))
        if clamped_position != int(self.paned_missions.sashpos(0)):
            self.paned_missions.sashpos(0, clamped_position)
        self.last_missions_sash_pos = int(self.paned_missions.sashpos(0))
        return self.last_missions_sash_pos

    def fit_missions_summary_pane(self, force: bool = False):
        self.missions_sash_fit_pending = False
        if self.missions_split_user_positioned and not force:
            self.clamp_missions_sash_position()
            return
        min_bottom_height = self.get_missions_summary_min_height()
        total_height = int(self.paned_missions.winfo_height())
        if min_bottom_height <= 0 or total_height <= 1:
            return
        self.clamp_missions_sash_position(
            preferred_position=total_height - self.get_missions_sash_size() - min_bottom_height
        )

    def on_missions_sash_pressed(self, event: tk.Event):
        if self.paned_missions.identify(event.x, event.y) not in ('0', 0):
            return None
        self.missions_sash_dragging = True
        self.missions_sash_drag_start_pos = int(self.paned_missions.sashpos(0))
        self.missions_sash_drag_offset = event.y - self.missions_sash_drag_start_pos
        return 'break'

    def on_missions_sash_dragged(self, _event: tk.Event):
        if not self.missions_sash_dragging:
            return None
        desired_position = _event.y - self.missions_sash_drag_offset
        self.clamp_missions_sash_position(preferred_position=desired_position)
        return 'break'

    def on_missions_sash_released(self, _event: tk.Event):
        if not self.missions_sash_dragging:
            return None
        self.missions_sash_dragging = False
        if len(self.paned_missions.panes()) < 2:
            self.missions_sash_drag_start_pos = None
            return None
        desired_position = _event.y - self.missions_sash_drag_offset
        current_position = self.clamp_missions_sash_position(preferred_position=desired_position)
        if current_position is None:
            self.missions_sash_drag_start_pos = None
            return 'break'
        if self.missions_sash_drag_start_pos is not None and abs(current_position - self.missions_sash_drag_start_pos) > 1:
            self.missions_split_user_positioned = True
        self.last_missions_sash_pos = current_position
        self.missions_sash_drag_start_pos = None
        return 'break'

    def on_missions_paned_configure(self, _event: tk.Event):
        self.schedule_missions_summary_pane_fit()
    
    def update_table_missions(self, data, rows_to_highlight:list[int]|None=None, rows_turn_in:list[int]|None=None):
        highlight_rows = {}
        if rows_to_highlight:
            highlight_rows['#0a84ff'] = rows_to_highlight
        if rows_turn_in:
            highlight_rows["#0fff6f"] = rows_turn_in
        self.update_table(self.sheet_missions, data, highlight_rows)

    def update_table_faction_distribution(self, data, rows_to_highlight:list[int]|None=None):
        highlight_rows = {}
        if rows_to_highlight:
            highlight_rows['#0a84ff'] = rows_to_highlight
        self.update_table(self.sheet_faction_distribution, data, highlight_rows)

    def update_table_mission_stats(self, data, rows_to_highlight:list[int]|None=None):
        self.update_table(self.sheet_mission_stats, data, rows_to_highlight)

    def update_table_mission_stats_rewards(self, data, rows_to_highlight:list[int]|None=None):
        self.update_table(self.sheet_mission_stats_rewards, data, rows_to_highlight)

    def update_table_active_journals(self, data, rows_to_highlight:list[int]|None=None):
        self.update_table(self.sheet_active_journals, data, rows_to_highlight)

    def toggle_active_journals_tab(self):
        state = 'normal' if self.checkbox_show_active_journals_var.get() else 'hidden'
        self.tab_controler.tab(self.tab_active_journals, state=state)

    def update_time(self, time:str):
        self.clock_utc.configure(text=time)

    def update_cmdr_location(self, location:str):
        self.label_cmdr_location.configure(text=f'CMDR Location: {location}')

    def show_message_box_info(self, title:str, message:str):
        show_message_box_info(self.root, title, message)

    def show_message_box_info_no_topmost(self, title:str, message:str):
        show_message_box_info_no_topmost(self.root, title, message)

    def show_non_blocking_info(self, title: str, message: str):
        show_non_blocking_info(self.root, title, message)
    
    def show_message_box_warning(self, title:str, message:str):
        show_message_box_warning(self.root, title, message)
    
    def show_message_box_askyesno(self, title: str, message: str) -> bool:
        return show_message_box_askyesno(self.root, title, message)
    
    def show_message_box_askretrycancel(self, title: str, message: str) -> bool:
        return show_message_box_askretrycancel(self.root, title, message)

    def show_indeterminate_progress_bar(self, title: str, message: str):
        return show_indeterminate_progress_bar(self.root, title, message)

class ScrollableFrame(ttk.Frame):
    """A scrollable frame that can contain other widgets."""
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        self.canvas    = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame     = ttk.Frame(self.canvas)

        self.canvas.create_window((0,0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # whenever content or viewport changes, update scrollregion & bar‐visibility
        self.scrollable_frame .bind("<Configure>", lambda e: self._update())
        self.canvas.bind("<Configure>", lambda e: self._update())

        # wheel‐scroll
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)  # For Linux with wheel scroll up
        self.canvas.bind("<Button-5>", self._on_mousewheel)  # For Linux with wheel scroll down

        # run once after idle to hide if unnecessary
        self.after_idle(self._update)

    def bind_mousewheel_recursive(self, widget: tk.Misc | None = None):
        target = self.scrollable_frame if widget is None else widget
        for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            target.bind(sequence, self._on_mousewheel, add='+')
        for child in target.winfo_children():
            self.bind_mousewheel_recursive(child)

    def get_vertical_padding(self) -> int:
        raw_padding = self.cget('padding')
        if isinstance(raw_padding, (tuple, list)):
            padding_values = raw_padding
        else:
            padding_text = str(raw_padding).strip()
            if padding_text.startswith('(') and padding_text.endswith(')'):
                padding_text = padding_text[1:-1]
            padding_values = [value.strip() for value in padding_text.replace(',', ' ').split() if value.strip()]

        padding = tuple(int(float(self.tk.getdouble(value))) for value in padding_values)
        if not padding:
            return 0
        if len(padding) == 1:
            return padding[0] * 2
        if len(padding) == 2:
            return padding[1] * 2
        if len(padding) >= 4:
            return padding[1] + padding[3]
        return 0

    def _update(self):
        # 1) update scrollregion
        self.canvas.configure(scrollregion=self.canvas.bbox("all") or (0,0,0,0))

        # 2) show or hide the bar
        bbox = self.canvas.bbox("all")
        if not bbox:
            self.scrollbar.pack_forget()
            return

        content_h = bbox[3] - bbox[1]
        view_h    = self.canvas.winfo_height()
        if content_h > view_h:
            if not self.scrollbar.winfo_ismapped():
                self.scrollbar.pack(side="right", fill="y")
        else:
            self.scrollbar.pack_forget()

    def _on_mousewheel(self, e):
        bbox = self.canvas.bbox("all")
        if not bbox or (bbox[3] - bbox[1]) <= self.canvas.winfo_height():
            return "break"

        if getattr(e, 'num', None) == 4:
            delta = -1
        elif getattr(e, 'num', None) == 5:
            delta = 1
        else:
            raw_delta = getattr(e, 'delta', 0)
            if raw_delta == 0:
                return "break"
            delta = int(-1 * (raw_delta / 120))
            if delta == 0:
                delta = -1 if raw_delta > 0 else 1

        self.canvas.yview_scroll(delta, "units")
        return "break"

if __name__ == '__main__':
    import sv_ttk
    from config import WINDOW_SIZE
    from popups import apply_theme_to_titlebar
    root = tk.Tk()
    sv_ttk.set_theme("dark")
    root.geometry(WINDOW_SIZE)
    apply_theme_to_titlebar(root)
    view = MissionView(root)
    view.update_table_missions([['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'Workers of Dimocorna Union', 'Yes', 81, '38,995,904', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'Crimson Armada', 'Yes', 63, '30,402,636', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'Crimson Armada', 'Yes', 81, '39,031,136', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'HR 7169 Union Party', 'Yes', 63, '30,498,554', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'HR 7169 Union Party', 'Yes', 64, '30,745,880', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'HR 7169 Union Party', 'Yes', 81, '38,996,552', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'Crimson Armada', 'Yes', 56, '27,075,492', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'Puneith Organisation', 'Yes', 45, '21,718,472', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'Crimson Armada', 'Yes', 45, '21,617,422', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'HR 7169 Union Party', 'Yes', 54, '26,162,298', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'HR 7169 Union Party', 'Yes', 45, '21,762,156', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'HR 7169 Union Party', 'Yes', 54, '26,148,358', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'Crimson Armada', 'Yes', 45, '21,717,464', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'Crimson Armada', 'Yes', 64, '30,908,998', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'HR 7169 Union Party', 'Yes', 72, '34,741,692', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'Puneith Values Party', 'Yes', 54, '26,147,954', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'Crimson Armada', 'Yes', 48, '23,129,086', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'HR 7169 Union Party', 'Yes', 45, '21,688,192', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'Puneith Organisation', 'Yes', 81, '39,165,656', '5 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith', 'Wheelock Port', 'Workers of Dimocorna Union', 'Yes', 72, '34,579,660', '5 days from now']], [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19])
    view.update_table_faction_distribution([['Puneith Values Party', 54, 424, '23,578,024'], ['Puneith Organisation', 126, 352, '31,524,781'], ['Workers of Dimocorna Union', 153, 325, '39,245,618'], ['Crimson Armada', 402, 76, '19,826,781'], ['HR 7169 Union Party', 478, 0, '20,543,872']])
    view.update_table_mission_stats([('TotalMissions', 20), ('WingMissions', 20), ('ActiveMissions', 0), ('KillCount', 478), ('KillRemaining', 0), ('TotalKillCount', 1213), ('KillRatio', '2.54'), ('NumStations', 3)])
    view.update_table_mission_stats_rewards([('TotalReward', '585,233,562'), ('TotalSharableReward', '585,233,562'), ('CurrentReward', '585,233,562'), ('CurrentSharableReward', '585,233,562'), ('AverageReward', '29,261,678'), ('AverageSharableReward', '29,261,678')])
    view.update_table_active_journals([['F11601975', 'CmdrTest', 'C:\\Path\\To\\Journal.20240615T123456.01.log'], ['F11601976', 'CmdrExample', 'C:\\Path\\To\\Journal.20240615T123457.01.log']])
    view.update_cmdr_location('Puneith, Wheelock Port')
    view.dropdown_cmdr['values'] = ['Skywalkerctu', 'SKYWALKER THERESA', 'SKYWALKER SAGARMATHA', 'Skywalker Behemoth', 'SKYWALKERKUNIS', 'SKYWALKER MCDOWELL', 'SKYWALKER SOJOURNER', 'SKYWALKER TOULOUSE', 'SKYWALKER MONTENEGRO', 'SKYWALKER TRIPOLI']
    view.dropdown_cmdr.current(0)
    root.mainloop()
