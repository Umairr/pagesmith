from pathlib import Path

import pytest

from pagesmith.audit import audit_page, flesch_reading_ease, grade_for
from pagesmith.brief import Brief

BRIEF = Brief(
    product="Acme Notes",
    tagline="Notes that organise themselves.",
    description="A note taking app.",
    features=["Instant full text search", "Offline sync across devices", "Shared team notebooks"],
    keywords=["note taking app", "offline sync"],
    audiences=["Students"],
    call_to_action="Try it free",
)

GOOD_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Acme Notes, the note taking app that organises itself</title>
  <meta name="description" content="Acme Notes is the note taking app with instant full text search, offline sync across every device and shared team notebooks. Try it free today.">
  <link rel="canonical" href="https://example.com/">
  <meta property="og:title" content="Acme Notes">
  <meta property="og:description" content="The note taking app that organises itself.">
  <meta property="og:type" content="website">
  <link rel="stylesheet" href="styles.css">
  <script src="script.js" defer></script>
</head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>
  <header><nav><a href="#features">Features</a> <a href="#pricing">Pricing</a></nav></header>
  <main id="main">
    <section id="hero"><h1>The note taking app that keeps up with you</h1>
      <p>{copy}</p><a href="#pricing" data-cta>Try it free</a></section>
    <section id="features"><h2>Features</h2>
      <p>Instant full text search finds any note. Offline sync across devices keeps work safe. Shared team notebooks keep everyone on the same page.</p></section>
    <section id="pricing"><h2>Pricing</h2><p>Free for one person. Teams pay a small fee.</p></section>
    <section id="testimonials"><h2>What people say</h2><p>Sam, student: it is fast.</p></section>
    <section id="faq"><h2>Questions</h2><p>Is there offline sync? Yes.</p>
      <form><label for="email">Email</label><input id="email" type="email"></form>
      <button type="submit" data-cta>Try it free</button></section>
  </main>
  <footer><p>Acme Notes</p></footer>
</body>
</html>"""

COPY = " ".join(["We help you write things down. It is quick to start and easy to use."] * 40)


@pytest.fixture
def good_page(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text(GOOD_PAGE.replace("{copy}", COPY), encoding="utf-8")
    (tmp_path / "styles.css").write_text("body{font-family:system-ui}", encoding="utf-8")
    (tmp_path / "script.js").write_text("console.log('ok')", encoding="utf-8")
    return tmp_path


def test_good_page_scores_full_marks(good_page: Path) -> None:
    report = audit_page(good_page, BRIEF)
    lost = {c.id: c.detail for c in report.checks if c.lost}
    assert report.score == 100, lost
    assert report.grade == "A"
    assert sum(c["max"] for c in report.categories.values()) == 100


def test_missing_page_scores_zero(tmp_path: Path) -> None:
    report = audit_page(tmp_path, BRIEF)
    assert report.score == 0
    assert "index.html" in report.feedback()


def test_external_resources_lose_points(good_page: Path) -> None:
    html = (good_page / "index.html").read_text()
    html = html.replace("</head>", '<link rel="stylesheet" href="https://fonts.example.com/x.css"></head>')
    (good_page / "index.html").write_text(html)
    report = audit_page(good_page, BRIEF)
    check = next(c for c in report.checks if c.id == "no_third_party")
    assert check.earned == 0
    assert "fonts.example.com" in check.detail


def test_missing_sections_and_h1_are_reported(good_page: Path) -> None:
    html = (good_page / "index.html").read_text()
    html = html.replace('id="faq"', 'id="questions"').replace("<h1>", "<h2>").replace("</h1>", "</h2>")
    (good_page / "index.html").write_text(html)
    report = audit_page(good_page, BRIEF)
    issues = {c.id for c in report.top_issues(20)}
    assert {"single_h1", "sections"} <= issues
    assert "faq" in next(c for c in report.checks if c.id == "sections").detail


def test_feedback_is_sorted_by_points_lost(good_page: Path) -> None:
    (good_page / "index.html").write_text("<html><body><p>Hello</p></body></html>")
    issues = audit_page(good_page, BRIEF).top_issues(10)
    assert [c.lost for c in issues] == sorted((c.lost for c in issues), reverse=True)


def test_score_is_deterministic(good_page: Path) -> None:
    assert audit_page(good_page, BRIEF).to_dict() == audit_page(good_page, BRIEF).to_dict()


def test_readability_and_grades() -> None:
    assert flesch_reading_ease("The cat sat on the mat. It was warm.") > 90
    assert flesch_reading_ease("Organisational interdependencies necessitate comprehensive reconsideration.") < 30
    assert [grade_for(s) for s in (95, 85, 75, 65, 10)] == ["A", "B", "C", "D", "F"]
