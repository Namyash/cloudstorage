# SpareDrive

SpareDrive is a browser-based file server for a drive connected to your home computer. The same website gives the admin a storage and account dashboard and each family member or guest their own file area.

## Install the Windows package

With Python 3.10 or newer, install the wheel supplied with the release. Then run SpareDrive and open `http://127.0.0.1:8765/`.

```powershell
py -3 -m pip install .\family_drive-0.2.1-py3-none-any.whl
py -3 -m family_drive
```

The installed package also provides the `sparedrive` command. The existing `family-drive` command is also supported. It keeps host settings in `%LOCALAPPDATA%\FamilyDrive\host.json`. The database and file objects go in the storage folder chosen in the browser. The code in the terminal unlocks first-run storage selection and creates the first admin account.

## Start on Windows

1. Open PowerShell in the project folder and run `npm run dev` with Node.js, npm, and Python 3.10 or newer installed. You can also double-click `Start-Family-Drive.cmd` to launch with Python. The launcher installs Flask and Waitress from PyPI on first use.
2. Open `http://127.0.0.1:8765/`. The storage explorer shows physical disks and Windows drive letters, including when no eligible storage drive is attached. Connect your data drive and wait for its drive letter to appear. To use the Windows system drive, explicitly select **Include the Windows system drive**.
3. Enter the setup code printed in the terminal, choose **Browse** on your data drive, and create a dedicated storage folder or select an empty one. First-time setup starts a new household. Use the same setup code to create its first admin account on the next screen.
4. On **Overview**, use the pencil next to your admin account to set your personal quota. Open **Family space → Set quota** to assign the household quota. Both start at 0 GB. Use **Add person** to create family or guest accounts and enter their quotas. Send temporary passwords privately so each person can choose their own username and password on the first visit.
5. Keep the host computer and launcher running while people use the drive. `Ctrl+C` stops the server. Start it again with the same launcher and drive attached.

The launcher saves the selected path and storage identity in `.runtime/host.json` inside the application folder. An administrator can open **Storage explorer** in the sidebar to view drive status, capacity, folders, and file details. If the storage drive disconnects, the local site shows an offline page. Reconnect it to resume. SpareDrive checks the connected drives every few seconds, up to two folders deep, and reopens a household it finds there, even on a different drive letter or under a different folder name. If it finds exactly one household and the saved one is missing, it switches to that one and remembers it. If it finds several, it keeps waiting until you pick one in Storage explorer with the terminal setup code. Keep the storage folder together when moving it.

## Change the active drive or folder

On the host computer, sign in as the admin and open **Storage explorer → Change storage location**. Browse to the destination and enter a new folder name and your admin sign-in password. SpareDrive pauses household requests while it copies the database and files, verifies the copied data, and activates the destination. Both drives need to remain connected until the move finishes. The old folder stays on its original drive as a backup. The destination needs enough space for the existing files and assigned quotas. Each household uses one active storage folder.

## Storage and access

- **My files.** Every account has a personal vault. The browser encrypts filenames and file contents before sending them to the drive. Each person sets a separate vault passphrase. Save the recovery key generated during setup. The vault locks after 10 minutes of inactivity or when you leave the vault. A sign-in password reset keeps the original vault passphrase.
- **Family space.** The admin always has access and can grant or revoke access for each member in **People & access → Manage account**. **Allow Family space access** controls shared files. **Allow sign-in** controls the entire account. Existing family members start with shared access enabled. The admin sets a separate shared quota, and the uploader or admin can rename and delete shared files.
- **Guest exchange.** The admin can enable a separate shared folder for a guest, give their account an expiry, or pause their access. Guests have personal storage even when their exchange folder is disabled. A user's own guest-exchange uploads count against that user's quota.
- **Storage limits.** Quotas are in decimal GB. The server reserves space when an upload begins, checks available disk space, and keeps 512 MiB of free disk headroom. Each account can own up to 25,000 files and folders across all spaces, including items in Trash and archived vaults. Private files use a small amount of extra space for encryption. An interrupted upload, such as one from a closed tab, stops counting against the quota once it has made no progress for 30 minutes. SpareDrive clears it the next time anyone starts an upload, removes a folder, changes a quota or an account, or moves storage. Pausing an account, resetting its password, or turning off its Family space or guest-exchange access cancels the uploads it can no longer finish.
- **Drive usage.** The overview shows the storage folder, actual free disk space, total assigned quotas, and the amount you can still allocate. Each household runs its own instance and uses the drive it chooses.

