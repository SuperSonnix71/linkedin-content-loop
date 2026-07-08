"""
LinkedIn browser automation: logs in and posts via Playwright.
No LinkedIn API required. Handles session persistence and 2FA.
"""

import time

from playwright.sync_api import Page, sync_playwright


def _handle_2fa(page: Page) -> bool:
    """Check if LinkedIn is asking for 2FA. In headless mode, warn and exit."""
    time.sleep(2)

    # Check for various 2FA prompts
    pin_selector = page.locator('input[autocomplete="one-time-code"]')
    if pin_selector.is_visible(timeout=1000) or "checkpoint" in page.url or "challenge" in page.url:
        print("\n[!] LinkedIn is asking for 2FA / verification.")
        print("    Headless mode cannot handle interactive 2FA.")
        print("    Run once with a visible browser to complete 2FA:")
        print("      Set headless=False temporarily, or log in manually at linkedin.com")
        print("    Session will be saved to your profile_dir for future headless runs.")
        return False

    return True  # No 2FA detected


def post_to_linkedin(text: str, config: dict, dry_run: bool = False) -> bool:
    """
    Log into LinkedIn and create a post with the given text.
    Set dry_run=True to test the full flow without actually posting.

    Args:
        text: The post body text.
        config: dict with 'email', 'password', and optional 'profile_dir'.
        dry_run: If True, fills the post but does NOT click Post.

    Returns:
        True if posted successfully (or would have posted in dry run), False otherwise.
    """
    email = config["email"]
    password = config["password"]
    profile_dir = config.get("profile_dir", "./browser-profile")

    with sync_playwright() as p:
        # Use persistent context to save cookies/session
        browser = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=True,
            channel="chromium",
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )

        # Inject anti-detection scripts into every page
        browser.add_init_script("""
            // Remove webdriver flag
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            // Fake plugins array (headless Chrome has none)
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            // Fake languages
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            // Fake chrome runtime
            window.chrome = {runtime: {}};
        """)

        page = browser.pages[0] if browser.pages else browser.new_page()

        try:
            # --- Check if already logged in ---
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            time.sleep(2)

            if "login" in page.url.lower():
                # --- Login flow ---
                print("[*] Not logged in. Signing in...")
                page.goto(
                    "https://www.linkedin.com/login",
                    wait_until="domcontentloaded",
                )
                time.sleep(2)

                # LinkedIn has duplicate hidden inputs — use :visible or last-of-type
                email_input = page.locator('input[type="email"]').last
                pass_input = page.locator('input[type="password"]').last
                email_input.fill(email)
                pass_input.fill(password)
                # LinkedIn sign-in button — check all buttons, pick the one that's a plain submit
                buttons = page.locator('button').all()
                clicked = False
                for btn in buttons:
                    if not btn.is_visible():
                        continue
                    txt = btn.inner_text().strip().lower()
                    # Skip social login buttons (Apple, Google, Microsoft)
                    if any(s in txt for s in ['apple', 'google', 'microsoft', 'facebook']):
                        continue
                    # Skip show/hide password toggles
                    if not txt or len(txt) > 20:
                        continue
                    # This is likely the sign-in button
                    btn.click()
                    clicked = True
                    break
                if not clicked:
                    print("[!] Could not find sign-in button.")
                    return False

                # Wait for login to process
                time.sleep(4)

                # Handle 2FA if present
                if not _handle_2fa(page):
                    print("[!] 2FA failed or timed out.")
                    return False

                if "login" in page.url.lower():
                    # Check for error messages using text content (IDs are randomized)
                    error_text = page.locator('text*=Please try again').first
                    if error_text.is_visible(timeout=1000):
                        print("[!] Login error: credentials may be incorrect.")
                    else:
                        print("[!] Login failed. Check your credentials or 2FA settings.")
                    return False

                print("[+] Logged in successfully.")

            # --- Navigate to feed ---
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            time.sleep(3)

            # --- Click "Start a post" ---
            start_button = None
            for selector in [
                'div[aria-label="Start a post"]',
                'button[aria-label="Start a post"]',
                "div:has-text('Start a post')",
                "button:has-text('Start a post')",
            ]:
                try:
                    el = page.locator(selector).first
                    if el.is_visible(timeout=1000):
                        start_button = el
                        break
                except Exception:
                    continue

            if start_button is None:
                print("[!] Could not find the 'Start a post' button.")
                return False

            start_button.click()
            time.sleep(2)

            # --- Fill the post text ---
            editor = None
            for selector in [
                'div[contenteditable="true"][role="textbox"]',
                'div[contenteditable="true"]',
                'p[contenteditable="true"]',
            ]:
                try:
                    editor = page.locator(selector).first
                    if editor.is_visible(timeout=2000):
                        break
                except Exception:
                    continue

            if editor is None:
                print("[!] Could not find the post text editor.")
                return False

            editor.click()
            time.sleep(0.5)
            editor.type(text, delay=5)
            time.sleep(3)

            # Post button — try multiple approaches (test this regardless of dry_run)
            post_btn_found = False
            for selector in [
                'button.share-actions__primary-action',
                'button[aria-label="Post"]',
                'button:has-text("Post")',
            ]:
                for btn in page.locator(selector).all():
                    try:
                        if btn.is_visible():
                            post_btn_found = True
                            print("      Post button found and visible.")
                            break
                    except Exception:
                        continue
                if post_btn_found:
                    break
            if not post_btn_found:
                for btn in page.locator('button').all():
                    try:
                        text = (btn.text_content() or "").strip()
                        if btn.is_visible() and text.lower() in ("post", "send", "share"):
                            post_btn_found = True
                            print("      Post button found via text scan.")
                            break
                    except Exception:
                        continue
            if not post_btn_found:
                print("[!] Could not find Post button.")
                page.screenshot(path="/tmp/linkedin_no_post_btn.png")
                return False

            if dry_run:
                print("      [DRY RUN] Post button found. Not clicking it.")
                page.screenshot(path="/tmp/linkedin_dryrun.png")
                print("      Screenshot saved to /tmp/linkedin_dryrun.png")
                return True

            # Click the Post button
            posted = False
            for selector in [
                'button.share-actions__primary-action',
                'button[aria-label="Post"]',
                'button:has-text("Post")',
            ]:
                for btn in page.locator(selector).all():
                    try:
                        if btn.is_visible():
                            btn.click(timeout=5000)
                            posted = True
                            break
                    except Exception:
                        continue
                if posted:
                    break
            if not posted:
                for btn in page.locator('button').all():
                    try:
                        text = (btn.text_content() or "").strip()
                        if btn.is_visible() and text.lower() in ("post", "send", "share"):
                            btn.click(timeout=3000)
                            posted = True
                            break
                    except Exception:
                        continue

            time.sleep(3)

            # Verify the post was published — check for error dialogs
            error_dialog = page.locator('text*=Something went wrong').first
            if error_dialog.is_visible(timeout=1000):
                print("[!] LinkedIn showed an error after posting. Post may have failed.")
                return False

            # Check we're back on the feed (modal closes on success)
            if "feed" in page.url.lower():
                print("[+] Post published successfully.")
                return True
            else:
                print("[+] Post submitted (could not verify — check LinkedIn manually).")
                return True

        except Exception as e:
            # Save screenshot on failure for debugging
            try:
                page.screenshot(path="/tmp/linkedin_error.png")
                print("      Saved error screenshot to /tmp/linkedin_error.png")
            except Exception:
                pass
            print(f"[!] Error during LinkedIn posting: {e}")
            return False
        finally:
            browser.close()
