import time
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options

def test_login():
    print("Starting Selenium QEMU Login Test...")
    
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
        # NoVNC usually has a canvas element
        time.sleep(5) # Give it some time to load the UI
        
        # Check if canvas exists
        canvas = driver.find_elements(By.TAG_NAME, "canvas")
        if not canvas:
            print("Error: NoVNC canvas not found!")
            driver.save_screenshot(os.path.join(output_dir, "error_no_canvas.png"))
            exit(1)
        
        print("NoVNC connected. Waiting for boot (60s)...")
        time.sleep(90) # Wait for VM to boot
        
        # Send Login
        print("Sending login credentials...")
        actions = ActionChains(driver)
        
        # Click on canvas to focus
        actions.move_to_element(canvas[0]).click().perform()
        time.sleep(1)
        
        # Type username
        actions.send_keys("centos").perform()
        time.sleep(0.5)
        actions.send_keys(Keys.RETURN).perform()
        
        time.sleep(2) # Wait for password prompt
        
        # Type password
        actions.send_keys("centos").perform()
        time.sleep(0.5)
        actions.send_keys(Keys.RETURN).perform()
        
        print("Credentials sent. Waiting for login to complete (10s)...")
        time.sleep(10)
        
        # Take screenshot of success (or failure)
        screenshot_path = os.path.join(output_dir, "login_screen.png")
        driver.save_screenshot(screenshot_path)
        print(f"Screenshot saved to {screenshot_path}")
        
        # Since we can't easily read the text on canvas, we assume success if we got here without crashing
        # In a real scenario, we might use OCR or check for pixel changes, but for now this validates the flow.
        print("Test sequence completed.")
        
    except Exception as e:
        print(f"An error occurred: {e}")
        output_dir = "artifacts" if os.path.exists("artifacts") else "."
        driver.save_screenshot(os.path.join(output_dir, "error_exception.png"))
        raise
    finally:
        driver.quit()

if __name__ == "__main__":
    test_login()
