import os
import re
import sys
import json
import time
import random
import requests
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import argparse

# --- Configuration ---
TEST_MODE = True  # Default. Will be overridden by --full flag
MAX_DOWNLOADS = 100 # Default. Overridden by --limit flag
TARGET_URL = 'https://wfsgroup.mykajabi.com/products/wfs-sales-resource-center-transitioning-reps'

CHROME_SESSION_DIR = 'chrome_session'
MANIFEST_FILE = 'manifest.json'
DOWNLOAD_DIR = 'downloads'

def clean_filename(name):
    """Clean the text of any special characters that aren't allowed in Windows/Linux filenames."""
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.strip()

def get_hierarchy(page):
    """
    Executes Javascript to group Kajabi lesson links into modules by DOM structure.
    """
    script = """
    () => {
        // Find all links to lessons, but explicitly exclude buttons (like "Resume Training")
        let allNodes = document.querySelectorAll('a[href*="/posts/"]');
        let links = Array.from(allNodes).filter(a => {
            // Filter out 'btn' class links which are usually Resume/Start buttons, not actual syllabus lists
            if (a.className && typeof a.className === 'string' && a.className.includes('btn')) return false;
            // Filter out the hero 'continue' block if it doesn't have a syllabus item parent
            if (!a.closest('.syllabus__item, .product-outline-post, .category-post, .panel, .module')) {
                // If it's a floating link outside a module container, it's likely a duplicate resume button
                return false;
            }
            return true;
        });
        
        // Remove duplicates and empty links
        let uniqueHrefs = new Set();
        let validLinks = [];
        for (let l of links) {
            if (!uniqueHrefs.has(l.href)) {
                uniqueHrefs.add(l.href);
                validLinks.push(l);
            }
        }
        
        const modulesMap = new Map();
        
        validLinks.forEach(link => {
            let modTitle = "Uncategorized";
            
            // Strategy 1: Look for common Kajabi category wrappers
            const wrapper = link.closest('.syllabus__category, .product-outline-category, .panel, .module, .category, .course-curriculum__chapter, .product-outline-category-container');
            if (wrapper) {
                const heading = wrapper.querySelector('h1, h2, h3, h4, h5, h6, .category-title, .panel-title, .syllabus__heading, .chapter-title');
                if (heading) {
                    modTitle = heading.innerText.trim().replace(/\\r?\\n|\\r/g, ' - ');
                }
            } else {
                // Strategy 2: Look backwards in the DOM for the nearest heading
                let current = link;
                while (current && current !== document.body) {
                    let prev = current.previousElementSibling;
                    while (prev) {
                        if (/^H[1-6]$/.test(prev.tagName)) {
                            modTitle = prev.innerText.trim();
                            break;
                        }
                        const headings = prev.querySelectorAll('h1, h2, h3, h4, h5, h6');
                        if (headings.length > 0) {
                            modTitle = headings[headings.length - 1].innerText.trim();
                            break;
                        }
                        prev = prev.previousElementSibling;
                    }
                    if (modTitle !== "Uncategorized") break;
                    current = current.parentElement;
                }
            }
            
            if (!modTitle) modTitle = "Uncategorized";
            
            if (!modulesMap.has(modTitle)) {
                modulesMap.set(modTitle, []);
            }
            
            let titleText = link.innerText.trim();
            if (!titleText) {
                 // Try looking for a title inside (Kajabi often embeds it in an h4 list element)
                 let innerHeader = link.querySelector('h1, h2, h3, h4, h5, h6, .syllabus__item-title, .post-title');
                 if (innerHeader) titleText = innerHeader.innerText.trim();
                 else titleText = 'Untitled_Lesson_' + link.href.split('/').pop();
            }
            titleText = titleText.replace(/\\r?\\n|\\r/g, ' ');
            
            modulesMap.get(modTitle).push({
                title: titleText,
                href: link.href
            });
        });
        
        const result = [];
        let m_idx = 1;
        for (const [modTitle, lessons] of modulesMap.entries()) {
            const formattedLessons = [];
            let l_idx = 1;
            for (const l of lessons) {
                formattedLessons.push({
                    index: l_idx,
                    title: l.title,
                    href: l.href
                });
                l_idx++;
            }
            result.push({
                index: m_idx,
                title: modTitle,
                lessons: formattedLessons
            });
            m_idx++;
        }
        return result;
    }
    """
    return page.evaluate(script)

