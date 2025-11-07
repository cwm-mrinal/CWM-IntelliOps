import os
os.environ["WDM_LOCAL"] = "1"
os.environ["WDM_CACHE_DIR"] = "/tmp/wdm"
import re
import time
import shutil
import urllib.request
import urllib.error
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


def capture_screenshot(url: str, file_path: str = "/tmp/screenshot.png") -> str:
    try:
        # Ensure /tmp is used for cache and driver
        os.makedirs("/tmp/wdm", exist_ok=True)

        # Install ChromeDriver (cached in /tmp)
        driver_path = ChromeDriverManager().install()

        # Copy ChromeDriver to /tmp
        tmp_driver_path = "/tmp/chromedriver"
        shutil.copy(driver_path, tmp_driver_path)
        os.chmod(tmp_driver_path, 0o755)

        # Set Chrome options
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1280,800")

        # Launch browser
        driver = webdriver.Chrome(executable_path=tmp_driver_path, options=options)
        driver.get(url)
        time.sleep(2)
        driver.save_screenshot(file_path)
        return file_path

    except Exception as e:
        return f"[Screenshot Failed: {str(e)}]"

    finally:
        try:
            driver.quit()
        except:
            pass


def check_site_status(ticket_body: str) -> str:
    # Extract URL from markdown-style format: [URL | Label] or [Label | URL]
    matches = re.findall(
        r"\[\s*(https?://[^\s\]]+)\s*\|\s*.*?\]|\[\s*.*?\|\s*(https?://[^\s\]]+)\s*\]",
        ticket_body
    )
    urls = [url for match in matches for url in match if url]

    if not urls:
        return "❌ No valid URL found in the ticket body."

    url = urls[0]

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        start_time = time.time()

        with urllib.request.urlopen(req, timeout=5) as response:
            response_time = round(time.time() - start_time, 3)
            status_code = response.getcode()
            reason = response.reason

            screenshot_info = capture_screenshot(url)

            status_msg = (
                f"🔗 URL: {url}\n"
                f"📶 Status: HTTP {status_code} {reason}\n"
                f"⏱️ Response Time: {response_time}s\n"
            )

            if screenshot_info.startswith("[Screenshot Failed"):
                status_msg += f"⚠️ {screenshot_info}"
            else:
                status_msg += f"🖼️ Screenshot saved at: {screenshot_info}"

            if 200 <= status_code < 300:
                return f"✅ Site is Up and Running.\n{status_msg}"
            else:
                return f"⚠️ Site responded but may have issues.\n{status_msg}"

    except urllib.error.HTTPError as e:
        return (
            f"❌ Site returned an HTTP error.\n"
            f"🔗 URL: {url}\n"
            f"📶 Status: HTTP {e.code} {e.reason}"
        )

    except urllib.error.URLError as e:
        return (
            f"❌ Site appears to be Down or Unreachable.\n"
            f"🔗 URL: {url}\n"
            f"💥 Error: {e.reason}"
        )
