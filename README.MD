# n-dashboard

A desktop task dashboard for Windows, Linux and macOS (Apple Silicon), written in Python with tkinter.

Each task gets its own kanban-style list of checkpoints, a due date, notes, links to files and folders, and attached files. Finished or paused work goes to a ZIP archive, and all the data can be backed up (by hand or automatically) and restored from inside the application.

## Running from source

You need Python 3.10 or newer with tkinter:

- **Windows**: Python from python.org (keep "tcl/tk and IDLE" selected in the installer). The free-threaded build (`python3.xxt`) won't do; use the standard one.
- **Linux**: tkinter, venv and pip are often separate packages: `python3-tk python3-venv python3-pip` on Debian and Ubuntu, `python3-tkinter` on Fedora, `tk` on Arch.
- **macOS** (Apple Silicon only): the universal2 Python from python.org includes tkinter; with Homebrew Python you also need `brew install python-tk@3.X`.

The setup scripts below check all of this and create the virtual environment. To do it by hand:

```
python -m venv .venv
.venv/bin/python -m pip install -U -r requirements.txt      (Windows: .venv\Scripts\python.exe)
.venv/bin/python main_window.pyw                            (Windows: .venv\Scripts\pythonw.exe)
```

The libraries are pinned in `requirements.txt`:

- `platformdirs` finds the data folder of each system;
- `filelock` keeps a second copy of the app from starting;
- `tkinterdnd2` lets you drop files from the file manager onto a task. If its Tk extension can't load on some system, the app starts anyway, just without drag and drop.

## Building the application

| System | Setup | Build | Result in `dist/` |
|---|---|---|---|
| Windows | `setup.bat` | `build.bat` | `n-dashboard.exe` (one file) |
| Linux | `./setup_lin.sh` | `./build_lin.sh` | `n-dashboard` (one file), `n-dashboard.png`, `install_lin.sh` |
| macOS (Apple Silicon) | `./setup_macos.sh` | `./build_macos.sh` | `n-dashboard.app` (arm64), `n-dashboard-macos.zip` |