Shared files are stored as ordinary files and protected by account permissions. Private file names and contents are encrypted, while the server has access to account names, file sizes, and timestamps. Trust the host and the website code it serves. Someone who controls that code could replace it to capture passphrases in future sessions. Keep the host and its dependencies updated. Use a separate offline backup of the whole data folder, including the SQLite database and `.family-drive-id`. Stop SpareDrive while making a filesystem copy of the data folder, and test a restore before relying on the drive for your only copy.

For private downloads over 256 MiB, use a desktop browser that supports the file-save picker, such as Chrome or Edge. Smaller private files can download in browsers that support Web Crypto without the picker.

## Manage files

- **Organize.** Select **New folder**, then open the folder to create subfolders. Use the path above the list to go back. Upload files or a folder from the toolbar, or drop files from your computer into the browser. Folder upload keeps the structure of the selected files.
- **Find.** Switch between list and grid views, search the current space, or sort by name, upload date, or size. **Recent** shows files by upload date. **Starred** shows favorites for the signed-in account.
- **Manage.** Use **More actions** to rename, move, copy, or download an item where applicable. To move several items, select them and choose **Move**. You can also drag a file or folder onto another folder within the same space. Select a filename to preview supported images, text, audio, and video. Other formats can be downloaded.
- **Recover.** **Move to Trash** removes an item from the active view and keeps its storage allocated. Open **Trash** to restore an item or choose **Delete forever** to reclaim its space. Deleting a folder forever also removes its contents.
- **Access.** In **My files**, the browser encrypts folder names, filenames, and the file contents. In **Family space** and **Guest exchange**, the owner or admin manages an item. An admin is required to trash or permanently delete a folder containing other people's items. Moves and copies stay within the current space. Archived vaults can be browsed, downloaded, or deleted.

## Manage your sign-in

Open **Account** to change your username or password. From the sign-in screen, **Change password** accepts your username, current password, and new password. If a member or guest forgets their password, the admin can issue a temporary password in **People & access**.

## Recover or reset a private vault

- From **My files**, choose **Forgot vault passphrase?** and **Use recovery key** if you saved one for this vault. Enter it and choose a new passphrase to keep your files in place. Save the new recovery key shown afterward.
- To start fresh, select **Start fresh and keep archive** and confirm with your SpareDrive sign-in password. The original encrypted files move to **Archived vaults**, where they still count toward your quota. To download them, open the archive using its original passphrase or a recovery key saved for that archive. To free that space, select **Delete** next to the archive and confirm with your sign-in password; this permanently removes its files. For an empty vault, the action is **Reset empty vault**.
- With **My files** unlocked, open **Vault security** to change your passphrase or generate a recovery key. This also works for vaults created before recovery keys were available, as long as you know the current vault passphrase.

## Connect family devices over private HTTPS

The default launcher listens only on the host computer. For phones and other computers, the app needs a private HTTPS address so the browser can use Web Crypto. One supported setup path is a private Tailscale Serve proxy. You can also use an existing LAN HTTPS reverse proxy with certificates trusted by your devices.

1. Set up Tailscale on the host and approved clients. Review the tailnet access policy so only the intended users can reach the host’s HTTPS service. The default policy can be broader than that.
2. On the host, start a private proxy with `tailscale serve --bg http://127.0.0.1:8765` and note the HTTPS address it prints. Use Serve with private access.
3. Stop SpareDrive. Add an `httpsUrl` field with the exact HTTPS origin to `.runtime/host.json`. Keep the same `data` and `port` values. Restart the launcher.
4. Open the HTTPS address on an approved device and sign in using the account the admin created. Test a guest account before sharing the address. If you use a different reverse proxy, configure it to preserve the request’s Host header and accept request bodies of at least 5 MiB.

