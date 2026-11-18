"""Annotate the quoted CCTP lines using the decisions in the exported report."""
import re
from html import escape, unescape
from urllib.parse import urlsplit

STYLE = """
.clause-law{display:block;border:2px solid #a62338;border-radius:6px;padding:.45em .65em;background:#fff4f4;color:#342225}
.clause-law.ok{border-color:#157249;background:#effaf4;color:#143c2d}
.clause-law .law-note{display:none;margin-top:.4em}
.clause-law:hover .law-note,.clause-law:focus-within .law-note{display:block}
.clause-law a{color:#124c79;text-decoration:underline}
@media print{.clause-law .law-note{display:block}}
"""


def annotation(row):
    source = row.get('source_display') or {}
    status = row.get('status')
    if source.get('kind') != 'legal' or status not in ('critere_auto_respecte','ecart_confirme_sur_critere'):
        return None
    url = source.get('url') or (row.get('source') or {}).get('url') or ''
    if not url.startswith('https://www.legifrance.gouv.fr/'):
        url = ''
    return dict(ok=status=='critere_auto_respecte', title=source.get('title') or '',
                metadata=' · '.join(source.get('metadata') or []), url=url,
                reason=(row.get('presentation') or {}).get('detail') or row.get('explanation') or '')


def mark(row, quote):
    a = annotation(row)
    label = 'Conforme' if a['ok'] else 'Non conforme'
    link = f' <a href="{escape(a["url"],quote=True)}" target="_blank" rel="noopener">Lire sur Légifrance</a>' if a['url'] else ''
    return (f'<div class="clause-law{" ok" if a["ok"] else ""}" tabindex="0">'
            f'{escape(quote)}<div class="law-note"><strong>{label} · {escape(a["title"])}</strong>'
            f'<br>{escape(a["metadata"])}<br>{escape(a["reason"])}{link}</div></div>')


def render(html, result):
    rows = {r['id']: r for r in result.get('findings', []) if annotation(r)}
    seen = set()
    def annotate(match):
        ident = unescape(match['id']).strip()
        if ident not in rows:
            return match[0]
        seen.add(ident)
        return match[0].replace('<td>'+match['quote']+'</td>', '<td>'+mark(rows[ident], unescape(match['quote']))+'</td>', 1)
    html = re.sub(r'<tr><td><span class="badge (?:pass|fail)">[^<]*</span></td><td>(?P<quote>[^<>]*)</td><td>(?P<id>[\w-]+) · p\. [^<]*</td></tr>', annotate, html)
    extras = [f'<p>{escape(i)} · p. {escape(str(r.get("page","")))}</p>'+mark(r,r.get('quote') or r.get('title') or i)
              for i,r in rows.items() if i not in seen]
    if extras:
        html = html.replace('</body>','<section><h2>Passages comparés aux textes juridiques</h2>'+''.join(extras)+'</section></body>')
    return html.replace('</head>', '<style>'+STYLE+'</style></head>').encode('utf8')
