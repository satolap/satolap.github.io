# Blog sources

Add a Markdown file named `YYYY-MM-DD-slug.md` here. The builder creates
`/blog/slug/`, the blog index and an Atom feed when at least one post is published.
The home page then includes a Blog link. Slugs must be unique across dates.

Start each post with this plain-text front matter (values are unquoted):

```markdown
---
title: A short descriptive title
summary: A plain-text summary of the article for the index and search results.
draft: true
---

## First section

Article text, using public facts and links to public sources only.
```

Remove `draft: true` only when the post is ready to publish. The filename date is
the publication date; future dates do not schedule publication. The page supplies
its own h1 from the title; use h2 and h3 for sections. Use absolute site paths
for internal links, such as `/terraform-msgraph-modules/modules/`.

Run `python3 tools/build.py --review` for release and deployment status, a full
build, link verification and the accessibility audit. Read the audit findings:
the audit is advisory and does not fail the command when it reports findings.
Never edit `_site/`; it is generated. Do not include scripts, trackers,
third-party assets or private information.
