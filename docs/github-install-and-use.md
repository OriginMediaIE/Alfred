# Beginner Guide: Install And Use OM Automate From GitHub

This guide is written for someone who has never installed a project from GitHub
before. It explains what to click, what to type, and why each step matters.

OM Automate is an app that runs on your own computer. You open it in a web
browser, but your private app data is stored locally on your machine unless you
choose to connect outside services.

## The Easiest Choice

If you are giving this to an internal Apple Silicon Mac tester, use the
one-click installer:

1. Build the installer on your Mac.
2. Send the tester `dist/OM Automate Internal Test.dmg`.
3. The tester opens the file and double-clicks `Install OM Automate.command`.
4. The app opens.
5. The tester logs in with:

```text
Username: Admin
Password: Admin
```

That internal installer is explained later in this guide.

If the user is installing from GitHub themselves, Docker is usually the simplest
path because it keeps most of the technical parts inside one container system.

## Words You Will See

- **GitHub**: a website where the project code is stored.
- **Repository**: the project folder on GitHub.
- **Clone**: download the project from GitHub onto your computer.
- **Terminal**: an app where you type commands. On macOS it is called
  Terminal. On Windows, use PowerShell.
- **Docker**: a tool that runs the app in a controlled package.
- **`.env` file**: a private settings file for your copy of the app.
- **Local LLM**: an AI model downloaded and run on your own computer.
- **Cookbook**: the OM Automate screen used to download and start local AI
  models.

## Before You Start

You need:

1. A computer running macOS, Windows, or Linux.
2. An internet connection.
3. A modern browser such as Chrome, Edge, Safari, or Firefox.
4. At least 20 GB of free space for the app and a small local AI model. Larger
   models need more space.

You do not need to understand programming to follow this guide. You will copy
and paste a few commands.

## Install Option 1: One-Click Internal Mac Tester Installer

Use this when you are sending the app to a trusted test user inside your
business and they are using an Apple Silicon Mac.

Apple Silicon means a Mac with an Apple chip, such as M1, M2, M3, or M4.

### Step 1: Build The Installer

On the developer Mac, open Terminal inside the project folder and run:

```bash
./scripts/build-internal-macos-test-installer.sh
```

What this means:

- `./scripts/...` tells the computer to run the installer-building script.
- The script packages a clean copy of OM Automate.
- It creates a file that a tester can install by double-clicking.

When it finishes, look for:

```text
dist/OM Automate Internal Test.dmg
```

### Step 2: Send The DMG To The Tester

Send this file to the tester:

```text
dist/OM Automate Internal Test.dmg
```

The file is a Mac installer disk image. A `.dmg` file is a common macOS package
format.

### Step 3: Tester Opens The Installer

The tester should:

1. Double-click `OM Automate Internal Test.dmg`.
2. Double-click `Install OM Automate.command`.
3. Wait for the installer window to finish.
4. Let the app open automatically.

What the installer does:

- Copies the app to `~/Library/Application Support/OM Automate/app`.
- Creates `~/Applications/OM Automate.app`.
- Preserves existing app data if the tester installs again later.
- Starts OM Automate.

### Step 4: Tester Logs In

Use:

```text
Username: Admin
Password: Admin
```

Important:

- This login is only for the internal test installer.
- It is intentionally easy for testing.
- Change it after testing in **Settings > Account**.

### Step 5: Tester Follows The Onboarding

After login, OM Automate opens Cookbook. Cookbook helps the tester:

1. Search for a local AI model.
2. Download the model.
3. Start serving the model.
4. Select the model in chat.
5. Send a first request.
6. Turn Web Search on or off.
7. Create memories and skills.
8. Ask the AI to use those memories.

## Install Option 2: Beginner Docker Install From GitHub

Use this if the user is installing the project themselves from GitHub.

Docker is recommended for beginners because it handles many app dependencies
for you.

## Part A: Install The Basic Tools

### Step 1: Install Git

Git is the tool that downloads the project from GitHub.

Download Git here:

```text
https://git-scm.com/downloads
```

After installing Git, restart Terminal or PowerShell.

### Step 2: Install Docker

Docker runs OM Automate in a packaged environment.

Download Docker Desktop here:

```text
https://www.docker.com/products/docker-desktop/
```

After installing Docker:

