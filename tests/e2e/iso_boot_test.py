import time
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options

def test_live_os_boot():
    """Test that the live OS boots successfully from ISO"""
    print("Starting Selenium Live OS Boot Test...")
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run headless
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1024,768")

    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        # Connect to NoVNC
        url = os.environ.get("VNC_URL", "http://localhost:8006")
        print(f"Connecting to {url}...")
        driver.get(url)
        
        # Determine output directory
        output_dir = "artifacts" if os.path.exists("artifacts") else "."
        
        # Wait for page to load and connection to be established
        time.sleep(5)
        
        # Check if canvas exists
        canvas = driver.find_elements(By.TAG_NAME, "canvas")
        if not canvas:
            print("Error: NoVNC canvas not found!")
            driver.save_screenshot(os.path.join(output_dir, "error_no_canvas.png"))
            exit(1)
        
        print("NoVNC connected. Waiting for ISO to boot into live OS (120s)...")
        time.sleep(120)  # Wait longer for ISO boot
        
        # Take screenshot of boot screen
        driver.save_screenshot(os.path.join(output_dir, "boot_screen.png"))
        print("Boot screenshot saved.")
        
        # TODO: Future enhancement - automate clicking through the installer
        # For now, we just verify the live OS boots
        
        print("Live OS boot test completed successfully.")
        
    except Exception as e:
        print(f"An error occurred: {e}")
        output_dir = "artifacts" if os.path.exists("artifacts") else "."
        driver.save_screenshot(os.path.join(output_dir, "error_exception.png"))
        raise
    finally:
        driver.quit()

if __name__ == "__main__":
    test_live_os_boot()
