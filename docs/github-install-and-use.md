# Beginner Guide: Install Alfred From GitHub

This guide is for someone who has never used Git, Python, Docker, Terminal, or
PowerShell. Follow the section for your computer and do the steps in order.

Alfred is the GitHub project. The application currently displays the product
name **OM Automate** in parts of its interface. Those names refer to the same
installation in this guide.

## The short version

You install one prerequisite—Docker Desktop—then download and double-click the
Alfred installer from GitHub.

You do **not** need to:

- type `git clone`;
- install Python;
- install Homebrew;
- change file permissions with `chmod`;
- find the correct project folder in Terminal; or
- build a Docker image on your computer.

The installer does not install Docker Desktop for you. Docker is a privileged
system application and must be installed through its normal, visible installer.

## Before you start

Check that you have:

1. A 64-bit Mac or Windows computer.
2. The password or approval needed to install normal applications.
3. A reliable internet connection.
4. At least 20 GB of free disk space. Local AI models can require much more.
5. Time for a first download that may take several minutes.

Alfred itself opens in a web browser, but it runs locally on your computer.
With the default settings, other computers cannot connect to it.

## A few useful words

- **GitHub** is the website that stores Alfred's project files and releases.
- **Release** is a named, packaged version of Alfred.
- **ZIP** is a compressed folder. You extract it before using its files.
- **Docker Desktop** runs Alfred and its helper services in containers.
- **Container** is an isolated package containing software and dependencies.
- **Installer window** is the Terminal or Command Prompt window opened by the
  downloaded installer. You do not need to type commands into it.
- **`.env`** is the private settings file for your installation.
- **Private data directory** stores accounts, memories, skills, calendar data,
  documents, and other Alfred state.
- **Local address** `http://127.0.0.1:7000` means Alfred on this computer only.

## Install on a Mac

### Step 1: Check your macOS version and free space

1. Click the Apple menu in the top-left corner.
2. Choose **About This Mac** to see the macOS version.
3. Open **System Settings → General → Storage** to check free space.

Both Apple Silicon Macs (M-series) and Intel Macs can use the Docker route.
Apple Silicon users who later want maximum local-model performance can read the
advanced native-install section in the main README.

### Step 2: Install Docker Desktop

1. Open [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/).
2. Download the correct Mac version. The Docker page normally detects your Mac.
3. Open the downloaded Docker installer.
4. Move Docker into Applications if asked.
5. Open **Docker** from Applications.
6. Accept Docker's licence and system prompts.
7. Wait until Docker says its engine is running.

Leave Docker Desktop open. Alfred needs the Docker engine, although you can
close the main Docker window after it has started.

### Step 3: Download the Alfred installer