[Tailscale Serve setup](https://tailscale.com/docs/features/tailscale-serve), [Tailscale access grants](https://tailscale.com/docs/features/access-control/grants).

## Open SpareDrive from the internet

1. On the Windows host, start SpareDrive, select a dedicated folder on your data drive, and create your administrator account.
2. The internet setup wizard installs Tailscale through WinGet if it is missing on the Windows host. Approve the installation if Windows prompts, then sign in to Tailscale. A tailnet administrator must authorize the device to use [Funnel](https://tailscale.com/docs/features/tailscale-funnel). Family members can use a browser.
3. Run `sparedrive-remote` in the environment where you installed the wheel. Pass `--config "C:\path\to\host.json"` if you start SpareDrive with a custom settings file. The local test installer also offers the wizard after installation and creates `Configure-Internet-Access.cmd` in the installation folder.
4. Confirm the public HTTPS address. If the wizard saves a new address, restart SpareDrive as requested. Share the verified link with household members after creating their accounts. Test sign-in, uploads and downloads from a phone on mobile data.
5. To publish an optional launch page, install Node.js with npx or use the Vercel CLI. Enter your Vercel email or use an existing CLI session, complete Vercel verification, and choose a launch-page address and a dedicated project. Enter a name like spare-smith for spare-smith.vercel.app, an existing domain you own like drive.example.com, or press Enter for Vercel’s default address. Your own domain may require DNS changes in the project’s Domains tab. Share the verified launch-page URL printed by the wizard.

Funnel makes the SpareDrive sign-in page publicly reachable. SpareDrive accounts and permissions control access to files. Vercel serves the launch page. Uploads and downloads go through the tunnel to the selected drive on the Windows host. Keep the PC awake with SpareDrive, Tailscale and the drive available. To turn off public access, run `tailscale funnel --https=443 off` on the host.

Funnel is subject to bandwidth limits. Check [Vercel plan terms](https://vercel.com/docs/limits/fair-use-guidelines) before commercial deployment.

## Build the package from source

The project separates the browser assets and Python service:

```text
frontend/   Browser HTML, CSS, and JavaScript
backend/    Python service
  host_server.py           Launches the website and manages drive setup
  account_and_file_api.py  Accounts, permissions, quotas, and file operations
  drive_discovery.py       Detects drives and validates storage paths
  storage_migration.py     Copies and verifies data during a drive move
tests/      Account, storage, and file management regression tests
ci/         Jenkinsfile and release_tools.py for automated releases
start.py    Source launcher used by npm run dev
```

```powershell
python -m pip install build
python -m build
```

Run the regression checks with `python -m unittest discover -s tests` from the project root after installing the app dependencies. The wheel includes the frontend and still launches with `python -m family_drive`.

## Automated releases

`ci/Jenkinsfile` is a Jenkins Multibranch Pipeline. A pull request is checked only. A push to `main` is checked and then released:

1. Static checks: ruff, a compile of every Python file, a syntax check of the frontend scripts, and a consistency check of `pyproject.toml`, `requirements.txt` and this README.
2. The unit tests on Python 3.10, 3.12 and 3.13.
3. The wheel is built, checked for every packaged file, version, dependency and command, installed into a clean environment, and smoke-tested.
4. The wheel and `SHA256SUMS.txt` are published as a GitHub release `vX.Y.Z`, and the tag is created on the tested commit.

Each release takes the next patch number above the newest `vX.Y.Z` tag. The first release uses the version in `pyproject.toml`. To start a new minor or major version, raise the version in `pyproject.toml`. The Jenkins job needs a token credential named `github-cloudstorage-credentials` with write access to the repository's contents. The header of `ci/Jenkinsfile` lists the job settings and what the build agent needs.

## Run with a custom host configuration

Install the Python packages into an environment of your choice, then run the same local server.

```powershell
python -m pip install -r requirements.txt
python -m backend.host_server '.runtime/host.json' --port 8765
```
