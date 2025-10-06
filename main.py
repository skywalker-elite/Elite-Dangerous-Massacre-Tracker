import os
from argparse import ArgumentParser
import tkinter as tk
import sv_ttk
from controller import MissionController
from model import MissionModel, JournalReader
import sys
import pickle
from PIL import Image, ImageTk
from utility import getResourcePath, getJournalPath, getCachePath
from config import WINDOW_SIZE, APP_NAME
from popups import apply_theme_to_titlebar

def load_journal_reader_from_cache(jr_version:str, journal_paths: list[str]) -> JournalReader | None:
    cache_path = getCachePath(jr_version, journal_paths)
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, 'rb') as f:
                jr:JournalReader = pickle.load(f)
            # smoke‐test: try to read journals once
            jr.read_journals()
            return jr
        except Exception:
            # something went wrong, nuke the cache
            try:
                os.remove(cache_path)
            except OSError:
                pass
    return None

def main():
    parser = ArgumentParser()
    parser.add_argument("-p", "--paths",
                    nargs='+', dest="paths", default=None,
                    help="journal paths: overrides journal path(s)")
    args = parser.parse_args()
    if args.paths:
        journal_paths = args.paths
    else:
        journal_path = getJournalPath()
        journal_paths = [journal_path] if journal_path else None
    assert journal_paths is not None, f'No default journal path for platform {sys.platform}, please specify one with --paths'
    for journal_path in journal_paths:
        assert os.path.exists(journal_path), f'Journal path {journal_path} does not exist, please specify one with --paths if the default is incorrect'

    # build first, then splash, then tk root
    if sys.platform == 'darwin':
        jr = load_journal_reader_from_cache(jr_version=JournalReader.version_hash(), journal_paths=journal_paths)
        model = MissionModel(journal_paths, journal_reader=jr)
    else:
        try:
            import pyi_splash  # type: ignore
            pyi_splash.update_text('Reading journals…')
            jr = load_journal_reader_from_cache(jr_version=JournalReader.version_hash(), journal_paths=journal_paths)
            model = MissionModel(journal_paths, journal_reader=jr)
            pyi_splash.close()
        except ModuleNotFoundError:
            jr = load_journal_reader_from_cache(jr_version=JournalReader.version_hash(), journal_paths=journal_paths)
            model = MissionModel(journal_paths, journal_reader=jr)

    root = tk.Tk()
    apply_theme_to_titlebar(root)
    sv_ttk.use_dark_theme()
    root.title(APP_NAME)
    root.geometry(WINDOW_SIZE)
    photo = Image.open(getResourcePath(os.path.join('images','EDCM.png')))
    root.iconphoto(True, *[ImageTk.PhotoImage(photo.resize((resolution, resolution))) for resolution in (16, 32, 48, 64, 128, 256, 512, 1024) if resolution < photo.width and resolution < photo.height])
    root.update()

    app = MissionController(root, model=model)
    root.mainloop()

if __name__ == "__main__":
    main()