The setup script creates `.venv` (only if it doesn't exist yet) and installs the libraries and PyInstaller into it. On Linux it installs missing system packages through `apt-get`, `dnf`, `pacman` or `zypper`, so it may ask for your sudo password. On Windows it skips a free-threaded Python if `py -3` picks one.

The build script runs PyInstaller with all options written in the script; there's no `.spec` file to maintain. PyInstaller's own hook packs the drag-and-drop extension, so no extra options are needed for it.

On Linux the binary has no icon or menu entry of its own. `dist/install_lin.sh` installs it for the current user without sudo: the program goes to `~/.local/bin/n-dashboard`, plus an icon and an entry in the applications menu. `install_lin.sh --uninstall` removes them and asks before deleting your data.

Things to know:

- PyInstaller doesn't cross-compile. Build the Linux version on Linux and the macOS version on an Apple Silicon Mac.
- Intel Macs aren't supported. The macOS scripts stop with an error when Python runs as x86_64, which also happens in a terminal running under Rosetta.
- Close the running application before building again, or the Windows build fails because it can't overwrite `n-dashboard.exe`.
- The scripts don't sign anything. On macOS an unsigned app downloaded from the internet gets blocked by Gatekeeper (right-click → Open the first time), so sign builds before you hand them out. `build_macos.sh` sets no bundle identifier; add `--osx-bundle-identifier` with your own when you sign.
- Windows Explorer caches icons and may show the old one after a rebuild; renaming or moving the file helps.
- `N_DASHBOARD_DATA_DIR` makes the app use another data folder, which is handy for trying a build without touching your real data.

## Where the data lives

| System | Data folder |
|---|---|
| Windows | `%LOCALAPPDATA%\n-dashboard` |
| macOS | `~/Library/Application Support/n-dashboard` |
| Linux | `~/.local/share/n-dashboard` (or `$XDG_DATA_HOME/n-dashboard`) |

Settings shows the path and has an **Open** button for it. Inside the folder:

| Path | Contents |
|---|---|
| `tasks.db` | the SQLite database, including the kanban templates |
| `tasks.db.bak`, `tasks.db.bak.1` ... | last working copy and daily copies |
| `tasks.db.corrupt_*` | damaged databases kept after a restore |
| `attachments/` | attached files, one folder per task |
| `archive/` | archived tasks as ZIP files; `archive/removed/` for removed ones |
| `backups/` | full backups, made by hand and automatic ones |
| `settings.json` | theme, window sizes, automatic backup and idle-task settings |
| `n-dashboard.lock` | lock that keeps a second copy from starting |

Attachment paths in the database are relative to the data folder, so you can move the folder to another computer and it keeps working.

Up to version 0.7 the app was called WinDashboard and kept its data in a `WinDashboard` folder (for example `%LOCALAPPDATA%\WinDashboard`). Versions before 0.6 kept it next to the program files. On the first start, when the new data folder has no database yet, the app copies the old data over, checking the `WinDashboard` folder first, and tells you where it came from. The old files stay put until you delete them yourself. Automatic backups named `WinDashboard_autobackup_*` still count as automatic, so the app prunes them like the new ones.

## Main window

The main window lists active tasks as cards. A card shows the title, creation date, due date, the first 80 characters of the description, a progress bar, the current status and the date of the last activity. The coloured stripe on the left tells you at a glance whether a task hasn't started, is in progress or is finished.

The due date turns amber when it's at most 3 days away and red when it's today or already past ("overdue since ..."). Finished tasks are never overdue. A task with no activity for longer than the limit in Settings (14 days by default) shows "no activity for N days" instead of the last activity date.

The search box looks in titles, descriptions and the notes of each task; when the match is in a note, the card says which one ("found in notes: ..."). It ignores letter case, Polish letters included, and finds any part of a word. You can sort by last activity, due date (nearest first, tasks without one at the end), creation date, progress or title. Any change made in a task window shows up on the list within 5 seconds; cards are updated in place, so the list doesn't blink.

Click a card to open the task. Each card has a **Put on hold** button, and a finished task (all checkpoints done) also gets an **Archive** button.

The header buttons open **New task**, **Archive**, **On Hold**, **Backup**, **Settings** and **Export**.

Windows remember their size between starts (small dialogs, such as New task, size themselves to their content). The main window and the On Hold, Archive, Backup and Kanban Templates windows remember their position too. Task and note windows, and the list of deleted attachments, keep only their size, since several of them are often open at once. A window saved on a monitor that's no longer connected opens on the main screen.

The mouse wheel scrolls the list under the cursor, in any window of the app, also one that's in the background.

## Creating a task

A new task needs a title. The description and due date are optional. The due date takes `2026-11-20`, `today` or `+N` (N days from today).

You also pick the kanban: one of the templates (the default one is preselected) or an empty kanban with a single "Task completed" checkpoint, so you can build the list yourself.

## Task window

The header shows the title, the description and the due date; ✏ edits all three. **Duplicate** asks first, then creates a copy of the task with its description, due date, checkpoints (none completed) and links, and opens it. Notes and attachments describe work already done, so the copy doesn't get them.

### Checkpoints

A checkpoint is either a checkbox or a counter. Counters have − and + buttons and track how many times something happened, for example review rounds. They're optional: a counter you never used doesn't count towards progress and doesn't block finishing the task, while a counter used at least once counts as done.

A completed checkbox shows the date you ticked it; a used counter shows the date of its last iteration ("last 2026-11-13"). Unticking clears the date. Checkpoints completed before version 0.7 have no date.

You can rename a checkpoint, change its type, move it up or down, add new ones at the end and delete them. The last checkpoint of a task can't be deleted, because a task without checkpoints could never be finished.

### Status

Every checkpoint of a template can lead to a status. A task reaches a status when all checkpoints with that status are completed, along with the checkpoints of every status before it. Statuses follow each other in the order of their first checkpoint in the template. On top of that:

- nothing completed: **Not started**
- started, but no status reached yet: **In progress**
- every checkpoint completed: **Finished**

The default template leads through these statuses:

| Status | Reached with |
|---|---|
| Planned | Kick-off |
| Started | CheckPoint 1 |
| In progress | CheckPoints 2, 3 and 4 |
| In review | CheckPoint 7 (CheckPoint 6 is a counter, so it never blocks) |
| Rework / fixes | CheckPoint 8 |

A task copies the statuses of its checkpoints when it's created. Editing the template later, or moving, adding and deleting checkpoints inside the task, doesn't change what a status means for that task. Checkpoints you add to a task by hand have no status.

### Notes

Notes have a title and free text. The list shows the newest note first, with the first two lines of its content. Click a note to open it in its own window; **Edit** switches to the editor, **Save** switches back to the formatted view.

The editor understands a small markdown subset: `**bold**`, `*italic*`, `~~strikethrough~~` and coloured highlights (`==#FFD700==text==`), which the **H** button inserts from a colour picker.

If you close a note with unsaved changes, the app asks whether to save them. When you close the task window or the whole application, open notes get saved without asking, so nothing typed is lost.

Notes can't be deleted. That's on purpose: they're meant to be a permanent log of the task.

### Links

**+ File** and **+ Folder** add a link to a file or folder anywhere on disk or on a network share; you can also drop files and folders from the file manager onto the Links panel. Folder links end with a `/`. Click a link to open it in the default application of the system; hover over it to see the full path. Links can be renamed, pointed at a different path or removed. The app stores the path only and never copies the target.

### Attachments

Attachments, unlike links, are copies. **+ Add file** (or dropping files onto the Attachments panel) copies them into `attachments/<task id>_<task title>/` in the data folder, so they stay available after the original moves or disappears. A file name that's already taken gets a `_2`, `_3`, ... suffix. Folders can't be attached; drop them on Links instead.

Deleting an attachment moves the file into a `deleted` subfolder of the task's attachment folder. **Deleted (N)** appears in the panel header while there are deleted attachments, and opens a list where you can open or restore each of them.

## On Hold

**Put on hold** moves a task off the main list into the On Hold window, which shows when each task was paused and how many checkpoints it has completed. From there you can restore a task to the main list or archive it.

## Archive

Archiving removes the task from the database and saves it as a ZIP file in `archive/`. The ZIP contains:

- `task.json` with all the task data
- `README.txt`, a plain-text summary you can read without the app (with the due date and completion dates)
- all attachments, including deleted ones

The Archive window lists archived tasks in two groups, On Hold and Finished, with a search box for titles and descriptions. **Restore** brings a task back to the list it came from (with a new id). **Delete** moves the ZIP to `archive/removed/`. Restoring moves the ZIP to `archive/removed/` as well, so an archive file is never deleted.

## Backup

The Backup window creates a full backup as a ZIP file in `backups/`. It includes:

- a consistent snapshot of the database, taken with the SQLite backup API
- the last working copy of the database (`tasks.db.bak`)
- all attachments
- the archive, including `archive/removed/`
- `settings.json`
- `backup_meta.json` with the date, app version, task counts and any files that couldn't be read

The backup runs in the background, so the window keeps responding and shows which file it's packing. Files that can't be read (a file locked by another program, say) are skipped and listed when the backup finishes.

Automatic backups run in the background too, by default every 7 days. The app checks at start and every 10 minutes whether one is due, and after each automatic backup it removes the oldest automatic ones beyond the number set in Settings (5 by default). Backups you make by hand are never removed automatically. The Backup window marks automatic backups with "automatic". If an automatic backup fails, you get one warning, and the app tries again 10 minutes later.

**Restore** merges a backup into the current data rather than replacing it. Tasks and archived tasks that are missing now get added; nothing that exists gets changed or removed. A task counts as existing if a task with the same title and creation date is in the database or in the archive, so restoring the same backup twice adds nothing the second time.

Deleting a backup removes the file permanently.

## Export

**Export** saves a summary of the tasks for someone who doesn't use the app: title, list (active or on hold), status, progress, due date, creation date, last activity and description. Choose:

- **Markdown**: a table readable in any Markdown viewer, with overdue dates marked;
- **CSV**: opens in Excel. The file is UTF-8 with a BOM, so Polish letters show correctly.

Tasks on hold can be left out. Within each list, tasks are sorted by due date.

## Database protection

The app checks the database (`PRAGMA quick_check`) at start, every 10 minutes and on close. A database that passes the check gets copied to `tasks.db.bak`, the last working copy. Once a day that copy moves to `tasks.db.bak.1` and the older ones shift down (`.bak.2`, `.bak.3`), so a mistake you notice a day or two later can still be undone.

If the database is damaged, missing or suddenly empty, the app restores it from the newest copy that passes the check and tells you so. The damaged file stays next to the database as `tasks.db.corrupt_<date>_<time>`. If none of the copies is usable, the app shows an error instead of starting with empty data.

## Settings

- **Color theme**: Dark (terminal) or Light (Windows). Switching rebuilds every open window on the spot without closing anything, including text you're in the middle of typing in a note.
- **Data folder**: the path, which you can copy, and an **Open** button.
- **Automatic backup**: off, every day, or every 7, 14 or 30 days, plus how many automatic backups to keep.
- **Idle tasks**: after how many days without activity a task gets highlighted (0 turns it off).
- **Kanban templates**: **Edit templates...** opens the template editor.

### Kanban templates

The template editor lists templates on the left and the checkpoints of the selected one on the right, with a line showing the statuses a task goes through. You can create, rename, duplicate and delete templates and pick the default one; the last template can't be deleted. For each checkpoint you set the name, type (checkbox or counter) and the status it leads to: pick an existing status or type a new one. Checkpoints can be added, edited, moved and deleted, but a template always keeps at least one.

Changes are saved at once and apply to tasks created afterwards. Existing tasks keep their checkpoints and statuses.

## Configuration

Most settings live in the Settings window. `config.py` holds what's left:

- `DEFAULT_TEMPLATE`: the template copied into a new database as "Default" (after that you edit templates in the app)
- `DEFAULT_CHECKPOINT`: the single checkpoint of an empty kanban
- `STATUS_NOT_STARTED`, `STATUS_IN_PROGRESS`, `STATUS_FINISHED`: names of the statuses that don't come from a template
- `DB_CHECK_INTERVAL_MS`: how often the database gets checked (10 minutes by default)
- `DB_BACKUP_DAILY_COPIES`: how many daily copies of the database to keep (3 by default)
- `MAIN_WINDOW_SIZE`, `APP_TITLE`, `APP_VERSION`

The colours of both themes are in `theme.py`; fonts for each system are at the top of `ui_helpers.py`.

Databases and archives from older versions get converted automatically when you open them, including the early ones that called checkpoints "stages". Tasks created before version 0.7 get their statuses from the template of those versions.

## Project layout

| Path | Purpose |
|---|---|
| `main_window.pyw` | start-up, main window, On Hold, Archive and Backup windows, New task and Export dialogs |
| `task_window.py` | task window, note editor and their dialogs |
| `settings_window.py` | Settings dialog and the kanban template editor |
| `database.py` | database schema, migrations, all reads and writes, templates, note search, checks and working copies |
| `archive.py` | exporting tasks to ZIP and importing them back |
| `backup.py` | creating, listing, restoring and automatically pruning full backups |
| `report.py` | the Markdown and CSV export |
| `settings.py` | reading and writing `settings.json` |
| `theme.py` | colour themes |
| `ui_helpers.py` | fonts, buttons, dialogs, tooltips, scrollable lists, due dates, window sizes, drag and drop |
| `config.py` | data folder and the settings described above |
| `test_db.py` | tests |
| `assets/` | `app.svg` (source), `app.ico` for Windows, `png/app-*.png` for Linux and macOS |
| `setup*`, `build*`, `install_lin.sh` | scripts described in "Building the application" |
| `TODO.md` | planned work |

## Tests

```
.venv/bin/python test_db.py          (Windows: .venv\Scripts\python.exe test_db.py)
```

The tests run in a temporary folder and never touch your real data. They cover task CRUD, checkpoint statuses and templates, counters, due dates, completion dates, duplicating tasks, note search, archiving with attachments and restoring from the archive, restoring deleted attachments, backups (by hand, automatic, pruning and merge restore), the export, settings, moving data of older versions, converting old database schemas, and recovering a damaged database from its copies.
