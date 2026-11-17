"""Ручной браузерный smoke-check: запустить demo, затем этот файл. Меняет только demo.db."""
from pathlib import Path
from playwright.sync_api import expect, sync_playwright


def main():
    folder=Path("docs/previews")
    folder.mkdir(parents=True,exist_ok=True)
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel="msedge",headless=True)
        page=browser.new_page(viewport={"width":390,"height":844},device_scale_factor=1)
        page.on("pageerror",lambda error:errors.append(str(error)))
        page.goto("http://127.0.0.1:8765",wait_until="networkidle")
        expect(page.locator(".game-hero")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(folder/"mini-app-mobile.png"),full_page=True)
        page.locator("#theme-toggle").click()
        expect(page.locator("body")).to_have_class("dark")
        page.screenshot(path=str(folder/"mini-app-dark.png"),full_page=True)
        page.locator("#theme-toggle").click()
        page.set_viewport_size({"width":1366,"height":960})
        page.screenshot(path=str(folder/"mini-app-desktop.png"),full_page=True)
        page.set_viewport_size({"width":360,"height":800})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for tab in ["ranking","stats","club","games","home"]:
            page.locator(f"#mobile-nav [data-tab='{tab}']").click()
            expect(page.locator("main h1")).to_be_visible()
        page.locator("[data-action='new-game']").first.click()
        page.locator("input[name='title']").fill("Browser smoke-check")
        page.locator("input[name='location']").fill("Demo only")
        page.locator("#sheet-submit").click()
        page.locator("#sheet-submit").click()
        expect(page.locator("#sheet")).not_to_be_visible()
        expect(page.locator("main h1")).to_have_text("Browser smoke-check")
        for _ in range(2):
            page.locator("[data-action='add-player']").click()
            page.locator("#sheet-submit").click()
            expect(page.locator("#sheet")).not_to_be_visible()
        page.locator("[data-status='active']").click()
        page.locator("#sheet-submit").click()
        expect(page.locator("#sheet")).not_to_be_visible()
        for player in range(2):
            page.locator("[data-action='record']").click()
            page.locator("select[name='member_id']").select_option(index=player)
            page.locator("#sheet-submit").click()
            page.locator("#sheet-submit").click()
            expect(page.locator("#sheet")).not_to_be_visible()
        for amount in ["1500","500"]:
            page.locator("[data-action='cashout']").click()
            page.locator("input[name='amount']").fill(amount)
            page.locator("#sheet-submit").click()
            page.locator("#sheet-submit").click()
            expect(page.locator("#sheet")).not_to_be_visible()
        for status in ["reconciling","completed"]:
            page.locator(f"[data-status='{status}']").click()
            page.locator("#sheet-submit").click()
            expect(page.locator("#sheet")).not_to_be_visible()
        expect(page.locator(".game-status")).to_have_text("Завершена")
        page.screenshot(path=str(folder/"mini-app-game.png"),full_page=True)
        assert not errors,errors
        browser.close()
    print("Browser checks passed: mobile/desktop, themes, navigation, complete cash game, no JS errors")


if __name__=="__main__":
    main()
