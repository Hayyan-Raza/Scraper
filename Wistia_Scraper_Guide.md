# Wistia/Kajabi Scraper: Technical Walkthrough & Guide

This document breaks down the operations of the `scraper.py` file, explains the inner workings of how the layout structure is gathered, and provides instructions on how to use, configure, and maintain the scraper.

---

## 1. How It Works: The `manifest.json` Builder
Before downloading hundreds of videos blindly, the scraper operates as a "Crawler" to index the entire course map. Here is how it generated the `manifest.json`:

1. **Automated Login & Sandbox:** The script uses **Playwright**—an automated browser framework. It reads your credentials securely from `.env` and uses a stealth-injected Chromium browser to spoof human login actions on the main portal.
2. **Syllabus Parsing:** It navigates to the root course syllabus path (the `TARGET_URL`). Then, the Python script injects a custom block of JavaScript directly into the page.
3. **DOM Navigation Algorithm:** The JavaScript evaluates the page's HTML (DOM structure):
   - It sweeps for all native Kajabi links matching the formula `.../posts/...` (the URL pattern mapped to individual lessons).
   - Once a link is found, the algorithm searches "up" the DOM hierarchy to find the closest overarching `<h1>` to `<h6>` heading tag or Category container. 
   - It natively associates each Lesson to its parent Module on the fly.
4. **Structured JSON:** The final associative array is exported back to Python and saved exactly as it looks inside `manifest.json`, giving you a 1:1 view of the backend directory tree before any intense traffic begins.

---

## 2. Setting Up & Editing Parameters
All constraints are defined at the very top of `scraper.py`. You can adjust these variables dynamically based on how aggressive or stealthy you want the scrape to be.

| Variable | Current Value | What it Does |
| :--- | :--- | :--- |
| `TEST_MODE` | `True` | Stops the script immediately after completing the very first download. **Set this to `False`** when you are ready to download the full course. |
| `TARGET_URL` | `https://w...` | The root Kajabi syllabus page the script starts its logic on. |
| `MAX_DOWNLOADS_PER_SESSION` | `100` | The total number of videos the script will rip before automatically shutting down to prevent triggering Kajabi bandwidth alarms. |

### Stealth Mechanisms
To avoid tripping Wistia's anti-bot mechanisms, the script employs localized rate-limiting logic. Because we are making legitimate HTML requests without rendering the full video stream via an automated browser interface, it's highly advised to space the pulls natively.
- **Short Delays**: The script pauses for a random interval between **4 to 9 seconds** after every successful rip: `random.uniform(4, 9)`.
- **Big Break System**: Due to the script natively mimicking human behavior, a secondary block logic activates after heavy sequential pulling. You can modify this around line 351 (`time.sleep(random.uniform(4, 9))`) to be longer if needed. (Right now, it waits standard intervals).

---

## 3. How to Run 

1. Ensure the Playwright libraries and dependencies are active on your system.
2. Ensure your `.env` file lists `USER_EMAIL = "..."` and `USER_PASSWORD = "..."`.
3. Open your terminal in the Scraper root directory.
4. Execute the Python scraper:
   ```bash
   python scraper.py
   ```

---

## 4. How the Downloader Works (Under the Hood)
After compiling `manifest.json`, the script switches to **Download Mode.**
1. **Directory Generation:** It cross-references the manifest and creates folders named `01_Module`, `02_Module`, etc., inside the `downloads/` directory.
2. **Wistia Handshake:** It commands the silent Chromium browser to visit the specific lesson URL. It forces the page to load the hidden Wistia embed payload. 
3. **ID Sniffing:** Once mounted, the script scrapes the unique `wistia_async_XXXXXXXXX` tag or `fast.wistia.net` iframe to steal the proprietary Wistia ID string.
4. **Direct Stream Extraction:** Finally, it takes that ID, bypasses the UI layer entirely, and hits the Wistia JSON REST API `api_url = f"https://fast.wistia.com/embed/medias/{wistia_id}.json"`, passing the Kajabi page as a forged *Referer* Header to avoid 403 blocks. 
5. It extracts the raw `.mp4` endpoint holding the highest size/resolution factor and commits it directly to your storage disk bit-by-bit!