1. Open Docker Desktop.
2. Wait until it says Docker is running.
3. Leave Docker Desktop open.

### Step 3: Open The Command App

On macOS:

1. Press `Command + Space`.
2. Type `Terminal`.
3. Press `Enter`.

On Windows:

1. Click Start.
2. Type `PowerShell`.
3. Open PowerShell.

On Linux:

Open your Terminal app.

## Part B: Download The Project

### Step 1: Choose A Folder

This command moves you to your home folder:

```bash
cd ~
```

What this means:

- `cd` means "change directory".
- `~` means your personal home folder.
- The project will be downloaded inside that area.

### Step 2: Clone The GitHub Repository

Replace `<GITHUB_REPOSITORY_URL>` with the real GitHub URL before publishing
this guide.

```bash
git clone <GITHUB_REPOSITORY_URL> om-automate
```

What this means:

- `git clone` downloads a copy of the project.
- `<GITHUB_REPOSITORY_URL>` is the GitHub address.
- `om-automate` is the folder name that will be created on your computer.

### Step 3: Enter The Project Folder

```bash
cd om-automate
```

What this means:

- You are moving into the project folder.
- The next commands must be run from inside this folder.

## Part C: Create The Private Settings File

Run:

```bash
cp .env.example .env
```

What this means:

- `.env.example` is a safe example settings file.
- `.env` is your private settings file.
- The app reads `.env` when it starts.

Important:

- Do not upload `.env` to GitHub.
- Do not share `.env` publicly.
- It may contain passwords, API keys, or private settings later.

For a normal local install, these settings are safe:

```dotenv
AUTH_ENABLED=true
LOCALHOST_BYPASS=false
APP_BIND=127.0.0.1
APP_PORT=7000
```

What these mean:

- `AUTH_ENABLED=true` means users must log in.
- `LOCALHOST_BYPASS=false` means login is not skipped.
- `APP_BIND=127.0.0.1` means the app is only available on your own computer.
- `APP_PORT=7000` means the app opens at port 7000 in your browser.

## Part D: Start The App With Docker

### Step 1: Check The Setup

On macOS or Linux, run:

```bash
./install-om-automate.sh --check
```

On Windows PowerShell, run:

```powershell
.\install-om-automate.ps1
```

What this means:

- The macOS/Linux check looks for Docker and required settings.
- The Windows command starts the installer script.
- If Docker is not running, open Docker Desktop and try again.

### Step 2: Install And Start

On macOS or Linux, run:

```bash
./install-om-automate.sh
```

On Windows, if you did not already run the PowerShell command above, run:

```powershell
.\install-om-automate.ps1
```

What this means:

- Docker builds the OM Automate app.
- Docker starts the app and helper services.
- The script waits until the app is ready.

This may take several minutes the first time.

### Step 3: Open The App

Open this address in your browser:

```text
http://127.0.0.1:7000
```

What this means:

- `127.0.0.1` means "this computer".
- `7000` is the app port.
- The app is not public on the internet with this default setup.

## Part E: First Login

The first time OM Automate starts, it creates an administrator account.

If the installer prints a username and password, use those to log in.

If you missed the password, run:

```bash
docker compose logs odysseus
```

What this means:

- `docker compose logs` shows messages from the running app.
- `odysseus` is the app service name inside Docker.
- The first-login password may be shown there.

After you log in:

1. Open **Settings**.
2. Open **Account**.
3. Change the temporary password.
4. Save the new password somewhere safe.

Important:

- Normal GitHub installs do not use `Admin` / `Admin`.
- `Admin` / `Admin` only works in the special internal Mac test installer.

## Part F: Download Your First Local AI Model

### Step 1: Open Cookbook

In OM Automate, click **Cookbook**.

Cookbook is where you find, download, and start local AI models.

### Step 2: Search For A Model

Search for a small beginner-friendly model first.

Why:

- Small models download faster.
- Small models are easier for a computer to run.
- Large models may need much more memory and disk space.

### Step 3: Download The Model

Click the download option for the model.

Wait until the download finishes. This can take a while.

### Step 4: Start The Model

Click **Serve** or **Start**.

What this means:

- The model is now running on your computer.
- OM Automate can send chat requests to it.

### Step 5: Use The Model In Chat

Go back to chat and select the new model in the model picker.

Try this message:

```text
Explain what OM Automate can help me do in five simple bullet points.
```