def extract_wistia_id_from_lesson(page, url):
    """Navigates to the lesson page to extract the Wistia ID natively embedded in the DOM."""
    if url.startswith('/'):
        url = "https://wfsgroup.mykajabi.com" + url
        
    print(f"      [Browser] Loading page: {url}")
    try:
        page.goto(url)
        # Wait for the network to settle but respect a timeout if it takes longer natively
        page.wait_for_load_state("networkidle", timeout=10000)
    except:
        # Ignore networkidle timeout to avoid failing if there are endless background streams
        pass
        
    # Extra pause to let Wistia player iframe load
    page.wait_for_timeout(3000)
    
    script = """
    () => {
        // Method 1: The standard Wistia async wrapper
        let asyncElem = document.querySelector('[class*="wistia_async_"]');
        if (asyncElem) {
            let match = asyncElem.className.match(/wistia_async_([a-zA-Z0-9]+)/);
            if (match) return match[1];
        }
        
        // Method 2: The classic Wistia iframe embed
        let iframe = document.querySelector('iframe[src*="fast.wistia.net/embed/iframe/"]');
        if (iframe) {
            let match = iframe.src.match(/iframe\\/([^\\?]+)/);
            if (match) return match[1];
        }
        
        // Method 3: Fallback DOM ID parsing
        let target = document.querySelector('[id^="wistia_"], [class*="wistia_embed"]');
        if (target) {
            let idStr = target.id || target.className;
            let match = idStr.match(/wistia_([a-zA-Z0-9]{3,})/);
            if (match && match[1] !== 'embed' && match[1] !== 'async') return match[1];
        }
        
        return null;
    }
    """
    return page.evaluate(script)


