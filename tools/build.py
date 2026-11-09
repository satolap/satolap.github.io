#!/usr/bin/env python3
"""Build https://satolap.github.io/terraform-msgraph-modules/ from the latest public release.

Facts come only from the public repository satolap/terraform-msgraph-modules at its latest release tag:
the release notes (module counts), the tag's tree (which verified modules exist) and each verified module's
README.md, rendered with GitHub's own Markdown API (the same sanitised HTML github.com shows).

    python3 tools/build.py            # rebuild everything for the latest release
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
    return {"tag": rel["tag_name"], "published": rel.get("published_at", ""), "url": rel["html_url"], "counts": counts}


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
    assurance = assurance.replace("`", "")
    if len(summ) > 230:  # cards stay scannable; the module page has the full text
        cut = summ[:230].rsplit(" ", 1)[0].rstrip(",;:")
        if cut.count("`") % 2:
            cut = cut.rsplit("`", 1)[0].rstrip()
        summ = cut + "…"
    return summ, assurance


def md_inline(text: str) -> str:
    """Escape, then render `code` spans only (for card summaries)."""
    out = html.escape(text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", out)


def render(md: str) -> str:
    return gh("markdown", data={"text": md, "mode": "gfm", "context": REPO})


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
    <nav class="links" aria-label="Sections">
      <a href="{BASE}/modules/">Verified modules</a>
      <a href="{BASE}/#start">Quick start</a>
      <a href="{BASE}/#trust">Release integrity</a>
      <a href="{BASE}/#versions">Versioning</a>
      <a href="{BASE}/#faq">FAQ</a>
      <a href="https://github.com/{REPO}">GitHub</a>
    </nav>
  </div>
</header>"""


def footer(rel: dict) -> str:
    return f"""<footer>
  <div class="wrap">
    <span>Built from release <a href="{rel['url']}">{rel['tag']}</a>. MIT licensed; Microsoft Graph metadata is used under its MIT licence (<a href="https://github.com/{REPO}/blob/main/NOTICE">NOTICE</a>).</span>
    <span>An independent open-source project, not affiliated with or endorsed by Microsoft or HashiCorp.</span>
  </div>
</footer>
</body>
</html>
"""


def group_lists(mods: list[str], info: dict, tag: str, with_summary: bool) -> str:
    by = {}
    for m in mods:
        by.setdefault(group_of(m), []).append(m)
    order = [g for g, _ in GROUPS] + ["Other"]
    parts = ['<div class="mods">' if not with_summary else '<div class="catalog">']
    for g in order:
        if g not in by:
            continue
        if with_summary:
            parts.append(f'<section class="cat"><h2 id="{re.sub(r"[^a-z0-9]+", "-", g.lower())}">{html.escape(g)}</h2><div class="cards">')
            for m in by[g]:
                s, a = info[m]
                badge = f'<span class="badge{" live" if "live-accepted" in a else ""}">{html.escape(a)}</span>' if a else ""
                parts.append(f'<a class="card mod" href="{page_url(m)}"><h3><code>{html.escape(short(m))}</code></h3>'
                             f'<p class="path">verified/{html.escape(m)}</p>{badge}<p>{md_inline(s)}</p></a>')
            parts.append("</div></section>")
        else:
            parts.append(f'      <div class="group"><h3>{html.escape(g)}</h3><ul>')
            for m in by[g]:
                parts.append(f'        <li><a href="{page_url(m)}"><code>{html.escape(short(m))}</code></a></li>')
            parts.append("      </ul></div>")
    parts.append("</div>")
    return "\n".join(parts)


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