If the model responds, the local AI setup is working.

## Part G: Use The Web Search Switch

In chat, OM Automate has a Web Search switch.

When Web Search is **off**:

- The AI does not intentionally search the internet for that request.
- It uses the prompt, local context, selected files, and enabled memories.

When Web Search is **on**:

- The AI can use internet search through the configured search service.
- Use this for current information, recent events, or things that may have
  changed.

Beginner rule:

- Leave Web Search off for private or offline work.
- Turn Web Search on only when you want the AI to look something up.

## Part H: Create Memories

Memories are saved facts or preferences that OM Automate can use later.

### Step 1: Open Brain

Click **Brain**.

Brain is where memories and skills are managed.

### Step 2: Add A Memory

Create a memory like:

```text
My internal test notes should be short, plain-English, and include clear
acceptance criteria.
```

What this means:

- You are teaching OM Automate a preference.
- Later, chat can use that preference when answering.

### Step 3: Enable Memory Context

Turn on memory context if it is not already on.

What this means:

- OM Automate is allowed to include saved memories in chat context.
- Turn it off when you do not want memories used.

### Step 4: Test The Memory

Ask:

```text
Draft test notes for the local LLM onboarding flow using my saved preference.
```

If the answer is short, plain-English, and includes acceptance criteria, the
memory is working.

## Part I: Create Skills

Skills are reusable instructions for tasks you do often.

Example skill:

```text
Title: Internal test note writer
When to use: Use when writing notes for internal QA or test users.
How: Keep the notes short, plain-English, and include acceptance criteria.
Tags: testing, QA, internal
```

What this means:

- A memory is usually a fact or preference.
- A skill is more like a reusable mini-process.
- Skills help the AI repeat a task in a consistent way.

## Stop And Restart The App

### Docker

To stop the app:

```bash
docker compose stop
```

To start it again:

```bash
docker compose up -d
```

What this means:

- `stop` pauses the running app containers.
- `up -d` starts them again in the background.

### Apple Silicon Native

If you started the app with:

```bash
./start-macos.sh
```

Stop it by pressing `Ctrl+C` in the Terminal window that is running it.

Start it again with:

```bash
./start-macos.sh
```

## Common Problems

### Docker Is Not Running

Open Docker Desktop and wait until it says Docker is running. Then try the
install command again.

### The Browser Page Does Not Open

Manually open:

```text
http://127.0.0.1:7000
```

### Port 7000 Is Already In Use

Open `.env` and change:

```dotenv
APP_PORT=7001
```

Then restart the app.

What this means:

- Only one app can use a port at a time.
- Changing to `7001` gives OM Automate a different local address.

### I Cannot Find The Login Password

Run:

```bash
docker compose logs odysseus
```

Look for the first admin login message.

### The Local AI Model Is Too Slow

Try a smaller model.

Why:

- Local AI models use your computer's memory and processor.
- Bigger models are smarter in some cases, but they need stronger hardware.

### Web Search Does Not Work

Check:

1. Docker is running.
2. The app is running.
3. Web Search is switched on in chat.
4. `SEARXNG_INSTANCE` in `.env` points to the search service.

For Docker installs, the default setup starts SearXNG for you.

## Safety Notes

- Keep `.env` private.
- Do not commit `.env` to GitHub.
- Do not commit the `data/` folder to GitHub.
- Do not publish your local app directly to the internet.
- Keep `AUTH_ENABLED=true`.
- Keep `APP_BIND=127.0.0.1` unless you know exactly why you need network access.
- Change the `Admin` / `Admin` password after internal testing.
- Treat Web Search as permission for the AI to use the internet.
- Treat memories as saved context that can affect future answers.

## Quick Checklist For A Beginner

1. Install Git.
2. Install Docker Desktop.
3. Open Docker Desktop and wait for it to run.
4. Open Terminal or PowerShell.
5. Run `git clone <GITHUB_REPOSITORY_URL> om-automate`.
6. Run `cd om-automate`.
7. Run `cp .env.example .env`.
8. Run the installer script for your system.
9. Open `http://127.0.0.1:7000`.
10. Log in with the first admin credentials.
11. Open Cookbook.
12. Download and start a local model.
13. Select the model in chat.
14. Test Web Search on and off.
15. Add a memory in Brain.
16. Ask chat to use the memory.
