"""Narrow literal prohibition operator; no topic, article ID or legal threshold.

Only resolves an invented exception when both readings already establish
object, applicability, complete evidence and fidelity; full source must not
contain a conditional/exception marker or an unresolved article reference.
"""
import copy,re,unicodedata,hashlib


def plain(text):
 text=''.join(c for c in unicodedata.normalize('NFKD',text).lower() if not unicodedata.combining(c))
 return re.sub(r'\s+',' ',text.replace('’',"'")).strip()


def resolve(fact,rule,source,first,second):
 required=('meme_objet','applicable','complet','sans_contradiction','critere_fidele')
 if not all(v.get(k) is True for v in (first,second) for k in required):return None
 match=re.fullmatch(r'\s*(?:Les|Le|La)\s+([\wÀ-ÿ -]{3,100}?)\s+(?:est|sont)\s+(?:interdits?|interdites?|prohibés?|prohibées?)\s*\.\s*',rule,re.I)
 if not match:return None
 subject=match[1];full=plain(source.get('texte',''));target=plain(fact.get('citation_visible',''))
 if plain(rule) not in full:return None
 # Reject explicit exceptions/conditions across the complete article, not
 # merely the selected sentence. Unknown references cannot be discharged.
 if re.search(r"\b(?:sauf|si|lorsque|toutefois|cependant|neanmoins|hormis|except\w*|reserve|derog\w*|conditionnel\w*|autorisa\w*|autorise\w*|decret|arrete|reglement)\b|\ba (?:moins|condition)\b|\b(?:pourvu|tant) que\b|\b(?:article|articles)\s+[a-z0-9]|ne\s+.{0,45}\s+pas",full):return None
 if re.search(r"\b(?:si|lorsque|sauf|toutefois|cependant|reserve|except\w*|exemple|hypothese|citation|interdi\w*|prohib\w*)\b|\ben cas\b|\ba (?:moins|condition)\b|\bne\b|\bn'|\bpas\b",target):return None
 if any(k not in ('REGLE','CONTEXTE_CRITERE') for v in (first,second) for k in v.get('manques',[])):return None
 words=plain(subject).split()
 if not 1<=len(words)<=8:return None
 roots=[re.escape(w[:-1] if len(w)>3 and w.endswith('s') else w)+('s?' if len(w)>3 else '') for w in words]
 noun=r'\s+'.join(roots)
 imposed=re.search(r"\b(?:impose|imposent|exige|exigent|prescrit|prescrivent)\b[^.;!?]{0,100}\b(?:un|une|des|le|la|les)\s+"+noun+r'\b',target)
 if not imposed:return None
 proof=dict(method='interdiction_litterale_et_prescription_positive',rule_citation=rule,subject=subject,
  contract_citation=fact['citation_visible'],normalized_positive_prescription=imposed[0],
  source_sha256=hashlib.sha256(source['texte'].encode()).hexdigest(),
  source_conditions_markers_absent=True,source_article_reference_absent=True,
  application_and_object_confirmed_by_both_readings=True,model_readings=copy.deepcopy([first,second]),
  limitation='Opérateur syntaxique limité ; champ confirmé en amont. Ne prouve pas une couverture juridique exhaustive ni une analyse de toute jurisprudence.')
 readings=[]
 for original in (first,second):
  readings.append({**copy.deepcopy(original),'exceptions_resolues':True,'manques':[],'resultat':'ecart',
   'raison':'Le programme retrouve la même action explicitement imposée dans le contrat et interdite dans la règle ; aucune exception ou référence conditionnante explicite dans l’article complet.'})
 return dict(readings=readings,proof=proof)
