# satolap.github.io

Source of https://satolap.github.io: the satolap home page, plus a documentation site for each product. Today the only product is [terraform-msgraph-modules](https://satolap.github.io/terraform-msgraph-modules/), Terraform modules for Microsoft Graph. Its docs include one page per verified module.

## How it is built

`tools/build.py` (standard library plus the `gh` CLI) writes the whole site to `_site/`, which is not committed:

| Output | Source |
| --- | --- |
| `/` and `/404.html` | `tools/products.json`, with live release facts for each product that sets `release_facts` |
| `/terraform-msgraph-modules/` | `tools/templates/home.html`, filled with the latest release's tag and module counts (parsed from its release notes) and the verified module list |
| `/terraform-msgraph-modules/modules/` and `/terraform-msgraph-modules/modules/<path>/` | every verified module of the latest release (a folder under `verified/` with `main.tf` and `README.md`, tests excluded). Each page renders that module's `README.md` through GitHub's Markdown API |
| `/style.css`, `/logo.svg`, `/.nojekyll` | `static/` |

Relative links in a README that point to another verified module go to that module's page on this site. Every other relative link goes to GitHub at the release tag.

`.github/workflows/pages.yml` builds and deploys on every push to `main`, on manual dispatch, and every 3 hours. The scheduled run deploys only when the latest public release is newer than the one the live site was built from (`/terraform-msgraph-modules/release.json`). A new release therefore reaches the site within 3 hours, with nobody involved.

## Commands

```bash
python3 tools/build.py            # build _site/ for the latest release
python3 tools/build.py --verify   # internal links resolve; no private names, tenant domains or scripts
python3 tools/build.py --audit    # design and accessibility facts: contrast, headings, alt text, titles, page weight
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