1. Open the [latest Alfred release](https://github.com/OriginMediaIE/Alfred/releases/latest).
2. Scroll to the **Assets** section.
3. Click `Alfred-macOS-Installer.zip`.
4. Wait for the download to finish.
5. Open your **Downloads** folder.
6. Double-click `Alfred-macOS-Installer.zip` to extract it.

You should now see `Install-Alfred.command`.

### Step 4: Run the installer

1. Double-click `Install-Alfred.command`.
2. If macOS displays a security question, choose **Open**.
3. If macOS says it cannot verify the developer:
   - Control-click `Install-Alfred.command`;
   - choose **Open**; and
   - choose **Open** again.
4. A Terminal window opens and displays each installation step.
5. Do not close that window while files are downloading.

The installer checks Docker, downloads the selected Alfred release, pulls the
published Docker images, starts the services, waits for a readiness check, and
opens the app.

### Step 5: Record the first login

On a completely clean installation, the installer prints something similar to:

```text
First login
  Username: admin
  Temporary password: randomly-generated-value
```

Write down or copy the temporary password before closing the window. It is
randomly generated; it is not `AdminPass` and the normal public installer does
not use `Admin` / `Admin`.

### Step 6: Open Alfred

The installer normally opens:

[http://127.0.0.1:7000](http://127.0.0.1:7000)

It also creates:

```text
~/Applications/Alfred.app
```

The installer attempts to add Alfred to the Dock. If it cannot, open your
personal Applications folder, drag `Alfred.app` to the Dock, and click it to
start Alfred later.

### Step 7: Finish the account setup

1. Sign in with username `admin` and the displayed temporary password.
2. Open **Settings**.
3. Open **Account**.
4. Choose a strong new password.
5. Store it in a password manager.
6. Enable two-factor authentication if it is available for your setup.

Your Mac installation lives here:

```text
~/Library/Application Support/Alfred
```

Private application data lives here:

```text
~/Library/Application Support/Alfred/data
```

## Install on Windows

### Step 1: Check Windows and free space

1. Open **Settings → System → About**.
2. Confirm that the system type is 64-bit.
3. Open **Settings → System → Storage**.
4. Confirm that at least 20 GB is free.

### Step 2: Install Docker Desktop

1. Open [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/).
2. Download Docker Desktop.
3. Run the installer.
4. Keep the recommended WSL 2 option unless your administrator requires a
   different setup.
5. Restart Windows if the installer asks you to.
6. Open **Docker Desktop** from the Start menu.
7. Accept Docker's licence and system prompts.
8. Wait until Docker says the engine is running.

Leave Docker Desktop running while you install Alfred.

### Step 3: Download and extract the Alfred installer

1. Open the [latest Alfred release](https://github.com/OriginMediaIE/Alfred/releases/latest).
2. Scroll to **Assets**.
3. Click `Alfred-Windows-Installer.zip`.
4. Open your **Downloads** folder.
5. Right-click the downloaded ZIP and choose **Extract All**.
6. Open the extracted folder.

You should see both of these files:

```text
Install-Alfred.cmd
Install-Alfred.ps1
```

Keep the files together. The `.cmd` file starts the PowerShell installer.

### Step 4: Run the installer

1. Double-click `Install-Alfred.cmd`.
2. If Microsoft Defender SmartScreen appears, confirm that the file came from
   `github.com/OriginMediaIE/Alfred`, choose **More info**, then **Run anyway**.
3. A Command Prompt window opens.
4. Do not close it while the installer is downloading or starting services.

If your organisation blocks PowerShell scripts, ask its administrator to allow
this project script or use the documented source installation. Do not disable
organisation-wide security controls.

### Step 5: Record the first login

On a new installation, record the username and temporary password printed in
the installer window:

```text
Username: admin
Temporary password: randomly-generated-value
```

Press a key to close the installer only after you have recorded this password.

### Step 6: Open Alfred and change the password

1. Open [http://127.0.0.1:7000](http://127.0.0.1:7000).
2. Sign in as `admin` with the temporary password.
3. Open **Settings → Account**.
4. Set a strong new password and store it safely.

The installer creates an **Alfred** shortcut on the Desktop and in the Start
menu. To put it on the taskbar, right-click the shortcut and choose **Pin to
taskbar**.

Your Windows installation lives here:

```text
%LOCALAPPDATA%\Alfred
```

Private application data lives here:

```text
%LOCALAPPDATA%\Alfred\data
```

## What to expect on the first run

The first run is slower than later starts because Docker downloads several
images. The installer displays these stages:

1. Checking Docker Desktop.
2. Choosing an Alfred release.
3. Downloading Alfred from GitHub.
4. Installing Alfred without replacing private data.
5. Pulling the published Docker images.
6. Starting Alfred, ChromaDB, SearXNG, and ntfy.
7. Waiting for Alfred's readiness check.
8. Creating a Mac app or Windows shortcut.

Download time depends on internet speed and whether Docker already has some of
the image layers.

## Start Alfred again later

### Mac

1. Open Docker Desktop if it is not already running.
2. Click **Alfred** in the Dock or open `~/Applications/Alfred.app`.
3. Wait for the browser to open.

### Windows

1. Open Docker Desktop if it is not already running.
2. Double-click the **Alfred** Desktop shortcut or choose Alfred from Start.
3. Wait for the browser to open.

If the browser does not open automatically, visit
[http://127.0.0.1:7000](http://127.0.0.1:7000).

## Stop Alfred

Opening and closing the browser does not stop the containers.

For an occasional personal installation, leaving the containers running with
Docker Desktop is normally fine. To stop them deliberately:

1. Open Docker Desktop.
2. Open **Containers**.
3. Find the Alfred/OM Automate group.
4. Click its **Stop** button.

Do not click a delete-volume option. Docker volumes can contain supporting
search and notification state.

## Update Alfred

Before an important update, create and verify an encrypted backup from Alfred's
backup tools.

Then:

1. Download the newest installer ZIP from the
   [latest release](https://github.com/OriginMediaIE/Alfred/releases/latest).
2. Extract it.
3. Run the installer exactly as before.

The installer updates application files and images while preserving:

- `.env`;
- the `data` directory;
- the `logs` directory;
- accounts and passwords;
- memories and skills;
- calendar and task records;
- uploaded documents; and
- application settings.

Never treat an upgrade as your only copy of important personal data. Keep a
verified backup outside the installation folder.

## Uninstall Alfred

There are two different choices.

### Remove the app but keep private data

1. Stop the Alfred containers in Docker Desktop.
2. Remove the Alfred app/shortcut.
3. Keep the Alfred installation folder listed above.

You can reinstall later and reuse that data.

### Permanently erase Alfred and its data

This is destructive. First export anything you want to retain and verify the
export. Then remove the Alfred containers, application folder, private `data`
folder, and Alfred-specific Docker volumes. Do not remove Docker volumes unless
you are certain which volumes belong to Alfred.

## Common problems

### “Docker is required”

Docker Desktop is not installed or the `docker` command is not available.
Install Docker Desktop from its official website, open it, wait for the engine,
then rerun the Alfred installer.

### Docker is installed but did not become ready

1. Open Docker Desktop manually.
2. Look for an error in the Docker window.
3. Restart Docker Desktop.
4. Restart the computer if Docker requests it.
5. Run the Alfred installer again.

### macOS will not open `Install-Alfred.command`

Control-click the file, choose **Open**, and confirm **Open** again. Download
installer files only from the official Alfred repository release page.

### Windows SmartScreen blocks the installer

Check that the ZIP came from `github.com/OriginMediaIE/Alfred`. Choose **More
info → Run anyway** only when that source is correct. The release artifacts are
not yet code-signed with a commercial Windows certificate.

### The page does not open

Try [http://127.0.0.1:7000](http://127.0.0.1:7000) directly. In Docker Desktop,
confirm that the Alfred containers are running rather than stopped or failed.

### Port 7000 is already used

Open the private `.env` file inside the Alfred installation folder. Add or
change this line:

```dotenv
APP_PORT=7001
```

Run Alfred again, then open
[http://127.0.0.1:7001](http://127.0.0.1:7001).

### I lost the temporary password

Open a terminal in the Alfred installation folder and view the application
logs:

```bash
docker compose logs odysseus
```

Look for the latest `Temporary password` line. If the password was already
changed, use the application's supported account-recovery process; do not
delete `data/auth.json` to force a new account.

### No AI model is available

The application and an AI model are separate services. Open **Cookbook** or
**Settings → Models**, configure a supported local or hosted model endpoint,
test it, and select it in chat. A model must also support structured tool calls
for agent tools to work.

### A local model on the host cannot be reached from Docker

Inside a container, `localhost` means the container itself. For services such
as Ollama running on the computer, use `host.docker.internal` where Alfred asks
for the host name—for example, `http://host.docker.internal:11434`.

### I need detailed logs

From the installation directory, run:

```bash
docker compose ps
docker compose logs --tail=200 odysseus
docker compose logs --tail=200 chromadb
docker compose logs --tail=200 searxng
```

Remove passwords, tokens, email content, personal file names, and other private
information before sharing logs publicly.

## Advanced source install

Developers who deliberately want a Git checkout can still use:

```bash
git clone https://github.com/OriginMediaIE/Alfred.git
cd Alfred
```

On macOS or Linux:

```bash
./install-om-automate.sh --pull
```

On Windows PowerShell:

```powershell
.\install-om-automate.ps1 -Pull
```

Use the scripts without `--pull`/`-Pull` only when you intentionally want to
build the Docker image from the checked-out source.

## Privacy and safety

- Keep authentication enabled.
- Keep `APP_BIND=127.0.0.1` unless you have deliberately configured
  authenticated HTTPS.
- Never commit or share `.env`.
- Never commit or share the `data` directory.
- Treat calendar, email, shell, model-serving, and file tools as privileged.
- Verify consequential actions in Alfred's audit and approval interfaces.
- Back up important data before updating or removing the installation.
- Download installers only from the official GitHub release page.

Each GitHub release includes `SHA256SUMS.txt`. Advanced users can compare its
hash with the downloaded ZIP before running it.

## Maintainer: publish the installer assets

The repository workflow `.github/workflows/release-installers.yml` attaches the
two installer ZIPs and `SHA256SUMS.txt` whenever a GitHub release is published.
The release should point at a reviewed tag. After publishing, verify that both
ZIPs download, extract, and target that release tag before announcing it to
beginners.
