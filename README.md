# README.md Changes

## Install

Requires Python 3.9+.

### Linux / macOS (Bash)

```bash
cd packages/cli-python
pip install -e ".[pdf]"     # core + PDF export (WeasyPrint) + hybrid-PDF support

# core only
# pip install -e .
```

### Windows (PowerShell)

```powershell
cd packages\cli-python

pip install -e ".[pdf]"

# core only
# pip install -e .
```

Verify installation:

```powershell
hdox --help
```

## 60-second tour

### Linux / macOS (Bash)

```bash
cat > report.md <<'MD'
---
title: Quarterly Review
authors: [Jane Doe]
keywords: [quarterly, review]
---

# Executive summary

Revenue grew **12%**.

| Region | Growth |
| ------ | ------ |
| EMEA   | 9%     |
MD

hdox build report.md -o report.hdox
hdox build report.md -o report.pdf
hdox build report.md -o report.html

hdox validate report.hdox
hdox llm-read report.pdf
```

### Windows (PowerShell)

```powershell
@"
---
title: Quarterly Review
authors: [Jane Doe]
keywords: [quarterly, review]
---

# Executive summary

Revenue grew **12%**.

| Region | Growth |
| ------ | ------ |
| EMEA   | 9%     |
"@ | Set-Content report.md

hdox build report.md -o report.hdox
hdox build report.md -o report.pdf
hdox build report.md -o report.html

hdox validate report.hdox
hdox llm-read report.pdf
```

### Windows PDF Export

PDF export uses WeasyPrint by default.

If you see:

```text
cannot load library 'libgobject-2.0-0'
```

Install the GTK runtime:

```powershell
winget install --id Tschoonj.GTKforWindowsRuntimeEnvironment -e --source winget
```

Restart PowerShell and retry:

```powershell
hdox build report.md -o report.pdf
```
