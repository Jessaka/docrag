"""Anthropic / Claude Code ingestion from code.claude.com llms index."""

from __future__ import annotations

import re
from typing import List

from src.ingestion.base_scraper import BaseScraper, RawDocument

# Canonical quick-install commands, kept intact and close to a heading so the
# chunker never separates the commands from their context.
QUICK_INSTALL_SNIPPET = """## Quick install

**macOS, Linux, WSL:**

```bash theme={null}
curl -fsSL https://claude.ai/install.sh | bash
```

**Windows PowerShell:**

```powershell theme={null}
irm https://claude.ai/install.ps1 | iex
```

**Homebrew (macOS/Linux):**

```bash theme={null}
brew install --cask claude-code
```

**WinGet (Windows):**

```powershell theme={null}
winget install Anthropic.ClaudeCode
```

"""


class AnthropicScraper(BaseScraper):
    provider = "anthropic"
    tool_name = "claude-code"
    start_urls = ("https://code.claude.com/docs/llms.txt",)

    def scrape(self) -> List[RawDocument]:
        index_url = self.start_urls[0]
        index_text = self.fetch_text(index_url, use_cache=False)
        if not index_text:
            return []

        documents: List[RawDocument] = []
        entries = self.parse_llms_index(index_text, base_url=index_url)
        for entry in entries:
            title = entry["title"]
            url = entry["url"]
            section = entry["section"] or title
            if not url.endswith(".md"):
                continue
            if "/en/" not in url:
                continue
            if not self.is_english_url(url) or self.is_excluded_doc_url(url):
                continue

            markdown_text = self.fetch_text(url, use_cache=False)
            if not markdown_text or markdown_text.lstrip().lower().startswith("<html"):
                continue

            markdown_text = self.strip_mdx_noise(markdown_text)

            normalized_url = url.lower().replace('.md', '')
            install_paths = (
                '/en/setup',
                '/en/quickstart',
                '/en/overview',
                '/en/desktop-quickstart',
                '/en/web-quickstart',
                '/en/troubleshoot-install',
            )
            install_keywords_prefix = (
                "Instalace Claude Code. Nainstalovat Claude Code. Nainstaluji Claude Code. "
                "Instalace a nastaveni Claude Code. "
                "Claude Code setup. Install Claude Code. "
                "Claude Code installation instructions. Claude Code installation guide.\n\n"
            )
            is_install_page = normalized_url.endswith(install_paths)
            if is_install_page:
                markdown_text = install_keywords_prefix + markdown_text

            for section_title, section_text in self.split_markdown_sections(markdown_text):
                document_url = url[:-3]
                if section_title and section_title != "overview":
                    slug = re.sub(r'[^a-z0-9]+', '-', section_title.lower()).strip('-')
                    if slug:
                        document_url = f"{document_url}#{slug}"
                # Every section on an install/setup/quickstart page gets the
                # canonical quick-install commands prepended (with Czech
                # keyword stuffing), so whichever chunk wins retrieval still
                # surfaces the actual curl/brew/winget commands instead of
                # only a link to the setup page.
                if is_install_page and section_title != "overview":
                    section_text = install_keywords_prefix + QUICK_INSTALL_SNIPPET + section_text
                document = self.create_document(
                    url=document_url,
                    title=title,
                    text=section_text,
                    doc_type=self.classify_doc_type(url, title, section_text),
                    section=section_title or section,
                )
                documents.append(document)
        return self.deduplicate_documents(documents)

    def strip_mdx_noise(self, markdown_text: str) -> str:
        """Strip MDX/JSX wrapper components that bury code blocks in noise.

        Mintlify-style docs wrap content (and install commands) in
        ``<Tabs>``/``<Tab title="...">`` and aside components like
        ``<Tip>``/``<Info>``/``<Note>``/``<Warning>``/``<Caution>``. These tags
        and the bulky aside content push the actual commands past the
        truncation window of downstream retrieval/reranking, so drop the
        asides entirely and unwrap the tab containers while keeping their
        labelled content.
        """
        text = markdown_text
        # Drop whole aside blocks (including their content).
        for tag in ("Tip", "Info", "Note", "Warning", "Caution"):
            text = re.sub(rf"(?is)<{tag}>.*?</{tag}>\n*", "", text)
        # Unwrap tab containers, keeping the tab title as a bold label.
        text = re.sub(r"(?im)^\s*<Tabs[^>]*>\s*\n?", "", text)
        text = re.sub(r"(?im)^\s*</Tabs>\s*\n?", "", text)
        text = re.sub(r"(?im)^\s*<Tab title=\"([^\"]*)\"[^>]*>\s*\n?", r"**\1:**\n", text)
        text = re.sub(r"(?im)^\s*</Tab>\s*\n?", "", text)
        return text

    def split_markdown_sections(self, markdown_text: str) -> List[tuple[str, str]]:
        """Split a markdown page into section-level documents by H2 headings."""
        cleaned = markdown_text.strip()
        parts = re.split(r'(?m)^##\s+', cleaned)
        if len(parts) <= 1:
            return [("overview", cleaned)]

        sections: List[tuple[str, str]] = []
        preamble = parts[0].strip()
        if preamble:
            sections.append(("overview", preamble))

        for part in parts[1:]:
            lines = part.splitlines()
            if not lines:
                continue
            heading = lines[0].strip()
            body = "\n".join(lines[1:]).strip()
            if not body:
                continue
            sections.append((heading, f"## {heading}\n\n{body}"))
        return sections or [("overview", cleaned)]
