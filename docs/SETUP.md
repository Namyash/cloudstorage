# Set up SpareDrive on Windows

The **host** is the PC with the drive attached. The **admin** sets up SpareDrive on that PC, chooses how much storage each person can use, and creates accounts. Everyone else signs in with a browser.

**Setup order**  
Install on the host → start SpareDrive → create the admin → assign space → add people → test an upload → enable internet access if needed.

## 1. Prepare the host and drive

- Use a Windows PC with Python 3.10 or newer. Use the official Windows download if Python is missing. [Python for Windows](https://www.python.org/downloads/windows/)
- Connect the spare HDD, SSD, or USB drive. Open **File Explorer → This PC** and check that Windows gives it a drive letter, such as `D:`. Leave free space for your data. SpareDrive keeps 512 MiB of disk space in reserve.
- Create a dedicated install folder, for example `D:\SpareDrive`. The installer can use the Windows system drive with your confirmation. The examples use `D:` for the external drive. Use the letter shown on your PC.
- Connect the host to the internet for the installation so it can download the release and its Python dependencies.

## 2. Install and start SpareDrive

1. Open the latest Windows release and expand **Assets**. Download **Install-SpareDrive.cmd** into the folder you made. [Latest SpareDrive release](https://github.com/Namyash/cloudstorage/releases/latest)
2. Double-click the file. Confirm the install folder when prompted. The installer downloads and verifies the matching wheel, then installs SpareDrive in its own Python environment.
3. To finish local setup first, answer **No** when asked to set up internet access. Then answer **Yes** to **Start SpareDrive now?**. To start it later, double-click **Start-SpareDrive.cmd** in the install folder. You can also choose internet setup immediately and complete the admin setup when the second terminal opens.
4. Keep the server terminal open. On the host PC, open the address it prints, usually `http://127.0.0.1:8765/`.

The install folder contains these files and folders.

| Location | Purpose |
| --- | --- |
| `Start-SpareDrive.cmd` | Start the SpareDrive server. |
| `Configure-Internet-Access.cmd` | Set up or reconnect internet access. |
| `Install-SpareDrive.cmd` | The Windows installer. Use the installer from a newer release when upgrading. |
| `.sparedrive\host.json` | Remembers the active data folder, port, and optional HTTPS address. |
| `.sparedrive\program\` | Installed program and Python dependencies. |
| `.sparedrive\data\` | Default household data folder for a new installer setup. After a storage move, check **Overview** or **Storage explorer** for the active folder. |

To see the hidden `.sparedrive` folder, enable **Hidden items** in File Explorer.

## 3. Create the first admin

1. If you see **Set up SpareDrive**, continue to the admin form. A new installer setup normally prepares the storage folder inside the installation for you.
2. If **Storage explorer** opens first, enter the **setup code** from the running terminal to unlock it. Click **Browse** on the desired drive and choose a new or empty dedicated folder. Select **Include the Windows system drive** if you intend to use it.
3. On **Set up SpareDrive**, enter the current setup code from the same terminal, your display name, a username, and a password you choose. Click **Create admin account**.
4. In **Overview**, confirm the storage path and the available space.

The **setup code** authorizes first-run actions on the host. SpareDrive prints a fresh code when the server restarts. Your **sign-in password** is what you use for your account after setup. Keep both private.

## 4. Give people access and storage

1. In **People & access**, open **Manage account** for your admin account and set a personal quota for **My files**. New household quotas start at zero.
2. Open **Family space → Set storage quota** and assign space for shared files. The Family space quota is shared by everyone with access.
3. Click **Add person**. Enter a display name, an initial username, a role, and a personal storage quota.
   - **Family member** can have a private vault and join **Family space** if **Allow Family space access** is selected.
   - **Guest** can have a private vault. Choose **Enable a shared folder for this guest** to let the guest and admin use **Guest exchange**. You can also set an expiry.
4. Give each person their initial username and the generated temporary password privately. On first sign-in, they can choose their own username and must replace the temporary password.
5. To change or revoke access later, open **People & access → Manage account**. Use **Allow sign-in** to pause or restore the account, or use the space-specific control to change shared access.

A quota is an upload limit. For example, 10 GB for Family space and 5 GB for one personal account assigns 15 GB of the household's capacity. Disk usage grows as people upload. Check both **Assigned storage** and **Free on disk** in Overview. Trash and archived vault files still count toward storage until permanently removed.

## 5. Try everyday file management

1. Open **Family space**, choose **New folder**, then upload a small file into it. Watch the upload progress and download the file to confirm it opens.
2. Open **My files** to set up a private vault. Choose a separate vault passphrase of at least 16 characters and save the recovery key. The browser uses the vault passphrase to unlock encrypted names and file contents. For private downloads over 256 MiB, use a desktop browser with a file-save picker, such as Chrome or Edge.
3. Use the file menu to rename, move, copy, preview, or download supported items. Use **Trash** to restore something you removed or **Delete forever** to free its storage. Shared files are protected by account permissions. The host operator should be someone the household trusts.
4. Test with a family or guest account before sharing access more widely. Verify that the account can see only the spaces the admin intended it to use.

Use **Account** to change your username or password. The sign-in screen's **Change password** form also accepts your current password and new password. An admin can issue a temporary password for a family member or guest in **People & access**.

For a forgotten vault passphrase, open **My files → Forgot vault passphrase? → Use recovery key**. Save the new recovery key if you recover the vault. **Start fresh and keep archive** opens a new vault and preserves the old one in **Archived vaults**. Opening the archived files still requires their original vault passphrase or recovery key.

## 6. Let family members connect from another device

The address starting with `127.0.0.1` opens SpareDrive on the host itself. For devices away from home, run the internet setup wizard on the host and share the HTTPS link it prints.

### Set up the Tailscale HTTPS link

1. Finish local setup and leave SpareDrive running. On the host, open **Configure-Internet-Access.cmd** from the install folder.
2. If the wizard asks you to finish local setup, open the dashboard and press **Enter** in the wizard. If Tailscale is missing, the wizard tries to install it with WinGet. Approve the Windows installer prompt if it appears. If WinGet is unavailable, install Tailscale directly and run the wizard again. [Tailscale for Windows](https://tailscale.com/download/windows)
3. Sign in to Tailscale from the Windows system tray and return to the wizard. Approve **Enable public HTTPS** when you are ready. If Tailscale asks for Funnel authorization, follow the link it prints and approve the device using the tailnet admin account. [Tailscale Funnel setup](https://tailscale.com/docs/features/tailscale-funnel)
4. If the wizard asks for a restart, stop and reopen the **SpareDrive server** using the same launcher. Then return to the **wizard** and press **Enter**. Wait for **SpareDrive HTTPS link**, which ends in `.ts.net`.
5. Test that link from a phone on mobile data. Sign in as a family member, upload a small file, and download it again. Once that works, share the link and privately share the accounts you created.

Funnel makes SpareDrive's sign-in page reachable from the internet. SpareDrive accounts control access to files. The host PC must stay awake and online with SpareDrive running and its selected drive connected. To turn off Funnel, run `tailscale funnel --https=443 off` on the host. [Tailscale Funnel documentation](https://tailscale.com/docs/features/tailscale-funnel)

### Optional Vercel launch page

When the wizard asks **Publish a Vercel launch page linking to SpareDrive?**, choose **Yes** if you want a separate address to share. This step needs a Vercel account and the Vercel CLI or Node.js with `npx` on the host.

1. Enter your Vercel email and complete the sign-in prompt, or press **Enter** if the CLI is already signed in.
2. Enter a short name such as `smith-family` to request `smith-family.vercel.app`, use a domain you control, or press **Enter** for Vercel's default.
3. When the CLI asks, choose your account or team and a dedicated project. Use `./` for the code directory and keep the detected project settings. Custom domains may require DNS changes. [Vercel domain setup](https://vercel.com/docs/domains/working-with-domains/add-a-domain)
4. Open the **Family launch page** URL the wizard prints. Its button opens the SpareDrive HTTPS sign-in page on the home PC. Files still go to your selected household drive.

### Private device access

If everyone who needs access has Tailscale, a tailnet admin can use **Tailscale Serve** with an access policy that permits only the intended users. On the host, run the following command using the actual SpareDrive port, then save the HTTPS origin it prints as `httpsUrl` in the matching host settings file. Leave the existing `data` and `port` settings in place and restart SpareDrive. [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve) · [Tailscale access grants](https://tailscale.com/docs/features/access-control/grants)

```powershell
tailscale serve --bg http://127.0.0.1:8765
```

## Move your household to another drive

1. Connect the destination drive while the current drive is still attached. Check that Windows shows it and that it has enough free space for your household and its assigned quotas.
2. On the host, sign in as admin at the local address. Open **Storage explorer → Move storage**. If you have already browsed the destination, use **Move storage here**.
3. Select a new folder or an existing empty dedicated folder. Review **From** and **To**, enter your admin sign-in password, and click **Copy and switch storage**.
4. Keep both drives connected. SpareDrive pauses household requests, copies and verifies the database and files, and switches to the destination only after verification. Accounts, permissions, quotas, and private vaults move with the data.
5. When the progress panel confirms success, verify the new path in **Overview** and open a file. The previous folder is a backup from the time of the move. If you later move back to the original drive, choose a fresh or empty folder there so it receives the latest data.

SpareDrive uses one active storage folder at a time. If the move fails, review the on-screen error and retry with enough space after any active uploads have finished or been canceled. If the old drive still contains the installed program or its settings, keep it connected to run SpareDrive.

## Restart, upgrade, and back up

- **Restart.** Stop the server with `Ctrl+C`, then launch it again from the same installation with the active drive attached. Normal sign-ins use the same account credentials.
- **Upgrade.** Download the installer from a newer release and run it in the same installation folder. Confirm stopping the running instance if prompted. Start it again and check that **Overview** shows the expected active path. [Windows releases](https://github.com/Namyash/cloudstorage/releases)
- **Back up.** Stop SpareDrive and copy the entire active data folder to a separate drive. Include `family-drive.sqlite3`, `objects/`, and `.family-drive-id`. Keep a copy of the host settings file and store vault recovery keys securely. If storage has moved, use the active path in **Overview** to identify the folder to back up.

## Troubleshooting

| What you see | What to check |
| --- | --- |
| Local page won't open | Start SpareDrive and use the exact address the terminal prints. If it reports an occupied port, close the other SpareDrive instance before starting the intended one. |
| Setup code is rejected | Copy the latest code from the terminal running the server for that browser address. After a restart, reload the page and use the new code. |
| The USB is missing from Storage explorer | Check **File Explorer → This PC** for a drive letter and accessible volume, then click **Refresh drives**. The system-drive checkbox controls whether Windows' own drive can be selected. |
| The active drive is disconnected | Reconnect the correct drive. If Windows changed its letter, SpareDrive looks for the same household. If it stays offline, unlock Storage explorer with the terminal code, browse to the original household folder, and choose **Reconnect this folder**. |
| The site shows an existing admin | Check the installation and active storage path. An existing household opens with its saved accounts. A fresh household uses a separate new or empty storage folder. |
| Upload or migration reports insufficient space | Check the personal or shared quota and the physical drive's free space. For a move, choose a larger drive or reduce unused quota assignments so the destination can fit the household. |
| **Move storage** is unavailable on the shared link | On the host PC, open the local address shown by Storage explorer and sign in as admin there. |
| The remote link stops opening | Check that the host is awake, the drive is connected, and SpareDrive and Tailscale are running. Verify that the local site opens first, then rerun **Configure-Internet-Access.cmd** if needed. |

## Other ways to run SpareDrive

| How you run it | Host settings file used by default |
| --- | --- |
| Windows installer shortcuts | `<install folder>\.sparedrive\host.json` |
| Wheel via `python -m family_drive` | `%LOCALAPPDATA%\FamilyDrive\host.json` |
| Source via `npm run dev` | `.runtime\host.json` inside the project folder |

For the **wheel**, use the wheel filename and command listed in the matching GitHub release. After installing, run `python -m family_drive`. In a second terminal with the same Python environment, use `python -m family_drive.remote_setup` for internet access. [Release download and wheel command](https://github.com/Namyash/cloudstorage/releases/latest)

For the **source checkout**, open PowerShell in the repository. With Python and Node.js with npm installed, start the server. After creating the admin, run the internet wizard in a second PowerShell window in that same folder if you want remote access.

```powershell
npm run dev
```

```powershell
python -B -m backend.remote_setup --config .runtime\host.json
```

Keep using the same launcher and settings file for the household you set up. [Back to the project README](../README.md)
