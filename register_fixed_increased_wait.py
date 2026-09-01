"""
YES x Microsoft AI Skills - Bulk Registration Automation
Reads user data from users.csv and submits the registration form for each row.

Setup:
    pip install playwright
    playwright install chromium

Run:
    python register_fixed.py
"""

import csv
import random
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── Configuration ────────────────────────────────────────────────────────────
FORM_URL = (
    "https://yes-aiskills.co.za/register/"
    "?utm_source=YES+Landing+Page"
    "&utm_medium=Website"
    "&utm_campaign=YES+x+Microsoft+Ai+Skills+Certifications"
)
CSV_FILE  = Path(__file__).parent / "2.csv"
LOG_FILE  = Path(__file__).parent / "registration_log.txt"
HEADLESS  = False
SLOW_MO   = 300      # slightly slower actions = more human-like

TIMEOUT   = 60_000   # increased to 60s per element wait

# Seconds to wait after page load before touching anything (CleanTalk init)
# INCREASED: added 2-3 min delay -> now 210s to 300s (3.5 to 5 min)
CLEANTALK_WAIT = (210, 300)

# Seconds to wait before clicking Send
# INCREASED: added 2-3 min delay -> now 180s to 270s (3 to 4.5 min)
PRE_SUBMIT_WAIT = (180, 270)

# Minutes to wait between users
# INCREASED: added 3 min delay -> now 11 to 15 min
BETWEEN_USERS_WAIT_MIN = (11, 15)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── Exact option values from the live form ────────────────────────────────────

PROVINCE_OPTIONS = [
    "Gauteng", "North-West", "Limpopo", "Northern Cape",
    "Western cape",
    "Free State", "KwaZulu-Natal", "Eastern Cape", "Mpumalanga",
]

AGE_OPTIONS = {
    "15-18":  "15",
    "19-24":  "19",
    "25-34":  "25",
    "35+":    "35+",
}

QUALIFICATION_OPTIONS = {
    "no formal education":  "No formal education",
    "gr 9":                 "Gr 9",
    "grade 9":              "Gr 9",
    "matric":               "Matric/Grade 12",
    "grade 12":             "Matric/Grade 12",
    "matric/grade 12":      "Matric/Grade 12",
    "diploma":              "Diploma",
    "bachelor":             "Bachelor's Degree",
    "bachelor's degree":    "Bachelor's Degree",
    "undergraduate":        "Bachelor's Degree",
    "postgraduate":         "Postgraduate Degree",
    "postgraduate degree":  "Postgraduate Degree",
}

SKILLS_OPTIONS = [
    "Basic to intermediate computer skills and MS Office 365",
    "Some coding experience (Python, HTML, JavaScript, etc.)",
    "Data or spreadsheets (Excel, PowerBI, SQL)",
    "Social Media & Digital Tools (Adobe, Canva, TikTok, Editing apps etc.)",
    "No formal tech skills, but i am very curious to learn",
]

SKILLS_ALIAS = {
    "computer":     SKILLS_OPTIONS[0],
    "ms office":    SKILLS_OPTIONS[0],
    "coding":       SKILLS_OPTIONS[1],
    "code":         SKILLS_OPTIONS[1],
    "data":         SKILLS_OPTIONS[2],
    "excel":        SKILLS_OPTIONS[2],
    "social media": SKILLS_OPTIONS[3],
    "canva":        SKILLS_OPTIONS[3],
    "no skills":    SKILLS_OPTIONS[4],
    "curious":      SKILLS_OPTIONS[4],
}

SECTOR_OPTIONS = [
    "Marketing, PR & Media",
    "Construction, Manufacturing, Mining & Transportation",
    "IT & Telecommunications ",
    "Agriculture, Agri-processing & FMCG",
    "Auditing, Consulting, Legal & Professional Services",
    "Banking, Investment & Finance",
    "E-commerce & Retail",
    "Diplomacy, Government & Non-Profit",
    "Other",
    "N/A",
]

