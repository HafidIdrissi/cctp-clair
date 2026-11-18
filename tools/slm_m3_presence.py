"""Literal absence evidence for existing reviewed presence criteria only."""
import re


def absence(fact, readings, pool, reference):
    from slm_v6_visual_evidence import verified
    from slm_v6_numeric_evidence import reviewed_criterion
    from slm_v6_focused_review import article_sections
    from v4_8_document_service import norm
    kind=fact.get('type_fait')
    if kind not in ('bande_eveil','absence_amenagement_cyclable') or not verified(fact,readings):return None
    text=norm(fact.get('citation_visible',''))
    if re.search(r'(?:pas|non).{0,12}(?:absence|absent|aucun)',text):return None
    if not re.search(r'aucun|absence|non prevu|ni piste',text):return None
    if kind=='bande_eveil' and not re.search(r'bande.{0,15}eveil',text):return None
    if kind=='absence_amenagement_cyclable' and not re.search(r'cyclabl|piste',text):return None
    matches=[]
    for source in pool.values():
        for section in article_sections(source):
            binding=reviewed_criterion(fact,source,section,reference)
            if binding and binding.get('nature')=='presence':
                matches.append(dict(id=fact['id'],source_id=source['id'],obligation=binding['obligation'],
                    resultat=False,calcul='Absence explicitement écrite : '+fact['citation_visible'],
                    method='absence_ecrite_ocr_et_deux_relectures_image',binding=binding,
                    limite='Présence seulement ; même objet, champ juridique et exceptions à établir séparément.'))
    return matches[0] if len(matches)==1 else None
