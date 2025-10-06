import tkinter as tk
from tkinter import ttk
from tksheet import Sheet
from typing import Literal
import tkinter.font as tkfont
from popups import show_message_box_info, show_message_box_warning, show_message_box_info_no_topmost, show_non_blocking_info, show_message_box_askyesno, show_message_box_askretrycancel, show_indeterminate_progress_bar, center_window_relative_to_parent, apply_theme_to_titlebar
from config import WINDOW_SIZE_TIMER, font_sizes

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
        self.tab_mission = ttk.Frame(self.tab_controler)
        self.tab_options = ScrollableFrame(self.tab_controler)
        self.tab_active_journals = ttk.Frame(self.tab_controler)

        self.tab_controler.add(self.tab_mission, text='Missions')
        self.tab_controler.add(self.tab_active_journals, text='Active Journals', state='hidden')
        self.tab_controler.add(self.tab_options, text='Options')

        # Make the grid expand when the window is resized
        def configure_tab_grid(tab):
            tab.rowconfigure(0, pad=1, weight=1)
            tab.columnconfigure(0, pad=1, weight=1)

        for tab in [self.tab_mission, self.tab_active_journals, self.tab_options]:
            configure_tab_grid(tab)

        self.tab_controler.pack(expand=True, fill='both')

        # Initialize the tksheet.Sheet widget
        self.sheet_missions = Sheet(self.tab_mission, name='sheet_jumps')

        # Set column headers
        self.sheet_missions.headers([
            'TargetFaction', 'DestinationSystem', 'Faction', 'Wing', 'KillCount', 'Reward', 'Expires'
        ])

        self.configure_sheet(self.sheet_missions)

        # self.bottom_bar = ttk.Frame(self.tab_jumps)
        # self.bottom_bar.grid(row=2, column=0, columnspan=3, sticky='ew')
        # self.tab_jumps.grid_rowconfigure(1, weight=0)
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
        self.labelframe_EDCM = ttk.Labelframe(self.tab_options.scrollable_frame, text='EDCM')
        self.labelframe_EDCM.grid(row=0, column=0, padx=10, pady=10, sticky='w')
        self.button_check_updates = ttk.Button(self.labelframe_EDCM, text='Check for Updates')
        self.button_check_updates.pack(side='left', padx=10, pady=10, anchor='w')
        self.button_go_to_github = ttk.Button(self.labelframe_EDCM, text='Go to GitHub Repo')
        self.button_go_to_github.pack(side='left', padx=10, pady=10, anchor='w')
        self.button_clear_cache = ttk.Button(self.labelframe_EDCM, text='Clear Cache and Reload')
        self.button_clear_cache.pack(side='left', padx=10, pady=10, anchor='w')
        self.checkbox_show_active_journals_var = tk.BooleanVar()
        self.checkbox_show_active_journals_var.trace_add('write', lambda *args: self.toggle_active_journals_tab())
        self.checkbox_show_active_journals = ttk.Checkbutton(
            self.labelframe_EDCM,
            text='Show Active Journals Tab',
            variable=self.checkbox_show_active_journals_var,
        )
        self.checkbox_show_active_journals.pack(side='left', padx=10, pady=10, anchor='w')

        self.labelframe_settings = ttk.Labelframe(self.tab_options.scrollable_frame, text='Settings')
        self.labelframe_settings.grid(row=2, column=0, padx=10, pady=10, sticky='w')
        self.button_reload_settings = ttk.Button(self.labelframe_settings, text='Reload Settings File')
        self.button_reload_settings.pack(side='left', padx=10, pady=10, anchor='w')
        self.button_open_settings = ttk.Button(self.labelframe_settings, text='Open Settings File')
        self.button_open_settings.pack(side='left', padx=10, pady=10, anchor='w')
        self.button_open_settings_dir = ttk.Button(self.labelframe_settings, text='Open Settings Directory')
        self.button_open_settings_dir.pack(side='left', padx=10, pady=10, anchor='w')
        self.button_reset_settings = ttk.Button(self.labelframe_settings, text='Reset Settings to Defaults', style='Danger.TButton')
        self.button_reset_settings.pack(side='left', padx=10, pady=10, anchor='w')

        # Active Journals tab
        self.sheet_active_journals = Sheet(self.tab_active_journals, name='sheet_active_journals')

        # Set column headers
        self.sheet_active_journals.headers(['FID', 'CMDR Name', 'Carrier Name', 'Journal File'])
        
        self.configure_sheet(self.sheet_active_journals)

        self.bottom_bar_active_journals = ttk.Frame(self.tab_active_journals)
        self.bottom_bar_active_journals.grid(row=1, column=0, columnspan=3, sticky='ew')
        self.tab_active_journals.grid_rowconfigure(1, weight=0)
        # Buttons
        self.button_open_journal = ttk.Button(self.bottom_bar_active_journals, text='Open Journal File')
        self.button_open_journal.pack(side='left')

    def configure_sheet(self, sheet:Sheet):
        sheet.grid(row=0, column=0, columnspan=3, sticky='nswe')
        sheet.change_theme('dark', redraw=False)
        sheet.set_options(**self.sheet_colors)
        # Enable column resizing to match window resizing
        sheet.enable_bindings('single_select', 'drag_select', 'column_select', 'row_select', 'arrowkeys', 'copy', 'find', 'ctrl_click_select', 'right_click_popup_menu', 'rc_select')
        sheet.column_width_resize_enabled = False
        sheet.row_height_resize_enabled = False

    def set_font_size(self, font_size:str, font_size_table:str):
        size = font_sizes.get(font_size, font_sizes['normal'])
        size_table = font_sizes.get(font_size_table, font_sizes['normal'])

        # 1) resize all tksheets
        for sheet in [self.sheet_missions, self.sheet_active_journals]:
            sheet.font(('Calibri', size_table, 'normal'))
            sheet.header_font(('Calibri', size_table, 'normal'))

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

    def update_table(self, table:Sheet, data):
        table.set_sheet_data(data, reset_col_positions=False)
        table.set_all_column_widths()
    
    def update_table_missions(self, data):
        self.update_table(self.sheet_missions, data)

    def update_table_active_journals(self, data):
        self.update_table(self.sheet_active_journals, data)

    def toggle_active_journals_tab(self):
        state = 'normal' if self.checkbox_show_active_journals_var.get() else 'hidden'
        self.tab_controler.tab(self.tab_active_journals, state=state)

    def update_time(self, time:str):
        self.clock_utc.configure(text=time)

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
        delta = int(-1 * (e.delta / 120))
        # only scroll if there’s overflow
        bbox = self.canvas.bbox("all")
        if bbox and (bbox[3] - bbox[1]) > self.canvas.winfo_height():
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
    view.update_table_missions([['Anana Brotherhood', 'Anana', 'Workers of Dimocorna Union', True, 81, '38,995,904', '6 days from now'], ['Anana Brotherhood', 'Anana', 'Crimson Armada', True, 63, '30,402,636', '6 days from now'], ['Anana Brotherhood', 'Anana', 'Crimson Armada', True, 81, '39,031,136', '6 days from now'], ['Anana Brotherhood', 'Anana', 'HR 7169 Union Party', True, 63, '30,498,554', '6 days from now'], ['Anana Brotherhood', 'Anana', 'HR 7169 Union Party', True, 64, '30,745,880', '6 days from now'], ['Anana Brotherhood', 'Anana', 'HR 7169 Union Party', True, 81, '38,996,552', '6 days from now'], ['Anana Brotherhood', 'Anana', 'Crimson Armada', True, 56, '27,075,492', '6 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith Organisation', True, 45, '21,718,472', '6 days from now'], ['Anana Brotherhood', 'Anana', 'Crimson Armada', True, 45, '21,617,422', '6 days from now'], ['Anana Brotherhood', 'Anana', 'HR 7169 Union Party', True, 54, '26,162,298', '6 days from now'], ['Anana Brotherhood', 'Anana', 'HR 7169 Union Party', True, 45, '21,762,156', '6 days from now'], ['Anana Brotherhood', 'Anana', 'HR 7169 Union Party', True, 54, '26,148,358', '6 days from now'], ['Anana Brotherhood', 'Anana', 'Crimson Armada', True, 45, '21,717,464', '6 days from now'], ['Anana Brotherhood', 'Anana', 'Crimson Armada', True, 64, '30,908,998', '6 days from now'], ['Anana Brotherhood', 'Anana', 'HR 7169 Union Party', True, 72, '34,741,692', '6 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith Values Party', True, 54, '26,147,954', '6 days from now'], ['Anana Brotherhood', 'Anana', 'Crimson Armada', True, 48, '23,129,086', '6 days from now'], ['Anana Brotherhood', 'Anana', 'HR 7169 Union Party', True, 45, '21,688,192', '6 days from now'], ['Anana Brotherhood', 'Anana', 'Puneith Organisation', True, 81, '39,165,656', '6 days from now'], ['Anana Brotherhood', 'Anana', 'Workers of Dimocorna Union', True, 72, '34,579,660', '6 days from now'], ['Total', '', '', '', 1213, '585,233,562', '']])
    root.mainloop()