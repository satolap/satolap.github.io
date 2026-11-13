# satolap.github.io

Source of https://satolap.github.io: the satolap home page, plus a documentation site for each product. Today the only product is [terraform-msgraph-modules](https://satolap.github.io/terraform-msgraph-modules/), Terraform modules for Microsoft Graph. Its docs include one page per verified module.

## How it is built

`tools/build.py` (standard library plus the `gh` CLI) writes the whole site to `_site/`, which is not committed:

| Output | Source |
| --- | --- |
| `/` and `/404.html` | `tools/products.json`, with live release facts for each product that sets `release_facts` |
| `/terraform-msgraph-modules/` (Overview), `/get-started/`, `/versioning/`, `/support/`, `/faq/` | one template each under `tools/templates/` (`PAGES` in `build.py` lists them in sidebar order), filled with the latest release's tag, date, module counts and tested provider version (parsed from its release notes), its asset names, the verified coverage by Graph area, and the minimum Terraform and provider versions across the verified module READMEs |
| `/terraform-msgraph-modules/modules/` and `/terraform-msgraph-modules/modules/<path>/` | every verified module of the latest release (a folder under `verified/` with `main.tf` and `README.md`, tests excluded). Each page renders that module's `README.md` through GitHub's Markdown API, with a facts box (Graph area, assurance, requirements, release, licence), the other modules of its Graph area and previous/next links |
| `/style.css`, `/logo.svg`, `/.nojekyll` | `static/` |

Every page under `/terraform-msgraph-modules/` uses the documentation layout that `layout()` in `build.py` renders: a sticky header, a left sidebar that lists the section pages and every verified module by Graph area (the current page marked with `aria-current`), the document, and a right sidebar "On this page" built from the document's `h2` and `h3` headings at build time. Both sidebars are sticky and scroll on their own; below 1180 px the outline moves above the document and below 900 px both sidebars become `<details>` menus above it, with no script (`::details-content` keeps them open on wide screens; browsers without it get collapsible menus at every width).

Relative links in a README that point to another verified module go to that module's page on this site. Every other relative link goes to GitHub at the release tag. The overview keeps the fragment ids the single-page site used (`#start`, `#versions`, `#support`, `#faq`, …; `LEGACY_ANCHORS` in `build.py`) so links to them still land on a short summary with a link to the page.

`.github/workflows/pages.yml` builds and deploys on every push to `main`, on manual dispatch, and every 3 hours. The scheduled run deploys only when the latest public release is newer than the one the live site was built from (`/terraform-msgraph-modules/release.json`). A new release therefore reaches the site within 3 hours, with nobody involved.

## Commands

```bash
python3 tools/build.py            # build _site/ for the latest release
python3 tools/build.py --verify   # internal links and same-page fragments resolve, the overview keeps its legacy anchors;
                                  # no private names, tenant domains or scripts
python3 tools/build.py --audit    # design and accessibility facts: contrast (text, code and status colours in both themes),
                                  # heading order, alt text, link text, landmarks (named navs and asides, details with
                                  # summaries), the documentation layout (a Documentation nav marking the current page,
                                  # an "On this page" nav wherever a document has two or more h2), skip links, titles,
                                  # descriptions, duplicate ids, page weight
python3 tools/build.py --check    # is the deployed site older than the latest release?
python3 -m http.server -d _site   # preview at http://localhost:8000/terraform-msgraph-modules/
```

## Who maintains it

Three operating roles maintain the site, each in its own clone, and push only after a build and `--verify` pass:

- Developer Relations (devrel): content and release accuracy.
- UX and Accessibility Designer (ux-designer): information architecture, navigation, findability, WCAG 2.2 AA and mobile.
- Brand and Visual Designer (visual-designer): the design system, logo and brand, typography and visual consistency.

All three report to the CIO.

## Rules

- Public facts only: the public repository, its releases and the Terraform Registry. Never mention private repositories, tenants, internal tooling, people or employers. No invented customers, numbers or certifications.
- No scripts, trackers or third-party assets. Each page carries a CSP that allows no scripts. `--verify` enforces this, and the workflow runs it before every deploy.
- Change the content in `tools/templates/`, `tools/products.json` and `static/`, never in `_site/`.
- To add a product, add an entry to `tools/products.json`. If it needs its own docs, add a builder for its sub-site in `tools/build.py`.
- The logo (`static/logo.svg`) is the satolap mark, also used for terraform-msgraph-modules: ten flat triangles in five shades of purple, with a transparent background.
- Actions are pinned to full commit SHAs. Update a pin only to a release that is at least two weeks old.
