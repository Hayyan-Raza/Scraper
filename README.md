# Kajabi & Wistia Video Scraper

A robust Python automation tool designed to securely log in to Kajabi course portals and batch download Wistia-hosted videos locally, preserving the course's exact Module-Lesson folder hierarchy. Built with `playwright` and `playwright-stealth` to emulate real users and navigate complex, dynamically loaded portals.

## Features
- **Hierarchical Structure**: Scrapes the DOM syllabus and neatly folders your videos into `downloads/0X_ModuleName/0X_Lesson.mp4` structures. 
- **Wistia Stream Extraction**: Supports bypassing raw Wistia asynchronous wrappers and classic iFrame embeds to locate the direct `.mp4` stream securely.
- **Session Persistence**: Maintains your Chrome login cache to avoid repetitive login hurdles and 2FA loops.
- **Stealth Emulation**: Employs `playwright-stealth` mechanisms, dynamic networkidle pauses, and variable timing to mimic human scraping and bypass bot detection.
- **Scrapes Pagination**: Dynamically handles discovering hidden lessons within standard Kajabi pagination logic.

## Prerequisites
Ensure you have **Python 3.7+** installed.

Install the required modules:
```bash
pip install -r requirements.txt
playwright install chromium
```

## Setup & Configuration

1. **Credentials:**  
   Create a `.env` file in the root directory and provide your login details. This keeps your credentials decoupled from the codebase:
   ```env
   USER_EMAIL="your_email@example.com"
   USER_PASSWORD="your_password"
   ```

2. **Configure Target:**  
   Open `scraper.py` and modify the `TARGET_URL` variable if you'd like to target a different Kajabi syllabus.

## Usage

By default, the script safely runs in **Test Mode**. Test mode will load the portal, perform the extraction routines, download one single sequence file, and then safely exit.

```bash
python scraper.py
```

To run a **full pass** of the course (automatically overrides the test mode setting):
```bash
python scraper.py --full
```

If you only want to download a specified chunk of videos (e.g. 50 videos):
```bash
python scraper.py --full --limit 50
```

## Disclaimer
This project is for educational and temporary personal archiving purposes. Users are responsible for securely handling their credentials, adhering to any website Terms of Service, and navigating copyright standards for the portal being scraped.