def hub(rel: dict) -> str:
    """The satolap home page: one card per product in tools/products.json."""
    data = json.load(open(os.path.join(ROOT, "tools", "products.json"), encoding="utf-8"))
    cards = []
    for p in data["products"]:
        href = p.get("path") or p.get("url")
        facts = ""
        if p.get("release_facts"):
            c = rel["counts"]
            facts = ('<ul class="facts">'
                     f'<li><b>{html.escape(rel["tag"])}</b> latest release</li>'
                     f'<li><b>{c["v1.0"] or "–"}</b> v1.0 modules</li>'
                     f'<li><b>{c["beta"] or "–"}</b> beta modules</li>'
                     f'<li><b>{c["verified"] or "–"}</b> verified modules</li></ul>')
        links = " ".join(f'<a class="btn" href="{html.escape(l["url"])}">{html.escape(l["label"])}</a>' for l in p.get("links", []))
        cards.append(f"""<article class="product">
      <img class="plogo" src="{html.escape(p.get('logo', '/logo.svg'))}" width="88" height="77" alt="">
      <div class="pbody">
        <h3><a href="{html.escape(href)}">{html.escape(p['name'])}</a></h3>
        <p class="ptag">{html.escape(p['tagline'])}</p>
        <p>{html.escape(p['description'])}</p>
        {facts}
        <div class="cta"><a class="btn primary" href="{html.escape(href)}">Documentation</a> {links}</div>
      </div>
    </article>""")
    return (head("satolap", "Open-source projects by satolap, including terraform-msgraph-modules: Terraform modules for Microsoft Graph.",
                 "https://satolap.github.io/") + "\n" + HUB_HEADER + f"""
<main id="main">
  <div class="wrap hub-hero">
    <img class="hero-logo" src="/logo.svg" width="200" height="175" alt="">
    <div>
      <p class="eyebrow">satolap</p>
      <h1>Open-source infrastructure-as-code projects.</h1>
      <p class="lede">Each product here is published openly on GitHub, with versioned releases and the documentation to adopt it.</p>
    </div>
  </div>
  <section id="products">
    <div class="wrap">
      <h2>Products</h2>
      {''.join(cards)}
    </div>
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
    """Every root-relative link resolves inside _site, and no page names private sources or loads scripts."""
    import glob
    bad, n = [], 0
    for f in glob.glob(os.path.join(SITE, "**", "*.html"), recursive=True):
        text = open(f, encoding="utf-8").read()
        rel = os.path.relpath(f, SITE)
        for m in GUARD.finditer(text):
            bad.append(f"{rel}: forbidden content {m.group(0)!r}")
        for h in re.findall(r'(?:href|src)="(/[^"#?]*)', text):
            n += 1
            p = h.lstrip("/")
            p = p + "index.html" if (p == "" or p.endswith("/")) else p
            if not os.path.exists(os.path.join(SITE, p)):
                bad.append(f"{rel}: broken link {h}")
    print(f"verified {n} internal links; {len(bad)} problems")
    for b in bad[:40]:
        print("  " + b)
    return 1 if bad else 0


def main() -> int:
    if "--verify" in sys.argv:
        return verify()
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
    info = {}
    shutil.rmtree(SITE, ignore_errors=True)
    shutil.copytree(STATIC, SITE)
    for m in mods:
        md = gh(f"repos/{REPO}/contents/verified/{m}/README.md?ref={tag}", "-H", "Accept: application/vnd.github.raw")
        info[m] = summary_and_assurance(md)
        md_body = re.sub(r"\A\s*#\s+[^\n]*\n", "", md, count=1)  # the page has its own title
        body = sanitize(render(rewrite_links(md_body, m, tag, modset)))
        src = f"satolap/modules/msgraph//verified/{m}"
        title = f"verified/{m}"
        desc = info[m][0][:200] or f"Verified Terraform module {m} for Microsoft Graph."
        crumbs = f'<a href="{BASE}/">Home</a> / <a href="{BASE}/modules/">Verified modules</a> / {html.escape(group_of(m))}'
        badge = f'<span class="badge{" live" if "live-accepted" in info[m][1] else ""}">{html.escape(info[m][1])}</span>' if info[m][1] else ""
        page = (head(f"{short(m)}: verified module", desc, f"https://satolap.github.io{page_url(m)}") + "\n" + HEADER + f"""
<main id="main" class="wrap modpage">
  <p class="crumbs">{crumbs}</p>
  <h1><code>{html.escape(title)}</code></h1>
  {badge}
  <div class="srcbox">
    <pre>module "{html.escape(m.rsplit('/', 1)[-1].replace('-', '_'))}" {{
  source  = "{html.escape(src)}"
  version = "~&gt; {minor}.0"
}}</pre>
    <p class="links"><a href="https://github.com/{REPO}/tree/{tag}/verified/{m}">Source at {tag}</a> · <a href="https://registry.terraform.io/modules/satolap/modules/msgraph">Terraform Registry</a> · <a href="https://github.com/{REPO}/releases/tag/{tag}">Release notes</a></p>
  </div>
  <article class="md">
{body}
  </article>
</main>
""" + footer(rel))
        write(os.path.join(OUT, "modules", m, "index.html"), page)
        print(f"  {m}")
    catalog = (head("Verified modules: terraform-msgraph-modules", f"The {len(mods)} reviewed, verified Terraform modules for Microsoft Graph in {tag}.", SITE_URL + "modules/")
               + "\n" + HEADER + f"""
<main id="main" class="wrap modpage">
  <p class="crumbs"><a href="{BASE}/">Home</a> / Verified modules</p>
  <h1>Verified modules</h1>
  <p class="sub">{len(mods)} reviewed modules in <a href="{rel['url']}">{tag}</a> for directory objects, applications, identity governance, role management and Conditional Access. Each page shows the module's README from the release: inputs, permissions, licence requirements, lifecycle notes and its assurance level.</p>
{group_lists(mods, info, tag, True)}
</main>
""" + footer(rel))
    write(os.path.join(OUT, "modules", "index.html"), catalog)
    c = rel["counts"]
    home = open(os.path.join(TEMPLATES, "home.html"), encoding="utf-8").read()
    repl = {
        "{{HEAD}}": head("terraform-msgraph-modules: Terraform modules for Microsoft Graph",
                         "Versioned, tested Terraform modules for Microsoft Graph v1.0 and beta on the official microsoft/msgraph provider, plus verified modules for Entra ID identity governance and Conditional Access.", SITE_URL),
        "{{HEADER}}": HEADER, "{{FOOTER}}": footer(rel), "{{TAG}}": tag, "{{MINOR}}": minor,
        "{{V1_COUNT}}": str(c["v1.0"] or "–"), "{{BETA_COUNT}}": str(c["beta"] or "–"),
        "{{VERIFIED_COUNT}}": str(c["verified"] or len(mods)),
        "{{VERIFIED_GROUPS}}": group_lists(mods, info, tag, False),
    }
    for k, v in repl.items():
        home = home.replace(k, v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", home)
    if left:
        raise SystemExit(f"unfilled placeholders: {left}")
    write(os.path.join(OUT, "index.html"), home)
    write(os.path.join(SITE, "index.html"), hub(rel))
    write(os.path.join(SITE, "404.html"), (head("Page not found: satolap", "Page not found.", "https://satolap.github.io/404.html")
          + "\n" + HUB_HEADER + '\n<main id="main" class="wrap modpage"><h1>Page not found</h1><p class="sub">Go to the '
          '<a href="/">satolap home page</a> or the <a href="' + BASE + '/">terraform-msgraph-modules docs</a>.</p></main>\n' + hub_footer()))
    write(STAMP, json.dumps({"tag": tag, "published": rel["published"], "verified_modules": len(mods),
                             "counts": c}, indent=1) + "\n")
    print(f"built {SITE_URL} for {tag}: {len(mods)} verified module pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
