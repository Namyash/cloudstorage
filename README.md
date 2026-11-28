# SpareDrive

SpareDrive turns spare storage connected to a Windows PC into a private file service for your household. The administrator chooses the storage folder, creates family and guest accounts, and assigns upload limits. Everyone uses a web browser to manage the files they have access to.

[Download the Windows installer](https://github.com/Namyash/cloudstorage/releases/latest) · [Follow the setup guide](docs/SETUP.md)

## How it works

```text
Family member's browser
        ↓
SpareDrive running on your Windows PC
        ↓
Selected storage folder on your hard drive, SSD, or USB drive
```

Start on the Windows PC that hosts the drive. To let people sign in from elsewhere, the internet setup wizard gives that PC an HTTPS address using Tailscale Funnel. The optional Vercel launch page links to that address. The home PC handles accounts and uploads, and the files are saved on the selected drive. For access away from home, keep the PC awake, SpareDrive running, and the drive connected.

| Feature | What your household can do |
| --- | --- |
| **My files** | Store personal files in a vault. The browser encrypts file names and contents before uploading. |
| **Family space** | Use a shared file space with family accounts that the admin has granted access. |
| **Guest exchange** | Give a guest their own account and quota, with an optional shared folder and expiry. |
| **File management** | Create folders, upload files, search, sort, rename, move, copy, and restore items from Trash. |
| **Storage explorer** | See connected drives and move the whole household to a new or empty folder on another drive. |

## Start here

1. On the host PC, install Python 3.10 or newer. Connect the drive you want to use and confirm it appears in File Explorer. [Python for Windows](https://www.python.org/downloads/windows/)
2. Create a dedicated folder for SpareDrive. Download **Install-SpareDrive.cmd** from the latest release's **Assets** into that folder and double-click it. [Latest Windows release](https://github.com/Namyash/cloudstorage/releases/latest)
3. Start SpareDrive and open the address printed in its terminal, usually `http://127.0.0.1:8765/`. Use the printed setup code to create the first admin account.
4. Set storage quotas, add family members, and test an upload. Run **Configure-Internet-Access.cmd** when you are ready to share an HTTPS link. [Step-by-step setup guide](docs/SETUP.md)

For details on moving to a larger drive or getting back online when a drive is unplugged, see the [storage move instructions](docs/SETUP.md#move-your-household-to-another-drive) and [troubleshooting guide](docs/SETUP.md#troubleshooting).

## Run or build from source

From the repository root, run the source launcher with Python 3.10 or newer and Node.js with npm. On Windows, `Start-Family-Drive.cmd` also runs the source launcher.

```powershell
npm run dev
```

| Path | Purpose |
| --- | --- |
| [frontend/](frontend/) | Browser pages, styles, file management UI, and private vault encryption. |
| [backend/](backend/) | Python web service, accounts, file and quota APIs, drive discovery, migration, and internet setup. |
| [installer/](installer/) | Source for the one-file Windows installer. |
| [tests/](tests/) | Regression tests for accounts, access, files, storage moves, and internet setup. |
| [ci/](ci/) | Jenkins checks, packaging, and release automation. |

Use a Python environment for development and install the dependencies before running the tests.

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests
python -m pip install build
python -m build
```

Install the built wheel by its actual filename. For example, the source version builds `family_drive-0.2.1-py3-none-any.whl`.

```powershell
python -m pip install .\dist\family_drive-0.2.1-py3-none-any.whl
python -m family_drive
```

For a custom host settings file or port, run `python -m backend.host_server '.runtime/host.json' --port 8765` with the project dependencies installed. The port argument applies when starting with a new settings file.

### Automated releases

The Jenkins multibranch pipeline checks pull requests and publishes tested builds from `main`. It runs source checks and unit tests, verifies and smoke-tests the wheel, and tests the generated installer. The GitHub release includes the wheel, `Install-SpareDrive.cmd`, and `SHA256SUMS.txt`. The pipeline advances the patch version from the latest release tag and uses the Jenkins credential `github-cloudstorage-credentials` to publish. [Pipeline](ci/Jenkinsfile) · [Jenkins setup](ci/jenkins/README.md)
