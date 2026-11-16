"""A deterministic landing page audit that scores a page from 0 to 100.

The score is what turns the studio from "build some pages" into an optimisation
loop: every check is computed from the files on disk, so the same page always
gets the same score, and every lost point comes with a concrete hint the builder
can act on. No model is involved in scoring.

Four categories add up to 100:

    SEO            25   title, meta description, headings, canonical, Open Graph
    Accessibility  25   alt text, accessible names, labels, landmarks, heading order
    Performance    20   page weight, no third-party requests, DOM size, viewport
    Content        30   length, keyword and feature coverage, sections, CTAs, readability
                        (and brand colours, when the brief sets a palette)
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from pagesmith.brief import Brief, normalise_hex

PAGE_FILES = ("index.html", "styles.css", "script.js")
REQUIRED_SECTIONS = ("hero", "features", "pricing", "testimonials", "faq")
CATEGORY_LABELS = {
    "seo": "SEO",
    "accessibility": "Accessibility",
    "performance": "Performance",
    "content": "Content",
}
_EXTERNAL = re.compile(r"^\s*(https?:)?//", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_STOPWORDS = {
    "a", "an", "and", "the", "with", "your", "you", "on", "of", "for", "to", "in", "every",
    "such", "as", "or", "by", "what", "is", "are", "that", "it", "its", "our", "from", "at",
}


@dataclass
class Check:
    id: str
    category: str
    label: str
    points: float
    earned: float
    detail: str
    hint: str

    @property
    def lost(self) -> float:
        return round(self.points - self.earned, 2)


@dataclass
class Report:
    score: float
    grade: str
    categories: dict[str, dict]
    checks: list[Check] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "grade": self.grade,
            "categories": self.categories,
            "checks": [{**asdict(c), "lost": c.lost} for c in self.checks],
        }

    def top_issues(self, limit: int = 6) -> list[Check]:
        failing = [c for c in self.checks if c.lost > 0]
        return sorted(failing, key=lambda c: c.lost, reverse=True)[:limit]

    def feedback(self, limit: int = 6) -> str:
        """The lost points as a short, actionable list for a builder."""
        issues = self.top_issues(limit)
        if not issues:
            return "Every check passes."
        return "\n".join(f"- [{c.category}] {c.label}: {c.detail}. Fix: {c.hint} (+{c.lost:g} pts)" for c in issues)


def grade_for(score: float) -> str:
    for floor, letter in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= floor:
            return letter
    return "F"


# --- text helpers -------------------------------------------------------------------


def _visible_text(soup: BeautifulSoup) -> str:
    body = soup.body or soup
    clone = BeautifulSoup(str(body), "html.parser")
    for tag in clone(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    return " ".join(clone.get_text(" ").split())


def _syllables(word: str) -> int:
    word = word.lower().strip("'’-")
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups) + len(re.findall(r"i(?=[aou])|ie(?=rr|t)|eu(?=m)|eo|ua", word))
    stem = word[:-1] if word.endswith("es") and not word.endswith(("ces", "ses", "zes", "ges", "xes", "shes", "ches")) else word
    if stem.endswith("e") and not stem.endswith(("le", "ee")) and count > 1:
        count -= 1
    return max(count, 1)


def flesch_reading_ease(text: str) -> float:
    """Flesch reading ease (higher is easier; 60 to 70 is plain English)."""
    sentences = max(1, len(re.findall(r"[.!?]+(?:\s|$)", text)))
    words = _WORD.findall(text)
    if not words:
        return 0.0
    syllables = sum(_syllables(w) for w in words)
    return round(206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syllables / len(words)), 1)


def _significant(phrase: str) -> list[str]:
    return [w for w in (t.lower() for t in _WORD.findall(phrase)) if w not in _STOPWORDS and len(w) > 2]


def _covers(text_lower: str, phrase: str, threshold: float = 0.6) -> bool:
    words = _significant(phrase)
    if not words:
        return True
    hits = sum(1 for w in words if re.search(rf"\b{re.escape(w[:max(4, len(w) - 2)])}", text_lower))
    return hits / len(words) >= threshold


def _accessible_name(tag: Tag) -> str:
    name = tag.get("aria-label") or tag.get("title") or tag.get_text(" ", strip=True)
    if not name:
        img = tag.find("img")
        if img is not None:
            name = img.get("alt", "")
    return (name or "").strip()


# --- the audit ----------------------------------------------------------------------


def audit_page(page_dir: str | Path, brief: Brief) -> Report:
    """Score the landing page in page_dir against the brief."""
    page_dir = Path(page_dir)
    html_path = page_dir / "index.html"
    if not html_path.exists() or not html_path.stat().st_size:
        missing = Check("page_exists", "content", "Page exists", 100, 0, "index.html is missing or empty",
                        "Write index.html, styles.css and script.js into your folder")
        return Report(0.0, "F", {k: {"label": v, "score": 0, "max": 0} for k, v in CATEGORY_LABELS.items()}, [missing])

    html = html_path.read_text(encoding="utf-8", errors="replace")
    css = _read(page_dir / "styles.css")
    js = _read(page_dir / "script.js")
    soup = BeautifulSoup(html, "html.parser")
    text = _visible_text(soup)
    text_lower = text.lower()

    checks: list[Check] = []
    checks += _seo(soup, brief)
    checks += _accessibility(soup)
    checks += _performance(soup, html, css, js)
    checks += _content(soup, text, text_lower, brief, css)

    categories = {}
    for key, label in CATEGORY_LABELS.items():
        mine = [c for c in checks if c.category == key]
        categories[key] = {
            "label": label,
            "score": round(sum(c.earned for c in mine), 1),
            "max": round(sum(c.points for c in mine), 1),
        }
    score = round(sum(c.earned for c in checks), 1)
    return Report(score, grade_for(score), categories, checks)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _seo(soup: BeautifulSoup, brief: Brief) -> list[Check]:
    out = []
    title = (soup.title.get_text(strip=True) if soup.title else "")
    n = len(title)
    out.append(Check("title_length", "seo", "Title tag length", 4, 4 if 30 <= n <= 65 else (2 if n else 0),
                     f"title is {n} characters", "Keep <title> between 30 and 65 characters"))

    meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    desc = (meta.get("content") or "").strip() if meta else ""
    n = len(desc)
    earned = 4 if 120 <= n <= 160 else (2 if 70 <= n <= 200 else 0)
    out.append(Check("meta_description", "seo", "Meta description", 4, earned,
                     f"meta description is {n} characters", "Add <meta name=\"description\"> of 120 to 160 characters"))

    h1s = soup.find_all("h1")
    out.append(Check("single_h1", "seo", "Exactly one H1", 4, 4 if len(h1s) == 1 else 0,
                     f"found {len(h1s)} <h1>", "Use exactly one <h1> for the main headline"))

    kw = brief.primary_keyword.lower()
    h1_text = " ".join(h.get_text(" ", strip=True) for h in h1s).lower()
    in_title, in_h1 = _covers(title.lower(), kw, 1.0), _covers(h1_text, kw, 1.0)
    out.append(Check("keyword_placement", "seo", "Primary keyword placement", 4, 2 * in_title + 2 * in_h1,
                     f"'{brief.primary_keyword}' in title: {'yes' if in_title else 'no'}, in H1: {'yes' if in_h1 else 'no'}",
                     f"Put '{brief.primary_keyword}' in both the <title> and the <h1>"))

    h2 = len(soup.find_all("h2"))
    out.append(Check("section_headings", "seo", "Section headings", 3, 3 if h2 >= 4 else round(3 * h2 / 4, 2),
                     f"found {h2} <h2>", "Give each main section its own <h2> (at least 4)"))

    html_tag = soup.find("html")
    has_lang = bool(html_tag and html_tag.get("lang"))
    out.append(Check("html_lang", "seo", "Document language", 2, 2 if has_lang else 0,
                     "lang attribute " + ("set" if has_lang else "missing"), "Add lang=\"en\" to <html>"))

    canonical = soup.find("link", rel=lambda v: v and "canonical" in (v if isinstance(v, list) else [v]))
    out.append(Check("canonical", "seo", "Canonical URL", 2, 2 if canonical and canonical.get("href") else 0,
                     "canonical " + ("present" if canonical else "missing"), "Add <link rel=\"canonical\" href=\"...\">"))

    og = {m.get("property") for m in soup.find_all("meta", property=True)}
    need = {"og:title", "og:description", "og:type"}
    have = len(need & og)
    out.append(Check("open_graph", "seo", "Open Graph tags", 2, round(2 * have / 3, 2),
                     f"{have}/3 of og:title, og:description, og:type", "Add og:title, og:description and og:type meta tags"))
    return out


def _accessibility(soup: BeautifulSoup) -> list[Check]:
    out = []
    imgs = soup.find_all("img")
    bad = [i for i in imgs if i.get("alt") is None or (not i.get("alt", "").strip() and i.get("role") != "presentation")]
    earned = 5 if not imgs else round(5 * (len(imgs) - len(bad)) / len(imgs), 2)
    out.append(Check("img_alt", "accessibility", "Image alt text", 5, earned,
                     f"{len(bad)} of {len(imgs)} images lack alt text", "Give every <img> a descriptive alt"))

    controls = soup.find_all(["a", "button"])
    unnamed = [c for c in controls if not _accessible_name(c)]
    earned = 5 if not controls else round(5 * (len(controls) - len(unnamed)) / len(controls), 2)
    out.append(Check("control_names", "accessibility", "Links and buttons have names", 5, earned,
                     f"{len(unnamed)} of {len(controls)} links/buttons have no text or aria-label",
                     "Give every link and button visible text or an aria-label"))

    fields = [f for f in soup.find_all(["input", "select", "textarea"])
              if f.get("type", "").lower() not in {"hidden", "submit", "button", "reset", "image"}]
    labelled_ids = {lbl.get("for") for lbl in soup.find_all("label") if lbl.get("for")}
    unlabelled = [f for f in fields if not (f.get("aria-label") or f.get("aria-labelledby")
                                            or (f.get("id") and f.get("id") in labelled_ids)
                                            or f.find_parent("label"))]
    earned = 4 if not fields else round(4 * (len(fields) - len(unlabelled)) / len(fields), 2)
    out.append(Check("form_labels", "accessibility", "Form fields are labelled", 4, earned,
                     f"{len(unlabelled)} of {len(fields)} fields have no label",
                     "Pair every input with <label for> or an aria-label"))

    landmarks = [name for name in ("header", "nav", "main", "footer") if soup.find(name)]
    out.append(Check("landmarks", "accessibility", "Page landmarks", 4, len(landmarks),
                     f"has {', '.join(landmarks) or 'none'} of header, nav, main, footer",
                     "Wrap the page in <header>, <nav>, <main> and <footer>"))

    levels = [int(h.name[1]) for h in soup.find_all(re.compile(r"^h[1-6]$"))]
    skips = sum(1 for a, b in zip(levels, levels[1:]) if b > a + 1)
    out.append(Check("heading_order", "accessibility", "Heading order", 4, 4 if levels and not skips else (0 if not levels else 2),
                     f"{skips} skipped heading level(s)", "Do not jump heading levels (h2 then h4)"))

    main = soup.find("main")
    main_id = main.get("id") if main else None
    skip = soup.find("a", href=f"#{main_id}") if main_id else None
    out.append(Check("skip_link", "accessibility", "Skip to content link", 3, 3 if skip else 0,
                     "skip link " + ("present" if skip else "missing"),
                     "Add <a class=\"skip-link\" href=\"#main\">Skip to content</a> and give <main> id=\"main\""))
    return out


def _performance(soup: BeautifulSoup, html: str, css: str, js: str) -> list[Check]:
    out = []
    kb = round(sum(len(s.encode("utf-8")) for s in (html, css, js)) / 1024, 1)
    out.append(Check("page_weight", "performance", "Page weight", 6, 6 if kb <= 60 else (3 if kb <= 100 else 0),
                     f"{kb} KB of HTML, CSS and JS", "Keep the three files under 60 KB in total"))

    external = []
    for tag, attr in (("script", "src"), ("link", "href"), ("img", "src"), ("iframe", "src"), ("source", "src")):
        for el in soup.find_all(tag):
            if tag == "link" and "canonical" in (el.get("rel") or []):
                continue
            if _EXTERNAL.match(el.get(attr, "") or ""):
                external.append(el.get(attr))
    external += re.findall(r"url\(\s*['\"]?((?:https?:)?//[^)'\"]+)", css)
    external += re.findall(r"@import\s+(?:url\()?['\"]?((?:https?:)?//[^'\")]+)", css)
    out.append(Check("no_third_party", "performance", "No third-party requests", 6, 6 if not external else 0,
                     f"{len(external)} external resource(s)" + (f", e.g. {external[0]}" if external else ""),
                     "Inline or drop external fonts, scripts and images; ship everything locally"))

    nodes = len(soup.find_all(True))
    out.append(Check("dom_size", "performance", "DOM size", 4, 4 if nodes <= 900 else (2 if nodes <= 1500 else 0),
                     f"{nodes} elements", "Keep the page under 900 elements"))

    viewport = soup.find("meta", attrs={"name": "viewport"})
    scripts = [s for s in soup.find_all("script", src=True)]
    blocking = [s for s in scripts if not (s.has_attr("defer") or s.has_attr("async") or s.get("type") == "module")
                and s.find_parent("head")]
    earned = (2 if viewport else 0) + (2 if not blocking else 0)
    out.append(Check("render_path", "performance", "Viewport and non-blocking JS", 4, earned,
                     f"viewport {'set' if viewport else 'missing'}, {len(blocking)} render-blocking script(s)",
                     "Add <meta name=\"viewport\"> and load script.js with defer"))
    return out


def _css_colours(css: str) -> set[str]:
    """Every hex colour in the stylesheet, normalised to #rrggbb."""
    found = set()
    for raw in re.findall(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", css):
        found.add(normalise_hex(raw))
    return found


def _brand(css: str, brief: Brief) -> Check | None:
    palette = brief.style.palette() if brief.style else {}
    if not palette:
        return None
    used = _css_colours(css)
    missing = {role: hex_ for role, hex_ in palette.items() if hex_ not in used}
    detail = f"{len(palette) - len(missing)}/{len(palette)} brand colours in styles.css"
    if missing:
        detail += "; missing " + ", ".join(f"{role} {hex_}" for role, hex_ in missing.items())
    return Check("brand_colours", "content", "Brand colours", 4, round(4 * (len(palette) - len(missing)) / len(palette), 2),
                 detail, "Define the brand palette as CSS custom properties in :root (exact hex values) and use them")


def _content(soup: BeautifulSoup, text: str, text_lower: str, brief: Brief, css: str = "") -> list[Check]:
    out = []
    # With a brand palette in the brief, 4 points move to the colour check so Content still totals 30.
    brand = _brand(css, brief)
    length_pts, keyword_pts = (3, 6) if brand else (5, 8)
    words = len(_WORD.findall(text))
    full = 450 <= words <= 1400
    earned = length_pts if full else (length_pts * 0.4 if 300 <= words <= 2000 else 0)
    out.append(Check("word_count", "content", "Copy length", length_pts, earned,
                     f"{words} words of visible copy", "Aim for 450 to 1,400 words of real, specific copy"))

    hit = [k for k in brief.keywords if _covers(text_lower, k, 1.0)]
    missing = [k for k in brief.keywords if k not in hit]
    out.append(Check("keyword_coverage", "content", "Keyword coverage", keyword_pts,
                     round(keyword_pts * len(hit) / len(brief.keywords), 2),
                     f"{len(hit)}/{len(brief.keywords)} keywords used" + (f"; missing: {', '.join(missing)}" if missing else ""),
                     "Work each brief keyword naturally into the copy"))

    covered = [f for f in brief.features if _covers(text_lower, f)]
    out.append(Check("feature_coverage", "content", "Feature coverage", 4, round(4 * len(covered) / len(brief.features), 2),
                     f"{len(covered)}/{len(brief.features)} brief features described",
                     "Describe every feature from the brief"))

    present = [s for s in REQUIRED_SECTIONS if soup.find(id=s)]
    absent = [s for s in REQUIRED_SECTIONS if s not in present]
    out.append(Check("sections", "content", "Required sections", 7, round(7 * len(present) / len(REQUIRED_SECTIONS), 2),
                     f"{len(present)}/{len(REQUIRED_SECTIONS)} sections" + (f"; missing id: {', '.join(absent)}" if absent else ""),
                     "Add sections with id=\"hero\", \"features\", \"pricing\", \"testimonials\" and \"faq\""))

    ctas = soup.find_all(attrs={"data-cta": True})
    out.append(Check("cta_count", "content", "Calls to action", 3, 3 if len(ctas) >= 2 else 1.5 * len(ctas),
                     f"{len(ctas)} element(s) marked data-cta",
                     f"Repeat '{brief.call_to_action}' at least twice (hero and closing), each marked data-cta"))

    ease = flesch_reading_ease(text)
    out.append(Check("readability", "content", "Readability", 3, 3 if ease >= 55 else (1.5 if ease >= 45 else 0),
                     f"Flesch reading ease {ease}", "Use shorter sentences and plainer words (target 55+)"))
    if brand:
        out.append(brand)
    return out
