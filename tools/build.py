#!/usr/bin/env python3
"""Build https://satolap.github.io/terraform-msgraph-modules/ from the latest public release.

Facts come only from the public repository satolap/terraform-msgraph-modules at its latest release tag:
the release notes (module counts), the tag's tree (which verified modules exist) and each verified module's
README.md, rendered with GitHub's own Markdown API (the same sanitised HTML github.com shows).

    python3 tools/build.py            # rebuild everything for the latest release
    python3 tools/build.py --audit    # design and accessibility facts (contrast, headings, alt text, sizes)
    python3 tools/build.py --check    # print whether the deployed site is older than the latest release
                                      # (sets stale=true|false for GitHub Actions)

Output goes to _site/ (not committed). Preview: python3 -m http.server -d _site, then open /terraform-msgraph-modules/.

Standard library only; needs the gh CLI signed in (read-only API calls). See README.md for the runbook.
"""
from __future__ import annotations

import html
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys

REPO = "satolap/terraform-msgraph-modules"
BASE = "/terraform-msgraph-modules"
SITE_URL = "https://satolap.github.io" + BASE + "/"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "_site")            # build output; deployed by .github/workflows/pages.yml, not committed
STATIC = os.path.join(ROOT, "static")         # copied as-is into _site (redirect, styles, logo)
OUT = os.path.join(SITE, BASE.strip("/"))
TEMPLATES = os.path.join(ROOT, "tools", "templates")
STAMP = os.path.join(OUT, "release.json")

# Catalog groups, in display order: (title, path prefixes under verified/). Unknown modules land in "Other".
GROUPS = [
    ("Directory", ["users", "groups", "directory/", "naming"]),
    ("Applications", ["applications", "servicePrincipals", "oauth2PermissionGrants"]),
    ("Entitlement management", ["identityGovernance/entitlementManagement/", "compositions/connected-organization-access"]),
    ("Identity governance", ["identityGovernance/accessReviews/", "identityGovernance/lifecycleWorkflows/",
                             "identityGovernance/privilegedAccess/", "identityGovernance/termsOfUse/"]),
    ("Role management", ["roleManagement/"]),
    ("Conditional Access and policies", ["identity/conditionalAccess/", "policies/"]),
    ("Security baseline", ["security-baseline/"]),
]
STRIP = ["identityGovernance/entitlementManagement/", "identityGovernance/", "identity/conditionalAccess/",
         "roleManagement/", "security-baseline/", "directory/"]