def get_wistia_direct_link(wistia_id):
    """Fetch the fast.wistia.com JSON to find the actual direct .mp4 highest quality asset URL."""
    api_url = f"https://fast.wistia.com/embed/medias/{wistia_id}.json"
    headers = {
        'Referer': 'https://wfsgroup.mykajabi.com/'
    }
    
    try:
        r = requests.get(api_url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        if "media" in data and "assets" in data["media"]:
            assets = data["media"]["assets"]
            mp4_assets = [a for a in assets if a.get("ext") == "mp4"]
            
            if mp4_assets:
                best_asset = sorted(mp4_assets, key=lambda x: x.get("size", 0), reverse=True)[0]
                url = best_asset.get("url")
                if url and url.startswith("//"):
                    url = f"https:{url}"
                return url
    except Exception as e:
        print(f"      [API Error] fetching details for Wistia ID {wistia_id}: {e}")
    return None

def download_video(url, filepath):
    """Download video stream with persistent referer passing and .tmp swap to prevent corruption."""
    headers = {
        'Referer': 'https://wfsgroup.mykajabi.com/'
    }
    
    tmp_filepath = filepath + ".tmp"
    with requests.get(url, headers=headers, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(tmp_filepath, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    
    # Rename tmp lockfile to fully complete mp4 file only after successful stream flush
    os.rename(tmp_filepath, filepath)

def main():
    parser = argparse.ArgumentParser(description="Kajabi/Wistia Hierarchical Video Scraper")
    parser.add_argument('--limit', type=int, default=100, help="Maximum number of videos to download in this run.")
    parser.add_argument('--full', action='store_true', help="Run the full scrape (disables TEST_MODE).")
    args = parser.parse_args()
    
    global TEST_MODE, MAX_DOWNLOADS
    if args.full:
        TEST_MODE = False
    MAX_DOWNLOADS = args.limit
    
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    
    email = ""
    password = ""
    if os.path.exists('.env'):
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                if '=' in line:
                    k, v = line.split('=', 1)
                    if k.strip() == 'USER_EMAIL':
                        email = v.strip().strip('"').strip("'")
                    elif k.strip() == 'USER_PASSWORD':
                        password = v.strip().strip('"').strip("'")
                        
    print("=== Phase 1: Authentication & Scraping Hierarchy ===")
    with sync_playwright() as p:
        print("Launching browser context...")
        context = p.chromium.launch_persistent_context(
            user_data_dir=os.path.join(os.getcwd(), CHROME_SESSION_DIR),
            headless=False,
            viewport={"width": 1280, "height": 720}
        )
        
        page = context.new_page()
        stealth_manager = Stealth()
        stealth_manager.apply_stealth_sync(page)
        
        print(f"Navigating to course syllabus: {TARGET_URL}")
        page.goto(TARGET_URL)
        page.wait_for_timeout(3000)
        
        # 1. Automated Login Handling
        if page.locator("input[type='email']").is_visible():
            print("Login wall detected. Filling credentials...")
            page.fill("input[type='email']", email)
            page.fill("input[type='password']", password)
            submit_btn = page.locator("input[type='submit'], button[type='submit']")
            if submit_btn.is_visible():
                submit_btn.click()
            else:
                page.keyboard.press("Enter")
                
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(5000)
            
            # Navigate back to syllabus just in case login pushed us to generic library
            page.goto(TARGET_URL)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3000)

        # 2. Extract Hierarchy from Syllabus
        print("Scraping syllabus for course module hierarchy...")
        modules = get_hierarchy(page)
        
        # 2.5: Traverse category pagination to find hidden lessons on page 2+
        print("Checking for paginated lessons in each module...")
        for mod in modules:
            if not mod['lessons']:
                continue
                
            # Deduce the category URL from the first lesson's href
            first_href = mod['lessons'][0]['href']
            cat_match = re.search(r'(https?://[^/]+/.*?/categories/\d+)', first_href)
            
            if cat_match:
                cat_url = cat_match.group(1)
                
                # Check consecutive pages
                page_num = 2
                while True:
                    paged_url = f"{cat_url}?page={page_num}"
                    try:
                        page.goto(paged_url)
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except:
                        pass
                        
                    # Extract lessons on this paginated page
                    paged_modules = get_hierarchy(page)
                    
                    added_any = False
                    # We expect the lessons on this page to belong to the same module
                    for p_mod in paged_modules:
                        for less in p_mod['lessons']:
                            # Check if we already have it
                            existing_hrefs = [l['href'] for l in mod['lessons']]
                            if less['href'] not in existing_hrefs:
                                # Add the new hidden lesson!
                                new_index = len(mod['lessons']) + 1
                                mod['lessons'].append({
                                    'index': new_index,
                                    'title': less['title'],
                                    'href': less['href']
                                })
                                added_any = True
                                print(f"  -> Discovered hidden paginated lesson: {less['title']}")
                    
                    if not added_any:
                        # No new unique lessons found on this page number, meaning we reached the end of the pagination
                        break
                        
                    page_num += 1
        
        # Validation & Manifest Generation
        total_modules = len(modules)
        total_lessons = sum(len(m['lessons']) for m in modules)
        
        if total_lessons == 0:
            print("[CRITICAL] Found 0 lessons! The page might be rendering dynamically or we are not on the Syllabus.")
            print("Saving HTML dump to debug.html for troubleshooting.")
            with open('debug.html', 'w', encoding='utf-8') as f:
                f.write(page.content())
            sys.exit(1)
            
        print(f"\\n[SUCCESS] Discovered {total_modules} Modules and {total_lessons} total Lessons.")
        
        manifest_data = {
            "status": "success",
            "total_modules": total_modules,
            "total_lessons": total_lessons,
            "modules": modules
        }
        
        with open(MANIFEST_FILE, 'w', encoding='utf-8') as f:
            json.dump(manifest_data, f, indent=4)
            print(f"Structural layout successfully saved to {MANIFEST_FILE}")

        print("\\n=== Phase 2: Crawler - Wistia Player Extraction & Downloading ===")
        
        download_count = 0
        for mod in modules:
            mod_index = str(mod['index']).zfill(2)
            mod_title_clean = clean_filename(mod['title'])
            mod_folder_name = f"{mod_index}_{mod_title_clean}"
            mod_path = os.path.join(DOWNLOAD_DIR, mod_folder_name)
            
            os.makedirs(mod_path, exist_ok=True)
            
            for less in mod['lessons']:
                if download_count >= MAX_DOWNLOADS:
                    print(f"\\n[LIMIT REACHED] Maximum limit of {MAX_DOWNLOADS} videos reached for this session.")
                    context.close()
                    sys.exit(0)
                
                less_index = str(less['index']).zfill(2)
                less_title_clean = clean_filename(less['title'])
                lesson_filename = f"{less_index}_{less_title_clean}.mp4"
                lesson_filepath = os.path.join(mod_path, lesson_filename)
                
                if os.path.exists(lesson_filepath):
                    print(f"  [-] Already exists: {lesson_filename}. Skipping over.")
                    continue
                    
                print(f"\\n> Module {mod_index}: '{mod['title']}' | Lesson {less_index}: '{less['title']}'")
                
                wistia_id = extract_wistia_id_from_lesson(page, less['href'])
                
                if not wistia_id:
                    print(f"      [!] Skipping '{less['title']}': Could not find Wistia Player Element on page.")
                    continue
                else:
                    print(f"      [DOM Scraper] Found Hidden Wistia ID: {wistia_id}")
                    
                direct_link = get_wistia_direct_link(wistia_id)
                
                if not direct_link:
                    print(f"      [!] Request for MP4 stream failed for {wistia_id}")
                    continue
                    
                print(f"      [Downloader] Starting request into '{mod_folder_name}/{lesson_filename}'...")
                
                try:
                    download_video(direct_link, lesson_filepath)
                    print("      [✔] Success.")
                    download_count += 1
                except Exception as e:
                    print(f"      [X] Failed to parse chunks for {lesson_filename}: {e}")
                    
                if TEST_MODE:
                    print("\\n[TEST MODE ACTIVE] Completed extraction loop for the initial video successfully.")
                    print("Exiting test phase. Set TEST_MODE = False in the script to run bulk download.")
                    context.close()
                    sys.exit(0)
                    
                # Small anti-detection rate limit between individual lessons.
                time.sleep(random.uniform(4, 9))

        print("\\nAll downloads complete.")
        context.close()

if __name__ == "__main__":
    main()
