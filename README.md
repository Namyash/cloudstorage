# Family Drive

Family Drive is a browser-based file server for a drive connected to your home computer. The same website gives the admin a storage and account dashboard and each family member or guest their own file area.

## Install the Windows package

With Python 3.10 or newer, install the wheel supplied with the release. Then run Family Drive and open `http://127.0.0.1:8765/`.

```powershell
py -3 -m pip install .\family_drive-0.1.1-py3-none-any.whl
py -3 -m family_drive
```

The installed package also provides the `family-drive` command. It keeps host settings in `%LOCALAPPDATA%\FamilyDrive\host.json`. The database and file objects go in the storage folder chosen in the browser. The code in the terminal unlocks first-run storage selection and creates the first admin account.

## Start on Windows

1. Open PowerShell in the project folder and run `npm run dev` with Node.js, npm, and Python 3.10 or newer installed. You can also double-click `Start-Family-Drive.cmd` to launch with Python. The launcher installs Flask and Waitress from PyPI on first use.
2. Open `http://127.0.0.1:8765/`. The storage explorer shows physical disks and Windows drive letters, including when no eligible storage drive is attached. Connect your data drive and wait for its drive letter to appear. To use the Windows system drive, explicitly select **Include the Windows system drive**.
3. Enter the setup code printed in the terminal, choose **Browse** on your data drive, and choose or create a dedicated storage folder. A new folder starts with a fresh database. Use the same setup code to create your admin account on the next screen.
4. On **Overview**, use the pencil next to your admin account to set your personal quota. Open **Family space → Set quota** to assign the household quota. Both start at 0 GB. Use **Add person** to create family or guest accounts and enter their quotas. Send temporary passwords privately so each person can choose their own password on the first visit.
5. Keep the host computer and launcher running while people use the drive. `Ctrl+C` stops the server. Start it again with the same launcher and drive attached.

The launcher saves the selected path and storage identity in `.runtime/host.json` inside the application folder. An administrator can open **Storage explorer** in the sidebar to view drive status, capacity, folders, and file details. If the storage drive disconnects, the local site shows an offline page. Reconnect it to resume, or use the terminal setup code and **Reconnect this folder** if Windows assigned it a different drive letter. Keep the storage folder together when moving it.

## Change the active drive or folder

On the host computer, sign in as the admin and open **Storage explorer → Change storage location**. Browse to the destination and enter a new folder name and your admin sign-in password. Family Drive pauses household requests while it copies the database and files, verifies the copied data, and activates the destination. Both drives need to remain connected until the move finishes. The old folder stays on its original drive as a backup. The destination needs enough space for the existing files and assigned quotas. Each household uses one active storage folder.

## Storage and access

- **My files.** Every account has a personal vault. The browser encrypts filenames and file contents before sending them to the drive. Each person sets a separate vault passphrase. Save the recovery key generated during setup. The vault locks after 10 minutes of inactivity or when you leave the vault. A sign-in password reset keeps the original vault passphrase.
- **Family space.** Admins and family accounts can read and upload here. The admin sets a separate shared quota. The uploader or admin can delete shared files.
- **Guest exchange.** The admin can enable a separate shared folder for a guest, give their account an expiry, or pause their access. Guests have personal storage even when their exchange folder is disabled. A user's own guest-exchange uploads count against that user's quota.
- **Storage limits.** Quotas are in decimal GB. The server reserves space when an upload begins, checks available disk space, and keeps 512 MiB of free disk headroom. Private files use a small amount of extra space for encryption. Stale uploads are cleared after 24 hours at startup or when the next upload begins.
- **Drive usage.** The overview shows the storage folder, actual free disk space, total assigned quotas, and the amount you can still allocate. Each household runs its own instance and uses the drive it chooses.

Shared files are stored as ordinary files and protected by account permissions. Private file names and contents are encrypted, while the server has access to account names, file sizes, and timestamps. Trust the host and the website code it serves. Someone who controls that code could replace it to capture passphrases in future sessions. Keep the host and its dependencies updated. Use a separate offline backup of the whole data folder, including the SQLite database and `.family-drive-id`. Stop Family Drive while making a filesystem copy of the data folder, and test a restore before relying on the drive for your only copy.

For private downloads over 256 MiB, use a desktop browser that supports the file-save picker, such as Chrome or Edge. Smaller private files can download in browsers that support Web Crypto without the picker.

## Recover or reset a private vault

- From **My files**, choose **Forgot vault passphrase?** and **Use recovery key** if you saved one for this vault. Enter it and choose a new passphrase to keep your files in place. Save the new recovery key shown afterward.
- To start fresh, select **Start fresh and keep archive** and confirm with your Family Drive sign-in password. The original encrypted files move to **Archived vaults**, where they still count toward your quota. To download them, open the archive using its original passphrase or a recovery key saved for that archive. For an empty vault, the action is **Reset empty vault**.
- With **My files** unlocked, open **Vault security** to change your passphrase or generate a recovery key. This also works for vaults created before recovery keys were available, as long as you know the current vault passphrase.

## Connect family devices over private HTTPS

The default launcher listens only on the host computer. For phones and other computers, the app needs a private HTTPS address so the browser can use Web Crypto. One supported setup path is a private Tailscale Serve proxy. You can also use an existing LAN HTTPS reverse proxy with certificates trusted by your devices.

1. Set up Tailscale on the host and approved clients. Review the tailnet access policy so only the intended users can reach the host’s HTTPS service. The default policy can be broader than that.
2. On the host, start a private proxy with `tailscale serve --bg http://127.0.0.1:8765` and note the HTTPS address it prints. Use Serve with private access.
3. Stop Family Drive. Add an `httpsUrl` field with the exact HTTPS origin to `.runtime/host.json`. Keep the same `data` and `port` values. Restart the launcher.
4. Open the HTTPS address on an approved device and sign in using the account the admin created. Test a guest account before sharing the address. If you use a different reverse proxy, configure it to preserve the request’s Host header and accept request bodies of at least 5 MiB.

[Tailscale Serve setup](https://tailscale.com/docs/features/tailscale-serve), [Tailscale access grants](https://tailscale.com/docs/features/access-control/grants).

## Build the package from source

```powershell
py -3 -m pip install build
py -3 -m build
```

Run the storage-move regression checks with `py -3 -m unittest discover -s tests` after installing the app dependencies.

## Run with a custom host configuration

Install the Python packages into an environment of your choice, then run the same local server.

```powershell
python -m pip install -r requirements.txt
python host.py '.runtime/host.json' --port 8765
```