def gh(*args: str, data: dict | None = None) -> str:
    cmd = ["gh", "api", *args]
    if data is not None:
        cmd += ["--input", "-"]
    r = subprocess.run(cmd, input=json.dumps(data) if data is not None else None, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"gh api {' '.join(args)[:120]} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def latest_release() -> dict:
    rel = json.loads(gh(f"repos/{REPO}/releases/latest"))
    body = rel.get("body") or ""
    counts = {}
    for key in ("v1.0", "beta", "verified"):
        m = re.search(rf"^- {re.escape(key)}: (\d+) modules", body, re.M)
        counts[key] = int(m.group(1)) if m else None
    m = re.search(r"^- Tested provider `microsoft/msgraph`: `([^`]+)`", body, re.M)
    return {"tag": rel["tag_name"], "published": rel.get("published_at", ""), "url": rel["html_url"], "counts": counts,
            "provider_tested": m.group(1) if m else "",
            "assets": sorted(a["name"] for a in rel.get("assets", []))}


def verified_modules(tag: str) -> list[str]:
    tree = json.loads(gh(f"repos/{REPO}/git/trees/{tag}?recursive=1"))
    mods = set()
    for item in tree["tree"]:
        p = item["path"]
        if p.startswith("verified/") and p.endswith("/main.tf") and "/tests/" not in p and "/examples/" not in p:
            mods.add(p[len("verified/"):-len("/main.tf")])
    readmes = {i["path"] for i in tree["tree"]}
    return sorted(m for m in mods if f"verified/{m}/README.md" in readmes)


def group_of(mod: str) -> str:
    for title, prefixes in GROUPS:
        if any(mod == p.rstrip("/") or mod.startswith(p if p.endswith("/") else p + "/") or mod == p for p in prefixes):
            return title
    return "Other"


def short(mod: str) -> str:
    for p in STRIP:
        if mod.startswith(p):
            return mod[len(p):]
    return mod


def page_url(mod: str) -> str:
    return f"{BASE}/modules/{mod}/"


def rewrite_links(md: str, mod: str, tag: str, mods: set[str]) -> str:
    """Relative links: to another verified module's README -> its site page; anything else -> GitHub at the tag."""
    here = f"verified/{mod}"

    def fix(m: re.Match) -> str:
        bang, text, target, title = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        if re.match(r"^(https?:|mailto:|#)", target):
            return m.group(0)
        path, _, frag = target.partition("#")
        full = posixpath.normpath(posixpath.join(here, path))
        if not bang:
            cand = full[:-len("/README.md")] if full.endswith("/README.md") else full.rstrip("/")
            if cand.startswith("verified/") and cand[len("verified/"):] in mods:
                return f"[{text}]({page_url(cand[len('verified/'):])}{'#' + frag if frag else ''}{title})"
        kind = "raw" if bang else "blob"
        url = (f"https://raw.githubusercontent.com/{REPO}/{tag}/{full}" if kind == "raw"
               else f"https://github.com/{REPO}/blob/{tag}/{full}")
        return f"{bang}[{text}]({url}{'#' + frag if frag else ''}{title})"

    return re.sub(r'(!?)\[([^\]]*)\]\(([^)\s]+)(\s+"[^"]*")?\)', fix, md)


def summary_and_assurance(md: str) -> tuple[str, str]:
    body = re.sub(r"<!--\s*([\w-]+):start\s*-->.*?<!--\s*\1:end\s*-->", "", md, flags=re.S)  # generated blocks
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    m = re.search(r"Assurance: \*\*([^*]+)\*\*(?: \(([^)]*)\))?", md)
    assurance = (m.group(1) + (f" ({m.group(2)})" if m.group(2) else "")) if m else ""
    summ = ""
    for para in re.split(r"\n\s*\n", body):
        t = para.strip()
        if not t or t.startswith(("#", "!", "|", "```", "<", "-", "*", "Uses beta", "Assurance", "This module's state")):
            continue
        summ = re.sub(r"\s+", " ", t)
        break
    summ = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", summ)  # plain text for cards
    summ = re.sub(r"(\*\*|__)(.+?)\1", r"\2", summ)
    return summ, assurance.replace("`", "")


def card_text(summ: str, limit: int = 230) -> str:
    """Cards stay scannable; the module page has the full text."""
    if len(summ) <= limit:
        return summ
    cut = summ[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    if cut.count("`") % 2:
        cut = cut.rsplit("`", 1)[0].rstrip()
    return cut + "…"


def requirements(md: str) -> dict[str, str]:
    """The minimum Terraform and provider versions from the README's Requirements table."""
    sec = re.search(r"^## Requirements\s*\n(.*?)(?=^## |\Z)", md, re.M | re.S)
    if not sec:
        return {}
    return {n: v.strip() for n, v in re.findall(r"^\|\s*(terraform|msgraph)\s*\|\s*([^|]+?)\s*\|", sec.group(1), re.M)}


def version_key(constraint: str) -> tuple[int, ...]:
    m = re.search(r"(\d+(?:\.\d+)*)", constraint)
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def satisfies(constraint: str, version: str) -> bool:
    """Does a version meet a Terraform constraint of the forms the READMEs use (>=, >, <=, <, =, ~>)?"""
    v = version_key(version)
    for op, val in re.findall(r"(>=|<=|>|<|=|~>)\s*(\d+(?:\.\d+)*)", constraint):
        c = version_key(val)
        if op == ">=" and not v >= c or op == ">" and not v > c or op == "<=" and not v <= c or op == "<" and not v < c:
            return False
        if op == "=" and v != c:
            return False
        if op == "~>" and not (v >= c and v[:len(c) - 1] == c[:-1]):
            return False
    return True


def provider_line(reqs: dict[str, dict[str, str]], tested: str) -> str:
    """One true sentence about provider versions: the tested version satisfies every verified module, or not."""
    cons = [r["msgraph"] for r in reqs.values() if r.get("msgraph")]
    if tested and cons and all(satisfies(c, tested) for c in cons):
        return (f"<code>microsoft/msgraph</code> {html.escape(tested)}, the version the release was tested with, "
                f"satisfies every verified module's provider constraint")
    return "each module page states the <code>microsoft/msgraph</code> versions it accepts"


def floor_versions(reqs: dict[str, dict[str, str]]) -> dict[str, str]:
    """Per tool, the highest minimum across modules: what a root needs to use every verified module."""
    out = {}
    for name in ("terraform", "msgraph"):
        vals = [r[name] for r in reqs.values() if r.get(name)]
        if vals:
            out[name] = re.search(r"\d+(?:\.\d+)*", max(vals, key=version_key)).group(0)
    return out


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def heading_ids(body: str) -> str:
    """Give README headings the ids github.com gives them (the Markdown API leaves them out), so links like
    #inputs work and the "On this page" list can be built from the headings."""
    seen: dict[str, int] = {}

    def add(m: re.Match) -> str:
        level, attrs, inner = m.group(1), m.group(2), m.group(3)
        if " id=" in attrs:
            return m.group(0)
        text = html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()
        base = re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")
        n = seen.get(base, 0)
        seen[base] = n + 1
        hid = base if n == 0 else f"{base}-{n}"
        return f'<h{level}{attrs} id="{html.escape(hid)}">{inner}</h{level}>'

    return re.sub(r"<h([1-6])((?:\s[^>]*)?)>(.*?)</h\1>", add, body, flags=re.S)


def wrap_tables(body: str) -> str:
    """Make each README table and code block a labelled scroll region that keyboard users can focus and
    scroll (WCAG 2.1.1). Labels name the section they sit in and stay unique on the page."""
    out, last, pos, used = [], "Table", 0, {}

    def label(kind: str) -> str:
        name = f"{last} ({kind})"
        used[name] = used.get(name, 0) + 1
        return html.escape(name if used[name] == 1 else f"{last} ({kind} {used[name]})")

    for m in re.finditer(r"<h[2-4][^>]*>(.*?)</h[2-4]>|<table\b.*?</table>|<pre\b([^>]*)>", body, flags=re.S):
        if m.group(0).startswith("<h"):
            last = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() or last
            continue
        out.append(body[pos:m.start()])
        if m.group(0).startswith("<pre"):
            attrs = m.group(2) or ""
            out.append(m.group(0) if "tabindex" in attrs else
                       f'<pre{attrs} tabindex="0" role="region" aria-label="{label("code")}">')
        else:
            out.append(f'<div class="tablewrap" role="region" tabindex="0" aria-label="{label("table")}">{m.group(0)}</div>')
        pos = m.end()
    out.append(body[pos:])
    body = re.sub(r"</?markdown-accessiblity-table>", "", "".join(out))
    # GitHub links each README image (status badges) to its camo proxy copy; the link only reopens the image
    return re.sub(r'<a [^>]*href="https://camo\.githubusercontent\.com/[^"]*"[^>]*>(<img [^>]*>)</a>', r"\1", body)


def outline(body: str) -> list[tuple[int, str, str]]:
    """The h2 and h3 headings of a document that carry an id, in order: (level, id, text)."""
    out = []
    for m in re.finditer(r"<h([23])\b[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</h\1>", body, flags=re.S):
        text = html.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
        if text:
            out.append((int(m.group(1)), m.group(2), text))
    return out


def onpage_nav(items: list[tuple[int, str, str]]) -> str:
    """The "On this page" sidebar: h2 entries with their h3s nested. Empty when a page has one heading or none."""
    if len(items) < 2:
        return ""
    parts, depth = [], 0
    for level, hid, text in items:
        if level == 3 and depth == 0:
            if not parts:
                continue  # an h3 before the first h2 has no parent entry
            parts.append("<ol>"); depth = 1
        elif level == 2 and depth == 1:
            parts.append("</ol></li>"); depth = 0
        elif level == 2 and parts:
            parts.append("</li>")
        link = f'<a href="#{html.escape(hid)}">{html.escape(text)}</a>'
        parts.append(f"<li>{link}" if level == 2 else f"<li>{link}</li>")
    parts.append("</ol></li>" if depth else "</li>")
    return (f'<details class="menu"><summary>On this page</summary><nav class="onpage" aria-label="On this page">'
            f'<p class="side-title" aria-hidden="true">On this page</p><ol>{"".join(parts)}</ol></nav></details>')


# The section pages of the product documentation, in sidebar order: (path under BASE, title, template).
PAGES = [
    ("", "Overview", "overview.html"),
    ("get-started/", "Get started", "get-started.html"),
    ("modules/", "Verified modules", None),
    ("versioning/", "Versioning and releases", "versioning.html"),
    ("support/", "Support and policies", "support.html"),
    ("faq/", "FAQ", "faq.html"),
]
# Fragments other pages and the README of the module repository link to on the product page; the overview
# keeps an element with each id so those links still land somewhere relevant. --verify checks them.
LEGACY_ANCHORS = ["top", "overview", "why", "modules", "verified-list", "start", "trust", "versions", "support", "faq"]


def sidenav(current: str, mods: list[str]) -> str:
    """The left sidebar: the section pages, then every verified module grouped by Graph area. `current` is
    the path under BASE of the page being built ("" for the overview, "modules/<mod>/" for a module page)."""
    def link(path: str, label: str) -> str:
        cur = ' aria-current="page"' if path == current else ""
        return f'<li><a href="{BASE}/{path}"{cur}>{label}</a></li>'

    parts = [f'<nav class="sidenav" aria-label="Documentation"><ul class="pages">']
    parts += [link(p, html.escape(t)) for p, t, _ in PAGES]
    parts.append("</ul>")
    by: dict[str, list[str]] = {}
    for m in mods:
        by.setdefault(group_of(m), []).append(m)
    for g in [g for g, _ in GROUPS] + ["Other"]:
        if g in by:
            parts.append(f'<p class="nav-group">{html.escape(g)}</p><ul class="mods">')
            parts += [link(f"modules/{m}/", f"<code>{html.escape(short(m))}</code>") for m in by[g]]
            parts.append("</ul>")
    parts.append("</nav>")
    return "".join(parts)


def layout(title: str, desc: str, current: str, body: str, mods: list[str], rel: dict, cls: str = "") -> str:
    """A documentation page: sticky header, left navigation, the document, "On this page", footer. On narrow
    screens the sidebars are <details> menus above the document (see static/style.css)."""
    right = onpage_nav(outline(body))
    return (head(title, desc, SITE_URL + current) + "\n" + HEADER + f"""
<div class="wrap docs">
  <aside class="side left" aria-label="Documentation menu">
    <details class="menu"><summary>Documentation</summary>{sidenav(current, mods)}</details>
  </aside>
  {f'<aside class="side right" aria-label="Page outline">{right}</aside>' if right else ''}
  <main id="main" class="doc{(' ' + cls) if cls else ''}">
{body}
  </main>
</div>
""" + footer(rel))


def meta_desc(text: str, fallback: str, limit: int = 160) -> str:
    """A search-result description: plain text, 50-170 characters, cut at a word boundary."""
    t = re.sub(r"\s+", " ", text.replace("`", "").replace("…", "")).strip()
    if len(t) > limit:
        t = t[:limit - 1].rsplit(" ", 1)[0].rstrip(",;:.(") + "…"
    return t if len(t) >= 50 else fallback


def md_inline(text: str) -> str:
    """Escape, then render `code` spans only (for card summaries)."""
    out = html.escape(text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", out)


def render(md: str) -> str:
    # "markdown" renders like a README on github.com; "gfm" (comment mode) turns every source newline into <br>
    return gh("markdown", data={"text": md, "mode": "markdown", "context": REPO})


SAFE_TAGS = re.compile(r"<\s*/?\s*(script|iframe|object|embed|form|input|style|link|meta|base)\b[^>]*>", re.I)


def sanitize(fragment: str) -> str:
    fragment = SAFE_TAGS.sub("", fragment)
    fragment = re.sub(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", fragment, flags=re.I)
    return re.sub(r"(href|src)\s*=\s*\"\s*javascript:[^\"]*\"", r'\1="#"', fragment, flags=re.I)


def head(title: str, desc: str, url: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; base-uri 'none'; form-action 'none'">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{url}">
<link rel="canonical" href="{url}">
<link rel="stylesheet" href="/style.css">
<link rel="icon" type="image/svg+xml" href="/logo.svg">
</head>
<body>"""


HEADER = f"""<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <div class="wrap">
    <span class="brand">
      <a class="org" href="/" aria-label="satolap home"><img src="/logo.svg" width="30" height="26" alt="">satolap</a>
      <span class="sep" aria-hidden="true">/</span>
      <a href="{BASE}/">terraform-msgraph-modules</a>
    </span>
    <nav class="links" aria-label="Project links">
      <a href="https://registry.terraform.io/modules/satolap/modules/msgraph">Terraform Registry</a>
      <a href="https://github.com/{REPO}/releases">Releases</a>
      <a href="https://github.com/{REPO}">GitHub</a>
    </nav>
  </div>
</header>"""


def footer(rel: dict) -> str:
    return f"""<footer>
  <div class="wrap">
    <span>Built from release <a href="{rel['url']}">{rel['tag']}</a> ({rel['published'][:10]}). MIT licensed; Microsoft Graph metadata is used under its MIT licence (<a href="https://github.com/{REPO}/blob/{rel['tag']}/NOTICE">NOTICE</a>).</span>
    <nav aria-label="Project policies"><a href="https://github.com/{REPO}/blob/{rel['tag']}/SECURITY.md">Security policy</a> · <a href="https://github.com/{REPO}/blob/{rel['tag']}/ACCESSIBILITY.md">Accessibility statement</a> · <a href="https://github.com/{REPO}/blob/{rel['tag']}/CONTRIBUTING.md">Contributing</a> · <a href="https://github.com/{REPO}/blob/{rel['tag']}/CODE_OF_CONDUCT.md">Code of conduct</a></nav>
    <span>An independent open-source project, not affiliated with or endorsed by Microsoft or HashiCorp.</span>
  </div>
</footer>
</body>
</html>
"""


def catalog_groups(mods: list[str], info: dict) -> str:
    """The catalog: one section per Graph area with a card per module."""
    by = {}
    for m in mods:
        by.setdefault(group_of(m), []).append(m)
    parts = ['<div class="catalog">']
    for g in [g for g, _ in GROUPS] + ["Other"]:
        if g not in by:
            continue
        parts.append(f'<section class="cat"><h2 id="{slug(g)}">{html.escape(g)}</h2><div class="cards">')
        for m in by[g]:
            s, a = info[m]
            badge = f'<span class="badge{" live" if "live-accepted" in a else ""}">{html.escape(a)}</span>' if a else ""
            parts.append(f'<article class="card mod"><h3><a href="{page_url(m)}"><code>{html.escape(short(m))}</code></a></h3>'
                         f'<p class="path">verified/{html.escape(m)}</p>{badge}<p>{md_inline(card_text(s))}</p></article>')
        parts.append("</div></section>")
    parts.append("</div>")
    return "\n".join(parts)


def area_counts(mods: list[str]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for m in mods:
        counts[group_of(m)] = counts.get(group_of(m), 0) + 1
    return [(g, counts[g]) for g in [g for g, _ in GROUPS] + ["Other"] if g in counts]


def area_index(mods: list[str], prefix: str = "", title: str = "Graph areas") -> str:
    """Jump links to each Graph area on the catalog, with module counts. `prefix` points the links at the
    catalog page from elsewhere."""
    items = "".join(f'<li><a href="{prefix}#{slug(g)}">{html.escape(g)}</a> <span class="n">{n} module{"s" if n != 1 else ""}</span></li>'
                    for g, n in area_counts(mods))
    hid = "areas-title" if not prefix else "areas-title-" + slug(title)
    return f'<nav class="toc areas" aria-labelledby="{hid}"><p class="toc-title" id="{hid}">{html.escape(title)}</p><ul>{items}</ul></nav>'


def module_facts(m: str, assurance: str, reqs: dict[str, str], rel: dict) -> str:
    """The facts an evaluator checks first, as a description list above the README."""
    rows = [("Graph area", f'<a href="{BASE}/modules/#{slug(group_of(m))}">{html.escape(group_of(m))}</a>'),
            ("Assurance", html.escape(assurance) if assurance else "see the README")]
    if reqs:
        rows.append(("Requires", " · ".join(f"{html.escape(n)} <code>{html.escape(v)}</code>" for n, v in reqs.items())))
    rows.append(("Release", f'<a href="{rel["url"]}">{html.escape(rel["tag"])}</a>, {html.escape(rel["published"][:10])}'))
    rows.append(("Licence", f'MIT (<a href="https://github.com/{REPO}/blob/{rel["tag"]}/LICENSE">LICENSE</a>)'))
    return ('<dl class="facts-grid" aria-label="Module facts">'
            + "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in rows) + "</dl>")


def module_nav(m: str, mods: list[str]) -> str:
    """Previous and next module in catalog order, and the other modules of the same Graph area."""
    i = mods.index(m)
    prev_m = mods[i - 1] if i > 0 else None
    next_m = mods[i + 1] if i + 1 < len(mods) else None
    g = group_of(m)
    siblings = [x for x in mods if group_of(x) == g and x != m]

    def link(x: str, rel: str) -> str:
        return (f'<a href="{page_url(x)}" rel="{rel}"><span class="dir">{"Previous" if rel == "prev" else "Next"}</span>'
                f'<code>{html.escape(short(x))}</code></a>')

    sib = ""
    if siblings:
        items = "".join(f'<li><a href="{page_url(x)}"><code>{html.escape(short(x))}</code></a></li>' for x in siblings)
        sib = (f'<nav class="siblings" aria-labelledby="siblings-title"><p class="toc-title" id="siblings-title">'
               f'Also in {html.escape(g)}</p><ul>{items}</ul></nav>')
    pager = (f'<nav class="pager" aria-label="Neighbouring modules">'
             f'{link(prev_m, "prev") if prev_m else "<span></span>"}'
             f'<a class="all" href="{BASE}/modules/">All {len(mods)} verified modules</a>'
             f'{link(next_m, "next") if next_m else "<span></span>"}</nav>')
    return sib + pager


HUB_HEADER = """<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <div class="wrap">
    <span class="brand"><a class="org" href="/" aria-label="satolap home"><img src="/logo.svg" width="30" height="26" alt="">satolap</a></span>
    <nav class="links" aria-label="Sections">
      <a href="/#products">Products</a>
      <a href="https://github.com/satolap">GitHub</a>
    </nav>
  </div>
</header>"""


def hub_footer() -> str:
    return """<footer>
  <div class="wrap">
    <span>satolap · <a href="https://github.com/satolap">github.com/satolap</a></span>
    <span>Product names of Microsoft, HashiCorp and others belong to their owners; satolap projects are independent and not endorsed by them.</span>
  </div>
</footer>
</body>
</html>
"""


def hub(rel: dict, mods: list[str], floors: dict[str, str], reqs: dict[str, dict[str, str]]) -> str:
    """The satolap home page: one card per product in tools/products.json."""
    data = json.load(open(os.path.join(ROOT, "tools", "products.json"), encoding="utf-8"))
    cards = []
    for p in data["products"]:
        href = p.get("path") or p.get("url")
        facts = areas = status = ""
        if p.get("release_facts"):
            c = rel["counts"]
            facts = ('<ul class="facts" aria-label="Release facts">'
                     f'<li><b>{html.escape(rel["tag"])}</b> latest release, {html.escape(rel["published"][:10])}</li>'
                     f'<li><b>{c["v1.0"] or "–"}</b> v1.0 modules</li>'
                     f'<li><b>{c["beta"] or "–"}</b> beta modules</li>'
                     f'<li><b>{c["verified"] or "–"}</b> verified modules</li></ul>')
            areas = ('<p class="areas-line"><span class="label">Verified coverage</span> '
                     + ", ".join(f'<a href="{BASE}/modules/#{slug(g)}">{html.escape(g)}</a> ({n})' for g, n in area_counts(mods))
                     + ".</p>")
            status = ('<p class="areas-line"><span class="label">Status</span> '
                      f'Pre-1.0 (0.x line): breaking changes arrive in minor releases with migration notes; pin a patch-only constraint. '
                      f'Security fixes go to the latest release. MIT licence. Terraform {html.escape(floors.get("terraform", "1.11.0"))} or later; '
                      f'{provider_line(reqs, rel["provider_tested"])}.</p>')
        links = " ".join(f'<a class="btn" href="{html.escape(l["url"])}">{html.escape(l["label"])}</a>' for l in p.get("links", []))
        cards.append(f"""<article class="product">
      <img class="plogo" src="{html.escape(p.get('logo', '/logo.svg'))}" width="88" height="77" alt="">
      <div class="pbody">
        <h3><a href="{html.escape(href)}">{html.escape(p['name'])}</a></h3>
        <p class="ptag">{html.escape(p['tagline'])}</p>
        <p>{html.escape(p['description'])}</p>
        {facts}
        {areas}
        {status}
        <div class="cta"><a class="btn primary" href="{html.escape(href)}">Documentation</a> <a class="btn" href="{html.escape(href)}get-started/">Get started</a> {links}</div>
      </div>
    </article>""")
    return (head("satolap: open-source infrastructure as code", "Open-source projects by satolap, including terraform-msgraph-modules: Terraform modules for Microsoft Graph.",
                 "https://satolap.github.io/") + "\n" + HUB_HEADER + f"""
<main id="main" class="wrap hub">
  <div class="hub-hero">
    <img class="hero-logo" src="/logo.svg" width="128" height="112" alt="">
    <div>
      <p class="eyebrow">satolap</p>
      <h1>Open-source infrastructure-as-code projects.</h1>
      <p class="lede">Each product here is published openly on GitHub, with versioned releases, checksummed release assets and the documentation to adopt it.</p>
    </div>
  </div>
  <section id="products">
    <h2>Products</h2>
    {''.join(cards)}
  </section>
</main>
""" + hub_footer())


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


GUARD = re.compile(r"benhaspalace/GraphForm|graphform-host|SchoggiLab|lindt|[A-Za-z0-9][A-Za-z0-9-]{2,}\.onmicrosoft\.com"
                   r"|<script\b|googletagmanager|google-analytics", re.I)


def verify() -> int:
    """Every root-relative link resolves inside _site, every same-page fragment link finds its id, the overview
    keeps the ids other pages link to, and no page names private sources or loads scripts."""
    import glob
    bad, n = [], 0
    for f in glob.glob(os.path.join(SITE, "**", "*.html"), recursive=True):
        text = open(f, encoding="utf-8").read()
        rel = os.path.relpath(f, SITE)
        for m in GUARD.finditer(text):
            bad.append(f"{rel}: forbidden content {m.group(0)!r}")
        ids = set(re.findall(r'\sid="([^"]+)"', text))
        for h in re.findall(r'href="#([^"]+)"', text):
            n += 1
            if html.unescape(h) not in ids:
                bad.append(f"{rel}: fragment link #{h} has no target")
        for h in re.findall(r'(?:href|src)="(/[^"#?]*)', text):
            n += 1
            p = h.lstrip("/")
            p = p + "index.html" if (p == "" or p.endswith("/")) else p
            if not os.path.exists(os.path.join(SITE, p)):
                bad.append(f"{rel}: broken link {h}")
        if rel == os.path.join(BASE.strip("/"), "index.html"):
            for a in LEGACY_ANCHORS:
                if a not in ids:
                    bad.append(f"{rel}: legacy anchor #{a} is gone (other pages link to it)")
    print(f"verified {n} internal links; {len(bad)} problems")
    for b in bad[:40]:
        print("  " + b)
    return 1 if bad else 0


def _lum(hexc: str) -> float:
    h = hexc.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    def ch(v: int) -> float:
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def audit() -> int:
    """Design and accessibility facts for the designer roles (advisory; exit 0). Run after a build."""
    import glob
    from html.parser import HTMLParser
    css = open(os.path.join(STATIC, "style.css"), encoding="utf-8").read()
    blocks = re.findall(r":root\s*\{([^}]*)\}", css)
    themes = {}
    for name, blk in zip(("light", "dark"), blocks[:2]):
        themes[name] = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,6})", blk))
    pairs = [("ink", "bg", 4.5), ("ink", "surface", 4.5), ("muted", "bg", 4.5), ("muted", "surface", 4.5),
             ("accent", "bg", 4.5), ("accent", "surface", 4.5), ("accent-ink", "accent", 4.5), ("code-ink", "code-bg", 4.5),
             ("ink", "accent-soft", 4.5), ("accent", "accent-soft", 4.5), ("muted", "accent-soft", 4.5),
             ("code-comment", "code-bg", 4.5), ("code-keyword", "code-bg", 4.5), ("code-string", "code-bg", 4.5),
             ("code-entity", "code-bg", 4.5), ("code-constant", "code-bg", 4.5), ("code-tag", "code-bg", 4.5),
             ("ok", "surface", 4.5), ("warn", "surface", 4.5), ("ok", "bg", 4.5), ("warn", "bg", 4.5),
             ("muted", "code-bg", 4.5), ("accent", "code-bg", 4.5),
             ("line", "surface", 1.3), ("line", "bg", 1.3), ("line", "code-bg", 1.3), ("line-strong", "bg", 1.3)]
    print("## Colour contrast (WCAG 2.2: 4.5:1 for text, 3:1 for large text and UI)")
    problems = []
    for t, tok in themes.items():
        for fg, bg, need in pairs:
            if fg in tok and bg in tok:
                c = contrast(tok[fg], tok[bg])
                flag = "" if c >= need else "  <-- below " + str(need)
                print(f"  {t:5} {fg:>10} on {bg:<8} {tok[fg]} / {tok[bg]}  {c:5.2f}:1{flag}")
                if flag:
                    problems.append(f"contrast {t} {fg}/{bg} {c:.2f}:1 < {need}")

    class P(HTMLParser):
        def __init__(self):
            super().__init__(); self.h = []; self.img_noalt = 0; self.links = []; self._a = None
            self.main = False; self.lang = False; self.title = ""; self._t = False; self.desc = ""
            self.viewport = False; self.skip = False; self.navs_unnamed = 0; self.ids = []; self.in_md = 0
            self.h_text = []; self._h = None; self.regions_unnamed = 0; self.landmarks = set()
            self.navs = []; self.current = 0; self.asides_unnamed = 0; self.details_open = 0; self.details_nosummary = 0
            self.h2_in_main = 0; self.in_main = False; self.onpage_links = 0
            self.in_onpage = False
        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "details": self.details_open += 1; self._summary = False
            if tag == "summary": self._summary = True
            if tag == "aside": self.landmarks.add("aside")
            if tag == "aside" and not (a.get("aria-label") or a.get("aria-labelledby")): self.asides_unnamed += 1
            if tag == "nav": self.navs.append(a.get("aria-label") or "")
            if tag == "nav" and a.get("aria-label") == "On this page": self.in_onpage = True
            if tag == "a" and self.in_onpage: self.onpage_links += 1
            if tag == "a" and a.get("aria-current") == "page": self.current += 1
            if tag == "main": self.in_main = True
            if tag == "h2" and self.in_main: self.h2_in_main += 1
            if re.fullmatch(r"h[1-6]", tag): self.h.append(int(tag[1])); self._h = []
            if tag == "img" and "alt" not in a: self.img_noalt += 1
            if tag == "a": self._a = [a.get("aria-label") or ""]; self._href = a.get("href")
            if tag == "main": self.main = True
            if tag in ("header", "footer", "main"): self.landmarks.add(tag)
            if tag == "html" and a.get("lang"): self.lang = True
            if tag == "title": self._t = True
            if tag == "meta" and a.get("name") == "description": self.desc = a.get("content") or ""
            if tag == "meta" and a.get("name") == "viewport": self.viewport = True
            if tag == "img" and self._a is not None: self._a.append(a.get("alt") or "img")
            if tag == "nav" and not (a.get("aria-label") or a.get("aria-labelledby")): self.navs_unnamed += 1
            if a.get("role") == "region" and not (a.get("aria-label") or a.get("aria-labelledby")): self.regions_unnamed += 1
            if a.get("id"): self.ids.append(a["id"])
            if tag == "article" and "md" in (a.get("class") or "").split(): self.in_md += 1
            if tag == "a" and a.get("class") == "skip" and a.get("href") == "#main": self.skip = True
        def handle_endtag(self, tag):
            if tag == "details":
                self.details_open -= 1
                if not self._summary: self.details_nosummary += 1
            if tag == "nav" and self.in_onpage: self.in_onpage = False
            if tag == "main": self.in_main = False
            if tag == "a" and self._a is not None:
                self.links.append(("".join(self._a).strip(), self._href, bool(self.in_md))); self._a = None
            if tag == "title": self._t = False
            if re.fullmatch(r"h[1-6]", tag) and self._h is not None: self.h_text.append("".join(self._h).strip()); self._h = None
            if tag == "article" and self.in_md: self.in_md -= 1
        def handle_data(self, d):
            if self._a is not None: self._a.append(d)
            if self._h is not None: self._h.append(d)
            if self._t: self.title += d
    pages = sorted(glob.glob(os.path.join(SITE, "**", "*.html"), recursive=True))
    total, titles, biggest = 0, {}, ("", 0)
    print("\n## Pages")
    for f in pages:
        text = open(f, encoding="utf-8").read(); total += len(text.encode())
        p = P(); p.feed(text)
        rel = os.path.relpath(f, SITE)
        if len(text) > biggest[1]: biggest = (rel, len(text))
        skips = sum(1 for a, b in zip(p.h, p.h[1:]) if b > a + 1)
        issues = []
        if p.h.count(1) != 1: issues.append(f"{p.h.count(1)} h1")
        if p.h and p.h[0] != 1: issues.append("first heading is not h1")
        if skips: issues.append(f"{skips} heading-level skips")
        if any(not t for t in p.h_text): issues.append("empty heading")
        if p.img_noalt: issues.append(f"{p.img_noalt} img without alt")
        empty = sum(1 for t, _, _ in p.links if not t)
        if empty: issues.append(f"{empty} links without text")
        generic = sum(1 for t, _, _ in p.links if t.lower().rstrip(".") in ("here", "click here", "link", "more", "read more", "this"))
        if generic: issues.append(f"{generic} links with generic text")
        # Same link text to different targets on one page (WCAG 2.4.4); README prose is the source's own
        seen: dict[str, set] = {}
        d = os.path.dirname(rel).replace(os.sep, "/")
        here = "/" + (d + "/" if d else "")
        for t, href, md in p.links:
            if t and not md: seen.setdefault(t, set()).add(here + href if (href or "").startswith("#") else href)
        ambiguous = [t for t, hs in seen.items() if len(hs) > 1]
        if ambiguous: issues.append(f"ambiguous link text {ambiguous[:3]}")
        dup_ids = sorted({i for i in p.ids if p.ids.count(i) > 1})
        if dup_ids: issues.append(f"duplicate ids {dup_ids[:3]}")
        if p.navs_unnamed: issues.append(f"{p.navs_unnamed} nav without a name")
        if p.regions_unnamed: issues.append(f"{p.regions_unnamed} region without a name")
        if not p.main: issues.append("no <main>")
        if {"header", "footer"} - p.landmarks: issues.append("missing header or footer landmark")
        if p.asides_unnamed: issues.append(f"{p.asides_unnamed} aside without a name")
        if p.details_nosummary: issues.append(f"{p.details_nosummary} details without a summary")
        # Documentation layout (every page under the product path): a named "Documentation" nav that marks the
        # current page, and an "On this page" nav whenever the document has two or more h2 headings
        if rel.startswith(BASE.strip("/") + os.sep):
            if "Documentation" not in p.navs: issues.append("no Documentation nav")
            elif p.current != 1: issues.append(f"{p.current} links marked aria-current=page (expected 1)")
            if p.h2_in_main >= 2 and "On this page" not in p.navs: issues.append("no On this page nav")
            if "On this page" in p.navs and p.onpage_links < 2: issues.append("On this page nav with fewer than 2 links")
        if not p.skip: issues.append("no skip link")
        if not p.lang: issues.append("no lang")
        if not p.viewport: issues.append("no viewport meta")
        if not (10 <= len(p.title) <= 70): issues.append(f"title length {len(p.title)}")
        if p.title in titles: issues.append(f"title also used by {titles[p.title]}")
        titles.setdefault(p.title, rel)
        if not (50 <= len(p.desc) <= 170): issues.append(f"description length {len(p.desc)}")
        if len(text) > 200_000: issues.append(f"{len(text)//1024} KB")
        if issues:
            problems.extend(f"{rel}: {i}" for i in issues)
    print(f"  {len(pages)} pages, {total // 1024} KB of HTML in total (largest {biggest[0]}: {biggest[1] // 1024} KB); "
          f"style.css {len(css) // 1024} KB; no scripts, fonts or third-party assets")
    print(f"\n## Findings ({len(problems)})")
    from collections import Counter
    kinds = Counter(re.sub(r"^[^:]+: ", "", x) if ": " in x else x for x in problems)
    for k, n in kinds.most_common(30):
        print(f"  {n:3} x {k}")
    for x in problems[:40]:
        print("  - " + x)
    return 0


def main() -> int:
    if "--verify" in sys.argv:
        return verify()
    if "--audit" in sys.argv:
        return audit()
    rel = latest_release()
    if "--check" in sys.argv:  # compare with the DEPLOYED site, so a scheduled run rebuilds only for a new release
        import urllib.request
        try:
            with urllib.request.urlopen(SITE_URL + "release.json", timeout=20) as r:
                cur = json.load(r).get("tag")
        except Exception:
            cur = None
        print(f"deployed {cur}, latest release {rel['tag']}")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"stale={'false' if cur == rel['tag'] else 'true'}\n")
        return 0
    tag = rel["tag"]
    minor = ".".join(tag.lstrip("v").split(".")[:2])
    mods = verified_modules(tag)
    modset = set(mods)
    info, reqs, pages = {}, {}, {}
    shutil.rmtree(SITE, ignore_errors=True)
    shutil.copytree(STATIC, SITE)
    for m in mods:
        md = gh(f"repos/{REPO}/contents/verified/{m}/README.md?ref={tag}", "-H", "Accept: application/vnd.github.raw")
        info[m] = summary_and_assurance(md)
        reqs[m] = requirements(md)
        md_body = re.sub(r"\A\s*#\s+[^\n]*\n", "", md, count=1)  # the page has its own title
        body = heading_ids(sanitize(render(rewrite_links(md_body, m, tag, modset))))
        pages[m] = wrap_tables(body)
        print(f"  {m}")
    floors = floor_versions(reqs)
    for m in mods:
        body = pages[m]
        src = f"satolap/modules/msgraph//verified/{m}"
        title = f"verified/{m}"
        desc = meta_desc(info[m][0], f"Verified Terraform module verified/{m} for Microsoft Graph: inputs, permissions and usage.")
        crumbs = (f'<a href="{BASE}/modules/">Verified modules</a> / '
                  f'<a href="{BASE}/modules/#{slug(group_of(m))}">{html.escape(group_of(m))}</a>')
        badge = f'<span class="badge{" live" if "live-accepted" in info[m][1] else ""}">{html.escape(info[m][1])}</span>' if info[m][1] else ""
        doc = f"""<nav class="crumbs" aria-label="Breadcrumb">{crumbs}</nav>
  <h1><code>{html.escape(title)}</code></h1>
  {badge}
  {f'<p class="sub">{md_inline(info[m][0])}</p>' if info[m][0] else ""}
  <div class="srcbox">
    <pre tabindex="0" role="region" aria-label="Module block to copy">module "{html.escape(m.rsplit('/', 1)[-1].replace('-', '_'))}" {{
  source  = "{html.escape(src)}"
  version = "~&gt; {minor}.0"
}}</pre>
    <p class="links"><a href="https://github.com/{REPO}/tree/{tag}/verified/{m}">Source at {tag}</a> · <a href="https://registry.terraform.io/modules/satolap/modules/msgraph">Terraform Registry</a> · <a href="https://github.com/{REPO}/releases/tag/{tag}">Release notes</a> · <a href="https://github.com/{REPO}/issues/new/choose">Report a problem</a></p>
  </div>
  {module_facts(m, info[m][1], reqs[m], rel)}
  <article class="md">
{body}
  </article>
  {module_nav(m, mods)}"""
        write(os.path.join(OUT, "modules", m, "index.html"),
              layout(f"{short(m)}: verified module", desc, f"modules/{m}/", doc, mods, rel, "modpage"))
    catalog = f"""<h1>Verified modules</h1>
  <p class="lede">{len(mods)} reviewed modules in <a href="{rel['url']}">{tag}</a> ({rel['published'][:10]}) across {len(area_counts(mods))} Microsoft Graph areas.</p>
  <p class="sub">Each page shows the module's README from the release: inputs, permissions, licence requirements, lifecycle notes and its assurance level, plus the module block to copy. Every module needs Terraform {html.escape(floors.get('terraform', '1.11.0'))} or later, and {provider_line(reqs, rel['provider_tested'])}; each page states its own requirements. New here? Read <a href="{BASE}/get-started/">Get started</a> first.</p>
{catalog_groups(mods, info)}"""
    write(os.path.join(OUT, "modules", "index.html"),
          layout("Verified modules: terraform-msgraph-modules", f"The {len(mods)} reviewed, verified Terraform modules for Microsoft Graph in {tag}, grouped by Graph area.",
                 "modules/", catalog, mods, rel, "modpage"))
    c = rel["counts"]
    repl = {
        "{{TAG}}": tag, "{{MINOR}}": minor, "{{PUBLISHED}}": rel["published"][:10],
        "{{V1_COUNT}}": str(c["v1.0"] or "–"), "{{BETA_COUNT}}": str(c["beta"] or "–"),
        "{{VERIFIED_COUNT}}": str(c["verified"] or len(mods)),
        "{{AREA_COUNT}}": str(len(area_counts(mods))),
        "{{AREA_INDEX}}": area_index(mods, f"{BASE}/modules/", "Verified coverage by Graph area"),
        "{{TF_MIN}}": floors.get("terraform", "1.11.0"), "{{PROVIDER_LINE}}": provider_line(reqs, rel["provider_tested"]),
        "{{PROVIDER_TESTED}}": rel["provider_tested"] or "the version in release-manifest.json",
        "{{ASSETS}}": ", ".join(f"<code>{html.escape(a)}</code>" for a in rel["assets"]) or "the release archives",
    }
    descs = {
        "": "Versioned, tested Terraform modules for Microsoft Graph v1.0 and beta on the microsoft/msgraph provider, plus verified modules for Entra ID governance.",
        "get-started/": f"Configure the microsoft/msgraph provider, reference a terraform-msgraph-modules module pinned to {tag}, initialise and plan, with a complete example.",
        "versioning/": "How terraform-msgraph-modules versions releases on the 0.x line and from 1.0.0, what to pin, beta module status and the release integrity checks.",
        "support/": "Where to report problems and request modules for terraform-msgraph-modules, vulnerability reporting, contributing, licensing and accessibility.",
        "faq/": "Answers on the provider, Terraform versions, beta modules in production, the first terraform init, Git sources, permissions and assurance levels.",
    }
    for path, title, template in PAGES:
        if not template:
            continue
        body = open(os.path.join(TEMPLATES, template), encoding="utf-8").read()
        for k, v in repl.items():
            body = body.replace(k, v)
        left = re.findall(r"\{\{[A-Z_]+\}\}", body)
        if left:
            raise SystemExit(f"{template}: unfilled placeholders {left}")
        full = "terraform-msgraph-modules: Terraform modules for Microsoft Graph" if not path else f"{title}: terraform-msgraph-modules"
        write(os.path.join(OUT, path, "index.html"), layout(full, descs[path], path, body, mods, rel))
    write(os.path.join(SITE, "index.html"), hub(rel, mods, floors, reqs))
    write(os.path.join(SITE, "404.html"), (head("Page not found: satolap", "This page does not exist. Find a verified module, the quick start or the satolap home page instead.", "https://satolap.github.io/404.html")
          + "\n" + HUB_HEADER + f"""
<main id="main" class="wrap hub">
  <h1>Page not found</h1>
  <p class="sub">The page may have moved when a module was renamed in a new release. Try one of these:</p>
  <ul>
    <li><a href="{BASE}/modules/">Verified modules</a>: all {len(mods)} modules in {tag}, grouped by Graph area</li>
    <li><a href="{BASE}/get-started/">Get started</a> with terraform-msgraph-modules</li>
    <li><a href="/">satolap home page</a></li>
  </ul>
</main>
""" + hub_footer()))
    write(STAMP, json.dumps({"tag": tag, "published": rel["published"], "verified_modules": len(mods),
                             "counts": c}, indent=1) + "\n")
    print(f"built {SITE_URL} for {tag}: {len(mods)} verified module pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
