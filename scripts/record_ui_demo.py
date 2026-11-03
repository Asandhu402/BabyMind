from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import shutil

OUT = Path("artifacts")
OUT.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 960},
        device_scale_factor=1,
        record_video_dir=str(OUT),
        record_video_size={"width": 1440, "height": 960},
    )
    page = context.new_page()
    page.goto("http://127.0.0.1:8765", wait_until="networkidle", timeout=60000)
    page.screenshot(path=str(OUT / "01-chat-home.png"), full_page=True)
    page.wait_for_selector("#agentSelect option:nth-child(50)", timeout=30000)

    # Show the searchable specialist directory.
    page.locator('[data-view="agents"]').click()
    page.wait_for_selector("#agentGrid .agent-card", timeout=15000)
    page.screenshot(path=str(OUT / "02-agent-directory.png"), full_page=True)
    page.locator("#agentSearch").fill("code")
    page.wait_for_timeout(700)
    page.locator("#agentSearch").fill("")

    # Return to chat and ask the actual local model a short question.
    page.locator('[data-view="chat"]').click()
    page.locator("#messageInput").fill(
        "For this interface demo, reply in two short sentences: introduce yourself as BabyMind and explain that you have specialist roles."
    )
    page.locator("#sendButton").click()
    try:
        page.locator("#messages .message.assistant .message-content").last.wait_for(
            state="visible", timeout=240000
        )
        page.wait_for_function(
            "() => !document.querySelector('#typingIndicator')",
            timeout=240000,
        )
    except PlaywrightTimeoutError:
        page.screenshot(path=str(OUT / "03-chat-timeout.png"), full_page=True)
        raise
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT / "03-live-model-chat.png"), full_page=True)

    # Show the local memory workspace and settings page.
    page.locator('[data-view="memory"]').click()
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "04-memory.png"), full_page=True)
    page.locator("#settingsButton").click()
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "05-settings.png"), full_page=True)

    context.close()
    video_path = page.video.path()
    browser.close()
    shutil.copy2(video_path, OUT / "BabyMind-UI-Demo.webm")
    print(f"Recorded actual BabyMind UI video: {OUT / 'BabyMind-UI-Demo.webm'}")
