# Installing Homefeed

Homefeed is a YouTube app for your computer: a short daily feed of videos picked for you, which gets better the more videos you rate.

## Windows

1. Download `Homefeed-Setup-<version>.exe` from the [latest release](https://github.com/0xZ0uk/homefeed/releases/latest).
2. Open it. Windows may show a blue "Windows protected your PC" box, because Homefeed isn't signed with a paid certificate. Click **More info**, then **Run anyway**.
3. That's it: there are no questions to answer and no administrator password. Homefeed installs, adds shortcuts to the Start Menu and the desktop, and opens.

## Linux

1. Download `Homefeed-<version>-x86_64.AppImage` from the [latest release](https://github.com/0xZ0uk/homefeed/releases/latest).
2. Make it executable (`chmod +x Homefeed-*.AppImage`, or Properties → Permissions → "Allow executing file as program") and open it. If it doesn't start, your system may need FUSE 2 (`libfuse2`).

## Using it

The first time, Homefeed walks you through setting up your feed. It keeps running in the background when you close its window, so your feeds stay up to date: look for its icon in the system tray (next to the clock). Right-click it for **Open Homefeed**, **Start at login** and **Quit Homefeed**.

## Updates

Homefeed updates itself. When a new version has downloaded you'll get a notification; choose **Restart to update** in the tray menu, or just let it install the next time you quit Homefeed.

## Where your data is

Your feed, ratings and settings stay on your computer:

- Windows: `%APPDATA%\Homefeed` (paste that into the File Explorer address bar)
- Linux: `~/.config/Homefeed`

The tray menu's **Open data folder** and **Open logs** go straight there. If something goes wrong, the files in `logs` help whoever is helping you.

## Uninstalling

- Windows: Settings → Apps → Installed apps → Homefeed → Uninstall. Quit Homefeed from the tray first.
- Linux: quit Homefeed and delete the AppImage. If you turned on **Start at login**, turn it off first (or delete `~/.config/autostart/homefeed.desktop`).

Uninstalling keeps your data. To remove it too, delete the folder listed under [Where your data is](#where-your-data-is).
