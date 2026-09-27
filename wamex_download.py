#!/usr/bin/env python3
"""Download all available documents for WAMEX reports (A numbers).

Reads a CSV with an ANUMBER column (tab or comma separated), opens each
report's WAMEX ReportDetails page in a real browser, clicks every download
link found on the page, and stores the downloaded files in a per-report
folder named A<6-digit zero-padded number>, e.g.:

    5725  -> reports/A005725/
    10299 -> reports/A010299/

The WAMEX portal is a JavaScript application: the document links are fetched
and rendered asynchronously, so the script waits dynamically for them to
appear (up to --page-timeout seconds) and retries the page (--retries times)
before giving up.

Diagnostics: a folder is created for EVERY report processed. On any failure
the page HTML, a screenshot, the browser URL and the visible page text are
saved into the report folder (debug_page.html, debug_screenshot.png,
debug_url.txt, debug_text.txt) so the failure can be diagnosed.

Bot protection: the WAMEX portal is protected by Imperva Incapsula. Its
bot-clearance is stored in cookies, so the browser session (including
cookies) is KEPT between reports by default -- clearing cookies forces a
new bot challenge on every report and causes 'Request unsuccessful'
block pages. If a block page still appears, the script waits out a
cooldown before retrying instead of hammering the site.

Resumable: a report folder containing a .complete marker is skipped.
Failures are collected in <out>/_failed.txt so you can re-run just those.

Usage:
    python3 wamex_download.py --csv sample_reports.csv
    python3 wamex_download.py --csv sample_reports.csv --out-dir reports --delay 10
    python3 wamex_download.py --anumbers 5725 6285
    python3 wamex_download.py --csv sample_reports.csv --dry-run
    python3 wamex_download.py --csv sample_reports.csv --fresh-session   # clear cookies between reports (not recommended)

Requires: pip install selenium   (Selenium >= 4.6 auto-manages the webdriver)
Note: WAMEX documents do not download correctly in Chrome; use Firefox
(the default here). See --browser chrome only if you must.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import shutil
import sys
import time
import traceback
from pathlib import Path

__version__ = "1.4.0"

BASE_URL = "https://wamex.dmp.wa.gov.au/Wamex/Search/ReportDetails?ANumber={}"
WAMEX_HOME = "https://wamex.dmp.wa.gov.au/Wamex/"
COMPLETE_MARKER = ".complete"
BLOCK_SIGNATURES = (
    "request unsuccessful",
    "incapsula",
    "incident id",
    "access denied",
    "you have been blocked",
    "unusual traffic",
    "bot protection",
    "verify you are a human",
    "captcha",
)
MATCH_WORDS = ("download", "getfile", "openfile", "filedownload")
FILE_EXTENSIONS = (
    "pdf", "zip", "doc", "docx", "xls", "xlsx", "tif", "tiff",
    "rar", "7z", "rtf", "txt", "csv",
)
DEFAULT_PAGE_TIMEOUT = 30
DEFAULT_DOWNLOAD_TIMEOUT = 300
POLL_INTERVAL = 1.0
NEVER_ASK_TYPES = (
    "application/octet-stream,application/pdf,application/zip,"
    "application/x-zip-compressed,application/x-pdf,application/msword,"
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
    "application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
    "application/rtf,text/plain,text/csv,image/tiff,application/x-tiff,"
    "application/x-download,application/force-download,"
    "application/x-zip,application/x-compressed,application/gzip,application/x-gzip,"
    "application/x-rar-compressed,application/vnd.rar,application/x-7z-compressed,"
    "application/xml,application/json"
)


class Tee:
    """Write messages to both the console and a log file."""

    def __init__(self, log_path: Path):
        self._path = log_path
        self._file = log_path.open("a", encoding="utf-8")

    def write(self, text: str) -> None:
        sys.__stdout__.write(text)
        try:
            self._file.write(text)
            self._file.flush()
        except Exception:
            pass

    def flush(self) -> None:
        sys.__stdout__.flush()
        try:
            self._file.flush()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._file.close()
        except Exception:
            pass


def log(message: str = "") -> None:
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {message}")


def folder_name(anumber: int) -> str:
    return f"A{anumber:06d}"


def report_url(anumber: int) -> str:
    return BASE_URL.format(anumber)


def read_anumbers_from_csv(path: Path) -> list[int]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        sample = fh.read(64 * 1024)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(fh, dialect)
        header = [h.strip().upper() for h in next(reader, [])]
        try:
            anum_idx = header.index("ANUMBER")
        except ValueError:
            sys.exit("error: CSV must contain an 'ANUMBER' column")
        numbers = []
        seen = set()
        for row in reader:
            if len(row) <= anum_idx:
                continue
            value = row[anum_idx].strip()
            if not value:
                continue
            try:
                n = int(value)
            except ValueError:
                print(f"warning: skipping non-numeric ANUMBER {value!r}", file=sys.stderr)
                continue
            if n not in seen:
                seen.add(n)
                numbers.append(n)
    return numbers


def make_driver(browser: str, download_dir: Path):
    if browser == "firefox":
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service

        options = Options()
        options.set_preference("browser.download.folderList", 2)
        options.set_preference("browser.download.dir", str(download_dir))
        options.set_preference("browser.download.useDownloadDir", True)
        options.set_preference("browser.helperApps.neverAsk.saveToDisk", NEVER_ASK_TYPES)
        options.set_preference("pdfjs.disabled", True)
        options.set_preference("browser.download.manager.showWhenStarting", False)
        options.set_preference("dom.disable_beforeunload", True)
        service = Service()
        from selenium.webdriver import Firefox

        return Firefox(service=service, options=options)
    if browser == "chrome":
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        options = Options()
        prefs = {
            "download.default_directory": str(download_dir),
            "download.prompt_for_download": False,
            "plugins.always_open_pdf_externally": True,
        }
        options.add_experimental_option("prefs", prefs)
        options.add_argument("--disable-popup-blocking")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        service = Service()
        from selenium.webdriver import Chrome

        return Chrome(service=service, options=options)
    sys.exit(f"error: unsupported browser {browser!r}")


def safe_current_url(driver) -> str:
    try:
        return driver.current_url
    except Exception:
        return ""


def safe_title(driver) -> str:
    try:
        return driver.title
    except Exception:
        return ""


def dismiss_alerts(driver) -> None:
    """Accept and dismiss any open JavaScript/browser alert.

    A leftover alert (e.g. from the previous report's click) blocks all
    further Selenium commands in the page, which looks exactly like
    'no download links found' on every subsequent report.
    """
    for _ in range(3):
        try:
            alert = driver.switch_to.alert
            text = ""
            try:
                text = alert.text
            except Exception:
                pass
            if text:
                print(f"    dismissing alert: {text!r}", file=sys.stderr)
            alert.accept()
            time.sleep(0.5)
        except Exception:
            return


def is_block_page(driver) -> bool:
    """Detect Incapsula/WAF block or challenge pages."""
    text = page_text_snippet(driver, 3000).lower()
    if not text:
        return False
    return any(sig in text for sig in BLOCK_SIGNATURES)


def wait_page_ready(driver, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if driver.execute_script("return document.readyState") == "complete":
                return
        except Exception:
            return
        time.sleep(0.5)


def pending_downloads(download_dir: Path) -> list[Path]:
    return [p for p in download_dir.iterdir() if p.suffix in (".part", ".crdownload", ".tmp")]


def _find_download_elements_in_context(driver) -> list:
    candidates = []
    selector = "a, button, [role='button'], input[type='button'], input[type='submit']"
    for elem in driver.find_elements("css selector", selector):
        try:
            text = (elem.text or "").strip().lower()
            href = (elem.get_dom_attribute("href") or "").lower()
            onclick = (elem.get_dom_attribute("onclick") or "").lower()
            title = (elem.get_dom_attribute("title") or "").lower()
            value = (elem.get_dom_attribute("value") or "").lower()
        except Exception:
            continue
        attributes = [s for s in (text, href, onclick, title, value) if s]
        word_match = any(word in s for word in MATCH_WORDS for s in attributes)
        file_match = bool(href) and any(f".{ext}" in href for ext in FILE_EXTENSIONS)
        if not (word_match or file_match):
            continue
        if not href and not onclick and not text and not value:
            continue
        candidates.append(elem)
    return candidates


def find_download_elements(driver) -> list:
    """Find download links in the top document and inside direct iframes.

    Leaves the driver switched into the frame where elements were found (so
    they remain clickable); switches back to the top document when nothing
    is found anywhere.
    """
    driver.switch_to.default_content()
    frames = driver.find_elements("css selector", "iframe, frame")
    contexts = [None] + list(range(len(frames)))
    for idx in contexts:
        driver.switch_to.default_content()
        if idx is not None:
            try:
                driver.switch_to.frame(idx)
            except Exception:
                continue
        candidates = _find_download_elements_in_context(driver)
        if candidates:
            return candidates
    driver.switch_to.default_content()
    return []


def wait_for_download_elements(driver, timeout: float):
    deadline = time.monotonic() + timeout
    while True:
        try:
            elements = find_download_elements(driver)
        except Exception:
            elements = []
        if elements:
            return elements
        if time.monotonic() >= deadline:
            return []
        time.sleep(POLL_INTERVAL)


def close_extra_windows(driver, main_window) -> None:
    for handle in list(driver.window_handles):
        if handle != main_window:
            try:
                driver.switch_to.window(handle)
                driver.close()
            except Exception:
                pass
    try:
        driver.switch_to.window(main_window)
    except Exception:
        pass


def page_text_snippet(driver, limit: int = 2000) -> str:
    try:
        driver.switch_to.default_content()
        text = driver.find_element("css selector", "body").text
    except Exception:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)[:limit]


def dump_debug(driver, target_dir: Path) -> None:
    """Save everything needed to diagnose the current browser state.

    Never raises; writes whatever it can into the report folder.
    """
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return
    try:
        (target_dir / "debug_url.txt").write_text(
            safe_current_url(driver) + "\n", encoding="utf-8"
        )
    except Exception:
        pass
    try:
        (target_dir / "debug_page.html").write_text(
            driver.page_source, encoding="utf-8", errors="replace"
        )
    except Exception:
        pass
    try:
        (target_dir / "debug_text.txt").write_text(
            page_text_snippet(driver) + "\n", encoding="utf-8"
        )
    except Exception:
        pass
    try:
        driver.save_screenshot(str(target_dir / "debug_screenshot.png"))
    except Exception:
        pass


def click_download_elements(driver, anumber: int, main_window, verbose: bool, page_timeout: float) -> int:
    url = report_url(anumber)
    total = len(wait_for_download_elements(driver, page_timeout))
    clicked = 0
    for i in range(total):
        try:
            dismiss_alerts(driver)
            if f"ANumber={anumber}" not in safe_current_url(driver):
                if verbose:
                    print("    page navigated away; returning to report page", file=sys.stderr)
                driver.get(url)
                wait_page_ready(driver)
                if not wait_for_download_elements(driver, page_timeout):
                    break
            elements = find_download_elements(driver)
            if i >= len(elements):
                break
            elem = elements[i]
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
            elem.click()
            clicked += 1
            time.sleep(1.5)
        except Exception as exc:
            if verbose:
                print(f"    click {i + 1} failed: {exc}", file=sys.stderr)
        close_extra_windows(driver, main_window)
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return clicked


def wait_for_downloads(download_dir: Path, before: set[str], timeout: int) -> list[Path]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        files = {p.name for p in download_dir.iterdir() if p.is_file()}
        new_files = files - before
        if new_files and not pending_downloads(download_dir):
            return [download_dir / name for name in sorted(new_files)]
        time.sleep(POLL_INTERVAL)
    if pending_downloads(download_dir):
        return []
    return [download_dir / n for n in sorted({p.name for p in download_dir.iterdir() if p.is_file()} - before)]


def download_report(driver, download_dir: Path, anumber: int, target_dir: Path,
                    verbose: bool, download_timeout: int, page_timeout: float,
                    retries: int, block_cooldown: float = 120.0,
                    max_block_retries: int = 3) -> tuple[int, str]:
    url = report_url(anumber)
    elements = []
    blocked = False
    for attempt in range(1 + max(0, retries)):
        try:
            dismiss_alerts(driver)
            if attempt == 0:
                driver.get(url)
            else:
                if verbose:
                    print(f"    retry {attempt}: re-entering via WAMEX home page", file=sys.stderr)
                try:
                    driver.get(WAMEX_HOME)
                    time.sleep(2)
                except Exception:
                    pass
                driver.get(url)
            wait_page_ready(driver)
            blocked = is_block_page(driver)
            if blocked:
                log(f"    attempt {attempt + 1}: blocked by site protection (Incapsula/WAF)")
                if attempt < max(0, retries) or attempt < max_block_retries:
                    cooldown = block_cooldown * (attempt + 1)
                    log(f"    cooling down {cooldown:.0f}s before retry (site bot protection is active)")
                    time.sleep(cooldown)
                    continue
            elements = wait_for_download_elements(driver, page_timeout)
        except Exception as exc:
            dump_debug(driver, target_dir)
            return 0, f"error while loading {url}: {exc!r}"
        if elements:
            break
        if verbose:
            print(f"    attempt {attempt + 1}: no download links rendered yet", file=sys.stderr)

    if not elements:
        dump_debug(driver, target_dir)
        title = safe_title(driver)
        snippet = page_text_snippet(driver, 300).replace("\n", " | ")
        if blocked:
            return 0, (
                f"blocked by site bot protection (Incapsula) on {url} after "
                f"{1 + max(0, retries)} attempt(s); the site is refusing automated "
                f"access right now -- wait a while, then re-run (completed reports "
                f"are skipped automatically). Page text: {snippet!r}"
            )
        return 0, (
            f"no download links found on {url} "
            f"(browser at: {safe_current_url(driver)}; title: {title!r}; "
            f"page text: {snippet!r}; "
            f"debug_page.html/debug_screenshot.png saved in {target_dir})"
        )

    main_window = driver.current_window_handle
    before = {p.name for p in download_dir.iterdir() if p.is_file()}

    clicked = click_download_elements(driver, anumber, main_window, verbose, page_timeout)
    if clicked == 0:
        dump_debug(driver, target_dir)
        return 0, f"found {len(elements)} candidate link(s) but none clickable on {url}"

    files = wait_for_downloads(download_dir, before, download_timeout)
    moved = 0
    target_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        dest = target_dir / f.name
        counter = 1
        while dest.exists():
            dest = target_dir / f"{f.stem} ({counter}){f.suffix}"
            counter += 1
        shutil.move(str(f), dest)
        moved += 1
        if verbose:
            print(f"    saved {dest}")
    return moved, ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Download all WAMEX report documents into per-A-number folders."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", help="CSV file with an ANUMBER column")
    source.add_argument("--anumbers", nargs="+", type=int, help="A numbers directly, e.g. 5725 6285")
    parser.add_argument("--out-dir", default="reports", help="base output directory (default: reports)")
    parser.add_argument("--browser", choices=["firefox", "chrome"], default="firefox",
                        help="browser to drive (default: firefox; WAMEX downloads fail in Chrome)")
    parser.add_argument("--delay", type=float, default=10.0,
                        help="seconds to wait between reports (default: 10)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_DOWNLOAD_TIMEOUT,
                        help="max seconds to wait for each report's downloads (default: 300)")
    parser.add_argument("--page-timeout", type=float, default=DEFAULT_PAGE_TIMEOUT,
                        help="seconds to wait for a report page to render its download links (default: 30)")
    parser.add_argument("--retries", type=int, default=2,
                        help="retries when a report page shows no download links (default: 2)")
    parser.add_argument("--fresh-session", action="store_true",
                        help="clear cookies before each report (NOT recommended: the site's Incapsula bot protection stores its clearance in cookies; wiping them triggers a new bot challenge every report)")
    parser.add_argument("--block-cooldown", type=float, default=120.0,
                        help="seconds to wait when the site shows a block/challenge page before retrying (default: 120)")
    parser.add_argument("--max-block-retries", type=int, default=3,
                        help="block/cooldown retries per report before giving up (default: 3)")
    parser.add_argument("--dry-run", action="store_true",
                        help="create folders and write report URLs without launching a browser")
    parser.add_argument("--force", action="store_true",
                        help="re-download even if the report folder has a .complete marker")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.csv:
        anumbers = read_anumbers_from_csv(Path(args.csv))
    else:
        anumbers = args.anumbers
    if not anumbers:
        sys.exit("error: no A numbers to process")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run_log.txt"
    tee = Tee(log_path)
    sys.stdout = tee
    sys.stderr = tee

    log(f"wamex_download.py version {__version__}")
    log(f"python: {sys.version.split()[0]}")
    log(f"script file: {Path(__file__).resolve()}")
    log(f"output directory: {out_dir.resolve()}")
    log(f"log file: {log_path.resolve()}")
    log(f"{len(anumbers)} report(s) to process")
    if args.csv:
        log(f"input csv: {Path(args.csv).resolve()}")
    log(f"browser: {args.browser}; fresh-session: {args.fresh_session}; delay: {args.delay}s")

    if args.dry_run:
        for n in anumbers:
            folder = out_dir / folder_name(n)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "report_url.txt").write_text(report_url(n) + "\n", encoding="utf-8")
            log(f"  {folder_name(n)}  {report_url(n)}")
        log("Dry run complete: folders created, no downloads attempted.")
        return 0

    import tempfile

    with tempfile.TemporaryDirectory(prefix="wamex_dl_") as tmp:
        download_dir = Path(tmp)
        log(f"download staging directory: {download_dir}")
        log("starting browser...")
        driver = make_driver(args.browser, download_dir)
        log("browser started")
        ok, skipped, failed = 0, 0, []
        try:
            for i, n in enumerate(anumbers, start=1):
                folder = out_dir / folder_name(n)
                marker = folder / COMPLETE_MARKER
                if not args.force and marker.exists():
                    log(f"[{i}/{len(anumbers)}] {folder_name(n)}: already complete, skipping")
                    skipped += 1
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                log(f"[{i}/{len(anumbers)}] {folder_name(n)}: START -> {report_url(n)}")
                log(f"    folder: {folder.resolve()}")
                if args.fresh_session:
                    try:
                        driver.delete_all_cookies()
                    except Exception:
                        pass
                try:
                    moved, err = download_report(
                        driver, download_dir, n, folder, args.verbose,
                        args.timeout, args.page_timeout, args.retries,
                        args.block_cooldown, args.max_block_retries,
                    )
                except SystemExit:
                    raise
                except Exception as exc:
                    dump_debug(driver, folder)
                    moved, err = 0, f"unexpected error: {exc!r}"
                    log(f"    unexpected error traceback:")
                    for line in traceback.format_exc().splitlines():
                        log(f"    {line}")
                if err:
                    log(f"    FAILED: {err}")
                    failed.append(n)
                else:
                    marker.write_text(report_url(n) + "\n", encoding="utf-8")
                    log(f"    saved {moved} file(s) -> {folder}")
                    ok += 1
                if i < len(anumbers):
                    time.sleep(args.delay)
        finally:
            try:
                driver.quit()
            except Exception:
                pass
            log("browser closed")

        failed_path = out_dir / "_failed.txt"
        if failed:
            failed_path.write_text("\n".join(map(str, failed)) + "\n", encoding="utf-8")
            log(f"Done: {ok} succeeded, {skipped} skipped, {len(failed)} failed.")
            log(f"Failed A numbers saved to {failed_path}; re-run the script to retry them.")
            tee.close()
            return 1
        if failed_path.exists():
            failed_path.unlink()
        log(f"Done: {ok} succeeded, {skipped} skipped, 0 failed.")
        tee.close()
        return 0


if __name__ == "__main__":
    sys.exit(main())
