"""Narrow structural recognition, independent of any legal topic or document.

The caller must separately establish that the quotation exists on its native
page. This module recognizes only short table-of-contents lines, not whether a
technical clause is binding, compliant, recommended or legally applicable.
"""
from __future__ import annotations

import re
import unicodedata

REASON = "Entrée de sommaire, renvoi de page, pas une prescription"
_LINE = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*\.?|[IVXLCDM]+[.)]?)\s+)?"
    r"(?P<title>[^\r\n]+?)\s*(?P<leader>_{4,}|\.{4,})\s*(?P<page>\d{1,4})\s*$"
)
# These words prevent a structural classification. They never establish any
# legal conclusion; ambiguous passages continue through the normal analysis.
_PRESCRIPTIVE = re.compile(
    r"\b(?:obligatoir\w*|obligation\w*|doit|doivent|devra\w*|devront|devoir|"
    r"faut|falloir|imperati\w*|impos\w*|exig\w*|prescri\w*|interdi\w*|"
    r"proscri\w*|respect\w*|requis\w*|requise\w*|necessair\w*|"
    r"recommand\w*|preconis\w*|prevoir|prevu\w*|prevoy\w*|assur\w*|"
    r"garanti\w*|realiser|realise\w*|installer|installe\w*|fournir|fourni\w*|"
    r"permet\w*|comport\w*|est|sont|sera|seront|aura|auront|\w+(?:era|eront|ira|iront|tra|tront))\b"
)


def structural_context_reason(quote: str) -> str | None:
    """Return a reason only if every nonempty line is a clear TOC entry.

    At most 300 characters; at least four consecutive dots/underscores; a
    trailing positive page number; a textual title; no prescription wording.
    This deliberately accepts false negatives instead of hiding requirements.
    """
    if not isinstance(quote, str) or not quote.strip() or len(quote) > 300:
        return None
    normalized = unicodedata.normalize("NFKD", quote)
    normalized = "".join(c for c in normalized if not unicodedata.combining(c)).lower()
    if _PRESCRIPTIVE.search(normalized):
        return None
    lines = [line for line in quote.splitlines() if line.strip()]
    for line in lines:
        match = _LINE.fullmatch(line)
        if not match or int(match["page"]) < 1:
            return None
        title = match["title"].strip()
        if not any(character.isalpha() for character in title):
            return None
        # A dotted or underscored data expression is not a title. Nor is a
        # measure ending in a number, which might be a badly extracted clause.
        if re.search(r"[\d%=<>≤≥]", title):
            return None
    return REASON if lines else None


def _paired_page_index_reason(quote: str, page: str) -> str | None:
    """Recognize a complete entry in an explicitly mapped native page index.

    A bare ``16 / 20`` may be a ratio, grade or dimension. It becomes a page
    cross-reference here only inside a whole, strictly parsed index paragraph
    whose first entry spells out source-page/PDF-page semantics. Nothing from
    an adjacent project paragraph is included or discarded by this check.
    """
    flat = lambda text: re.sub(r'\s+', ' ', text).strip()
    def plain(text):
        return ''.join(c for c in unicodedata.normalize('NFKD', text.lower())
                       if not unicodedata.combining(c)).replace('’', "'")
    citation = flat(quote)
    native = flat(page)
    if not citation or len(citation) > 120 or native.count(citation) != 1:
        return None
    blocks = [part.strip() for part in re.split(r'\n[ \t]*\n', page) if part.strip()]
    first_entry = re.compile(
        r'(?P<label>[^:.;\r\n]{2,80}):\s*page\s+(?:d\'origine|imprimee|source)\s+'
        r'(?P<source>\d{1,4})\s*/\s*page\s+(?:pdf|du fichier)\s+(?P<pdf>\d{1,4})\.')
    next_entry = re.compile(r'(?P<label>[^:.;\r\n]{2,80}):\s*'
                            r'(?P<source>\d{1,4})\s*/\s*(?P<pdf>\d{1,4})\.')
    for index, block in enumerate(blocks):
        content = flat(block)
        if citation not in content or len(content) > 2000 or index == 0:
            continue
        heading = plain(flat(blocks[index-1]))
        if not re.fullmatch(r'(?:\d+(?:\.\d+)*\.?\s+)?'
                            r'(?:index|sommaire|table des matieres|renvois de pages)\b[^\n]{0,100}', heading):
            continue
        if '\n' in blocks[index-1] or _PRESCRIPTIVE.search(heading):
            continue
        remaining = plain(content)
        entries = []
        while remaining:
            match = (first_entry if not entries else next_entry).match(remaining)
            if not match:
                break
            label = match['label'].strip()
            # Only plain textual titles. Units/operators and prescriptive
            # words cannot be silently reinterpreted as page references.
            if (not any(c.isalpha() for c in label) or len(label.split()) > 10
                    or re.search(r'[\d%=<>≤≥/]', label)
                    or _PRESCRIPTIVE.search(label)
                    or int(match['source']) < 1 or int(match['pdf']) < 1):
                break
            entries.append(match.group())
            remaining = remaining[match.end():].lstrip()
        if not remaining and len(entries) >= 3 and plain(citation) in entries:
            return ('Entrée d’index native : correspondance explicite entre page '
                    'd’origine et page PDF ; aucune prescription dans ce renvoi')
    return None


def documentary_structure_reason(quote: str, page: str) -> str | None:
    """Recognize isolated section headings and complete lists of figures.

    A heading must occupy its own native line; a fragment within a substantive
    line never qualifies. Lists must be entirely composed of numbered entries
    with leaders/page references. No source requirement is inferred here.
    """
    reason=structural_context_reason(quote)
    if reason:return reason
    if not isinstance(quote,str) or not isinstance(page,str):return None
    reason = _paired_page_index_reason(quote, page)
    if reason:return reason
    flat=re.sub(r'\s+',' ',quote).strip()
    heading=re.fullmatch(r'\d+(?:\.\d+){1,4}\.?\s+([^\d\r\n:;%=<>≤≥]{2,90})',flat)
    if heading:
        title=heading[1]
        plain=''.join(c for c in unicodedata.normalize('NFKD',title.lower()) if not unicodedata.combining(c))
        if (len(title.split())<=9 and not _PRESCRIPTIVE.search(plain)
            and not re.search(r'\b(?:minimum|maxim\w*|minimal\w*|absent\w*|supprim\w*|sans)\b',plain)
            and flat in [re.sub(r'\s+',' ',line).strip() for line in page.splitlines()]):
            return 'Titre de section isolé sur la page ; aucune prescription dans ce titre'
    # Native extraction may concatenate all entries of a figure index.
    entry=re.compile(r'(?:Schéma|Figure|Tableau)\s+\d+\s*:\s*[^\r\n]*?\.{4,}\s*\d{1,4}(?=\s+(?:Schéma|Figure|Tableau)\s+\d+\s*:|$)',re.I)
    matches=list(entry.finditer(flat))
    if len(matches)>=2 and all(not flat[a:b].strip() for a,b in
        zip([0]+[m.end() for m in matches],[m.start() for m in matches]+[len(flat)])):
        return 'Liste de figures avec renvois de pages ; examiner les figures et leurs prescriptions à leurs pages'
    return None
