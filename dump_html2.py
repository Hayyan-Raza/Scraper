import os
from playwright.sync_api import sync_playwright

def main():
    TARGET_URL = 'https://wfsgroup.mykajabi.com/products/wfs-sales-resource-center-transitioning-reps'
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=os.path.join(os.getcwd(), 'chrome_session'),
            headless=True,
            viewport={"width": 1280, "height": 720}
        )
        page = context.new_page()
        page.goto(TARGET_URL)
        page.wait_for_timeout(5000)
        
        with open('debug_syllabus.html', 'w', encoding='utf-8') as f:
            f.write(page.content())
            
        print("Done downloading syllabus")
        
        # Now find the first lesson and click it to get to player, or check if we are redirected
        if "/posts/" not in page.url:
            post_link = page.locator("a[href*='/posts/']").first
            if post_link.is_visible():
                post_link.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(3000)
                
        with open('debug_player.html', 'w', encoding='utf-8') as f:
            f.write(page.content())
            
        print("Done downloading player")
        context.close()

if __name__ == "__main__":
    main()
