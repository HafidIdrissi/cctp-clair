"""Conclude a negative V5 numeric criterion only with complete recorded proof.

This reuses the existing comparisons and version-bound rules. It does not
infer a missing obligation, override an exception or validate a whole theme.
"""
import re

from slm_v5_policy import compact


def confirm_supported_deviations(analysis, readings, gates):
    if analysis.get('controle_juridique') is not True:
        return
    for row in analysis.get('lignes', []):
        fact = row['fait']
        kind = fact.get('type_fait')
        if (row.get('statut') != 'ecart_potentiel' or row.get('comparaison') is not False
                or kind not in ('largeur_pieton', 'devers_pieton', 'fente_grille')
                or fact.get('origine') != 'texte_natif'
                or not all(gates.get(key, {}).get('eligible') is True for key in ('access', 'scope'))):
            continue
        check = row.get('verification_automatique') or {}
        conditions = {k: v for k, v in check.get('checks', {}).items() if k != 'comparaison_positive'}
        if not conditions:
            continue
        # Below 1.20 m the result fails both alternatives already encoded by
        # the reviewed rule; unknown side obstacles cannot change this result.
        if kind == 'largeur_pieton' and type(fact.get('valeur_m')) in (int, float) and fact['valeur_m'] < 1.20:
            conditions['conditions_du_seuil'] = True
            check['checks']['conditions_du_seuil'] = True
            check.setdefault('evidence', {}).setdefault('conditions_du_seuil', {})['motif'] = (
                'Largeur inférieure à 1,20 m : aucune des deux alternatives de largeur de cette règle n’est satisfaite.')
            check['missing'] = [k for k,v in check['checks'].items() if v is not True]
        quote = compact(fact.get('citation_visible'))
        # An exception, hypothetical value or negation may change the meaning.
        conditions['clause_affirmative_non_conditionnelle'] = not bool(re.search(
            r'\b(?:si|sauf|sans travaux|ne|pas|non|hypothese|variante|option|exemple|derogation|existant)\b', quote))
        # The positive check has a project context. A multi-sector document can
        # require scope attribution that this limited checker cannot establish.
        alltext = compact('\n'.join(readings.get('text') or []))
        sectors = set(re.findall(r'\b(?:secteur|lot|troncon)\s+([a-z0-9]+)\b', alltext))
        conditions['contexte_sans_ambiguite_de_secteur'] = len(sectors) <= 1
        row['verification_ecart_automatique'] = dict(
            eligible=all(v is True for v in conditions.values()), checks=conditions,
            missing=[k for k,v in conditions.items() if v is not True],
            sources_versions={key:gates[key]['version_attendue'] for key in ('access','scope')},
            methode='Comparaison négative sur règle revue ; citation, mesure et conditions vérifiées.')
        if row['verification_ecart_automatique']['eligible']:
            row.update(statut='ecart_confirme_sur_critere', mode_verification='automatique',
                explication=row['explication']+' La citation, la mesure, le contexte et les versions officielles permettent de confirmer automatiquement cet écart sur le critère.',
                action={
                    'largeur_pieton':'Reprendre la largeur libre prévue : 1,40 m, ou 1,20 m uniquement lorsque l’absence de mur et d’obstacle des deux côtés est établie. Mettre en cohérence le CCTP et les plans.',
                    'devers_pieton':'Reprendre le dévers du cheminement courant pour respecter le maximum de 2 %, puis mettre en cohérence le profil et les prescriptions du CCTP.',
                    'fente_grille':'Prévoir des ouvertures de grille strictement inférieures à 2 cm et préciser cette exigence dans la prescription et la fiche du produit.'
                }[kind])
