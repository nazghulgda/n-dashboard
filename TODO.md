# TODO

## First runs on macOS and Linux

The setup and build scripts for Apple Silicon and Linux haven't been run yet, and neither has drag and drop of files on those systems. Check:

- `setup_macos.sh`, `build_macos.sh` on an Apple Silicon Mac: the `.app` starts, has its icon, keeps data in `~/Library/Application Support/WinDashboard`;
- `setup_lin.sh`, `build_lin.sh`, `install_lin.sh` (and `--uninstall`) on Linux: menu entry, icon, `StartupWMClass` matching the window;
- dropping files and folders onto the Links and Attachments panels on both systems;
- fonts and the look of both themes, since they were only checked on Windows.

## Bundle identifier for signing on macOS

`build_macos.sh` doesn't set `--osx-bundle-identifier`. Add your own identifier there before signing the macOS build.

## Connection to a shared database (e.g. PostgreSQL)

Today every copy of WinDashboard keeps its data in a local SQLite file. The plan is a team setup:

- the current application becomes the **team member** app, working on a shared database (PostgreSQL or similar) instead of, or next to, the local SQLite file;
- a separate **manager** application shows the tasks of the whole team.

This is a large extension, not a switch in the settings. Things to decide before starting:

- who owns a task, and what a team member sees: only their own tasks or the team's;
- offline work: does the team member app keep a local copy and synchronise, or does it need the server all the time;
- attachments: today they're files in the data folder, so a shared setup needs shared storage for them;
- logging in and permissions;
- how archive and backup work when the data lives on a server;
- moving existing local data into the shared database.

`database.py` is already the only module that talks to SQLite, so it's the place where a second backend would start.
