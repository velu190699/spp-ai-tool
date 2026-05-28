# Pending Windows Run Readiness

Checklist before running this automation on Windows.

## Windows Runtime Setup

- Install Python 3.9 or newer from python.org.
- Create and activate a virtual environment from the repository root:

```powershell
py -3.9 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

- Run a smoke test:

```powershell
python main.py run --dry-run
```

## Environment Checks

- Confirm the machine can reach `https://www.spp.org`.
- Confirm corporate proxy, TLS inspection, or firewall rules do not block SPP downloads.
- If PowerShell blocks venv activation, update the execution policy according to local IT policy.
- Ensure the app is run from the repository root, or configure the Windows Scheduled Task `Start in` field to the repo path.

## Scheduling

- Scheduling is not implemented in code.
- If using Windows Task Scheduler later, configure:
  - Program: path to `.venv\Scripts\python.exe`
  - Arguments: `main.py run`
  - Start in: repository root path

## Future Integrations

- Real SharePoint upload is pending.
- Microsoft Graph auth mode is still undecided.
- Real Slack delivery is pending.
- PCI stakeholder routing is pending.
- Stakeholder/division/market mapping is pending.

## Optional Browser Automation

The current v1 flow uses HTTP discovery and downloads, not Playwright browser automation.

If visible-browser SPP automation is needed later on Windows, install Chromium:

```powershell
playwright install chromium
```
