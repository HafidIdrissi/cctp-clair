"""Recover complete numbered sections when the API flattened all newlines.

Only the Core exact reviewed catalogue opts in. Slices retain all source text;
numbering must be a full, consecutive 1..N sequence or nothing is split.
"""
import re

def sections(source):
 text=source['texte']
 markers=list(re.finditer(r'(?<!\w)(\d{1,2})\s*[°º]\s+(?=[A-ZÀ-ÖØ-Þ])',text))
 if len(markers)<2 or [int(m[1]) for m in markers]!=list(range(1,len(markers)+1)):return [text]
 starts=[0]+[m.start() for m in markers]+[len(text)]
 parts=[text[a:b].strip() for a,b in zip(starts,starts[1:]) if text[a:b].strip()]
 assert re.sub(r'\s+','',text)==re.sub(r'\s+','',''.join(parts))
 return parts
