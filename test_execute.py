import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: logs.append(f"[ERROR] {err}"))
        
        await page.goto("http://localhost:8080/app")
        await page.wait_for_timeout(2000)
        
        # Dispatch escape just in case
        await page.keyboard.press("Escape")
        
        # Type and click
        await page.fill("#targetInput", "TCS")
        await page.click("#executeBtn")
        
        # Wait for processing state or errors
        await page.wait_for_timeout(4000)
        
        await page.screenshot(path="playwright_debug.png")
        
        with open("playwright_logs.txt", "w") as f:
            for log in logs:
                f.write(log + "\n")
                
        # Check current state classes
        is_processing = await page.evaluate("!document.getElementById('stateProcessing').classList.contains('hidden')")
        with open("playwright_state.txt", "w") as f:
            f.write(f"Processing visible: {is_processing}\n")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