PATHWAY_OPTIONS = [
    "AI Transformation Leader",
    "Azure Fundamentals",
    "Azure Data Fundamentals",
    "AI Business Professional",
    "GitHub Foundations",
    "Power Platform Fundamentals",
    "Microsoft 365 Certified: Copilot and Agent Administration Fundamentals",
    "Security, Compliance, and Identity Fundamentals",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def n(value: str) -> str:
    return value.strip().lower()


_JS_SELECT = """
([selector, search]) => {
    const el = document.querySelector(selector);
    if (!el) return 'ERR: element not found: ' + selector;

    const norm = s => s.trim().replace(/\\s+/g, ' ').toLowerCase();
    const t = norm(search);

    let opt = Array.from(el.options).find(o => norm(o.text) === t);
    if (!opt) opt = Array.from(el.options).find(o => t.startsWith(norm(o.text).split(' ')[0]) && norm(o.text).startsWith(norm(o.text).split(' ')[0]));
    if (!opt) opt = Array.from(el.options).find(o => norm(o.text).includes(t));
    if (!opt) opt = Array.from(el.options).find(o => t.includes(norm(o.text)) && norm(o.text).length > 1);

    if (!opt) {
        const available = Array.from(el.options).map(o => o.text.trim()).join(' | ');
        return 'ERR: no match for [' + search + '] in: ' + available;
    }

    el.value = opt.value;
    el.dispatchEvent(new Event('change', {bubbles: true}));
    el.dispatchEvent(new Event('input',  {bubbles: true}));
    return 'OK: ' + opt.text.trim();
}
"""


def js_select(page, selector: str, search_text: str):
    result = page.evaluate(_JS_SELECT, [selector, search_text])
    if result.startswith("ERR:"):
        raise ValueError(f"js_select({selector!r}, {search_text!r}) → {result}")
    log.debug("    js_select %s → %s", selector, result)
    return result


def resolve_skill(value: str) -> str:
    vl = value.strip().lower()
    return SKILLS_ALIAS.get(vl, value.strip())


def resolve_pathway(value: str) -> str:
    vl = n(value)
    for opt in PATHWAY_OPTIONS:
        if n(opt) == vl or n(opt).startswith(vl) or vl in n(opt):
            return opt
    return value.strip()


# ── Simulate human-like typing with random delays ─────────────────────────────
def human_fill(page, selector: str, text: str):
    """Fill a field character by character with small random delays."""
    el = page.locator(selector)
    el.click()
    page.wait_for_timeout(random.randint(200, 500))
    for char in text:
        el.type(char, delay=random.randint(40, 120))
    page.wait_for_timeout(random.randint(200, 400))


# ── Core: fill & submit one registration ─────────────────────────────────────

def register_user(page, row: dict) -> bool:
    log.info("Registering %s %s <%s>", row["name"], row["surname"], row["email"])
    page.goto(FORM_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=TIMEOUT)

    # Let CleanTalk JS fully initialise — INCREASED wait
    wait_s = random.randint(*CLEANTALK_WAIT)
    log.info("  Waiting %ds for anti-spam init…", wait_s)
    page.wait_for_timeout(wait_s * 1_000)

    try:
        # ── Text inputs (human-like typing) ──────────────────────────────
        human_fill(page, "#form-field-name",    row["name"].strip())
        human_fill(page, "#form-field-surname", row["surname"].strip())
        human_fill(page, "#form-field-contact", row["contact_number"].strip())
        human_fill(page, "#form-field-email",   row["email"].strip())

        # Small pause between sections — looks more natural
        page.wait_for_timeout(random.randint(800, 1500))

        # ── SA Citizen ────────────────────────────────────────────────────
        citizen = row["sa_citizen"].strip()
        js_select(page, "#form-field-citizen", citizen)

        id_num = row.get("id_number", "").strip()
        if citizen.lower() == "yes" and id_num:
            human_fill(page, "#form-field-id", id_num)

        page.wait_for_timeout(random.randint(500, 1000))

        # ── Dropdowns ─────────────────────────────────────────────────────
        js_select(page, "#form-field-province", row["province"].strip())
        page.wait_for_timeout(random.randint(300, 700))

        age_search = AGE_OPTIONS.get(n(row["age"]), row["age"].strip())
        js_select(page, "#form-field-age", age_search)
        page.wait_for_timeout(random.randint(300, 700))

        js_select(page, "#form-field-gender", row["gender"].strip())
        page.wait_for_timeout(random.randint(300, 700))

        js_select(page, "#form-field-race", row["race"].strip())
        page.wait_for_timeout(random.randint(300, 700))

        js_select(page, "#form-field-abled", row["differently_abled"].strip())
        page.wait_for_timeout(random.randint(300, 700))

        qual_search = QUALIFICATION_OPTIONS.get(n(row["highest_qualification"]),
                                                row["highest_qualification"].strip())
        js_select(page, "#form-field-qualification", qual_search)
        page.wait_for_timeout(random.randint(300, 700))

        js_select(page, "#form-field-skills", resolve_skill(row["skills"]))
        page.wait_for_timeout(random.randint(300, 700))

        employed = row["employed"].strip()
        js_select(page, "#form-field-employment", employed)
        page.wait_for_timeout(random.randint(300, 700))

        sector_raw = row.get("employment_sector", "").strip()
        if n(employed) in ("yes", "self-employed") and sector_raw:
            js_select(page, "#form-field-sector", sector_raw)
        else:
            js_select(page, "#form-field-sector", "N/A")
        page.wait_for_timeout(random.randint(300, 700))

        js_select(page, "#form-field-pathway", resolve_pathway(row["certifications"]))
        page.wait_for_timeout(random.randint(500, 1000))

        # ── Consent checkbox ──────────────────────────────────────────────
        if n(row["consent"]) == "yes":
            consent_cb = page.locator("#form-field-privacy")
            if not consent_cb.is_checked():
                consent_cb.check()

        # ── Scroll Send button into view ───────────────────────────────────
        page.get_by_role("button", name="Send").scroll_into_view_if_needed()

        # ── Pre-submit pause ───────────────────────────────────────────────
        pre_s = random.randint(*PRE_SUBMIT_WAIT)
        log.info("  Pre-submit pause %ds…", pre_s)
        page.wait_for_timeout(pre_s * 1_000)

        # ── Click Send ────────────────────────────────────────────────────
        log.info("  Clicking Send…")
        page.get_by_role("button", name="Send").click(timeout=TIMEOUT)

        # ── Wait for page response ────────────────────────────────────────
        try:
            page.wait_for_function(
                """() => {
                    const t = document.body.innerText.toLowerCase();
                    return t.includes('thank') || t.includes('success') ||
                           t.includes('submitted') || t.includes('registered') ||
                           t.includes('spam') || t.includes('forbidden') ||
                           t.includes('error') || t.includes('invalid');
                }""",
                timeout=60_000,
            )
        except PlaywrightTimeout:
            log.warning("  No response after 60s — screenshot saved")
            page.screenshot(path=str(Path(__file__).parent / f"timeout_{row['email']}.png"))
            return False

        try:
            page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except PlaywrightTimeout:
            pass

        try:
            body = page.content().lower()
        except Exception:
            log.info("  SUCCESS (redirect detected): %s %s", row["name"], row["surname"])
            return True

        if any(kw in body for kw in ("thank", "success", "submitted", "registered")):
            log.info("  SUCCESS: %s %s", row["name"], row["surname"])
            return True
        elif any(kw in body for kw in ("spam", "forbidden", "cleantalk")):
            log.error("  BLOCKED by anti-spam: %s %s — screenshot saved",
                      row["name"], row["surname"])
            page.screenshot(path=str(Path(__file__).parent / f"spam_{row['email']}.png"))
            return False
        else:
            log.warning("  FORM ERROR for %s %s — screenshot saved",
                        row["name"], row["surname"])
            page.screenshot(path=str(Path(__file__).parent / f"fail_{row['email']}.png"))
            return False

    except PlaywrightTimeout as e:
        log.error("  TIMEOUT for %s %s: %s", row["name"], row["surname"], e)
        page.screenshot(path=str(Path(__file__).parent / f"timeout_{row['email']}.png"))
        return False
    except Exception as e:
        log.error("  ERROR for %s %s: %s", row["name"], row["surname"], e)
        page.screenshot(path=str(Path(__file__).parent / f"error_{row['email']}.png"))
        return False


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    log.info("Loaded %d user(s) from %s", len(rows), CSV_FILE)
    results = {"success": 0, "failed": 0}

    with sync_playwright() as p:
        PROXY = None
        launch_args = dict(headless=HEADLESS, slow_mo=SLOW_MO)
        if PROXY:
            launch_args["proxy"] = {"server": PROXY}

        browser = p.chromium.launch(**launch_args)
        page = browser.new_page()
        page.set_default_timeout(TIMEOUT)

        for i, row in enumerate(rows, 1):
            log.info("── User %d / %d ──────────────────────────────", i, len(rows))
            ok = register_user(page, row)
            results["success" if ok else "failed"] += 1
            if i < len(rows):
                wait_min = random.randint(*BETWEEN_USERS_WAIT_MIN)
                log.info("  Waiting %d min before next user…", wait_min)
                page.wait_for_timeout(wait_min * 60 * 1_000)

        browser.close()

    log.info("Done. Success: %d  |  Failed: %d", results["success"], results["failed"])


if __name__ == "__main__":
    main()
