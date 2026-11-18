"""Urban mobility dossier coverage. No network or new legal verdicts.

Keyword matches are navigation evidence, not proof that an obligation applies.
Only the existing evaluator may supply a result on a programmed criterion.
"""
import re
import unicodedata
from html import escape


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFD', str(value or ''))
                   if not unicodedata.combining(c)).lower().replace('’', "'")


# Questions to investigate, not a list of universally mandatory requirements.
# The catalogue is deliberately explicit about what the current engine covers.
THEMES = (
    ('accessibilite', 'Cheminements et accessibilité',
     r'\b(pieton\w*|trottoir\w*|accessibil\w*|ressaut\w*|devers|grille\w*|eveil)\b',
     'Continuité, largeur utile, pente, dévers, obstacles, ressauts et vigilance.',
     'Contrôles ciblés de largeur piétonne, dévers, ressaut, grille et vigilance.',
     ('largeur_pieton', 'devers_pieton', 'ressaut', 'fente_grille', 'bande_eveil')),
    ('cyclable', 'Itinéraires et aménagements cyclables',
     r'\b(cyclab\w*|cyclist\w*|velo\w*|voie\w* verte\w*)\b',
     'Obligation d’itinéraire selon les travaux, continuité, intersections et choix de conception.',
     'Contrôle ciblé de l’absence explicite d’aménagement ; largeur technique selon référentiel fourni.',
     ('largeur_cyclable', 'absence_amenagement_cyclable')),
    ('traversees', 'Traversées et visibilité',
     r'\b(passage\w* pieton\w*|traversee\w*|visibilite|stationnement\w* en amont)\b',
     'Position des passages, visibilité et stationnement en amont.',
     'Contrôle ciblé de la distance de stationnement en amont.',
     ('distance_stationnement_amont',)),
    ('circulation', 'Régime de circulation',
     r'\b(zone\w* 30|zone\w* de rencontre|double.?sens|sens unique|aire\w* pietonn\w*)\b',
     'Cohérence entre régime annoncé, double sens cyclable et décisions de police.',
     'Recherche documentaire possible ; pas de contrôle complet de ces décisions.', ()),
    ('signalisation', 'Signalisation et intersections',
     r'\b(signalis\w*|marquage\w*|panneau\w*|feu\w* tricolore\w*|carrefour\w*)\b',
     'Cohérence de la signalisation, du marquage et des plans d’intersection.',
     'Recherche documentaire possible ; prescriptions et plans non contrôlés intégralement.', ()),
    ('transports', 'Transports collectifs et arrêts',
     r'\b(bus|tramway\w*|transport\w* collectif\w*|arret\w* de (?:bus|car)|quai\w*)\b',
     'Accessibilité des arrêts, quais, cheminements et interfaces avec l’exploitant.',
     'Contrôle spécifique des arrêts et interfaces à développer.', ()),
    ('stationnement', 'Stationnement et livraisons',
     r'\b(stationnement\w*|parking\w*|livraison\w*)\b',
     'Places accessibles, accès, dimensions, localisation et livraisons.',
     'Le contrôle en amont d’un passage ne couvre pas les autres règles de stationnement.', ()),
    ('chaussee', 'Chaussées et matériaux',
     r'\b(chaussee\w*|revetement\w*|enrobe\w*|bordure\w*|materiau\w*|materiaux)\b',
     'Adéquation des matériaux, performances, réception et référentiels contractuels.',
     'Normes, essais et performances non contrôlés automatiquement.', ()),
    ('eaux', 'Eaux pluviales et drainage',
     r'\b(pluvial\w*|drainage|assainissement|ruissellement|infiltration)\b',
     'Drainage, interfaces, rejets et procédures environnementales selon le projet.',
     'Applicabilité et dimensionnement à documenter.', ()),
    ('reseaux', 'Travaux à proximité des réseaux',
     r'\b(reseau\w*|dict|aipr|dt.?dict|canalisation\w*)\b',
     'Repérage, responsabilités, déclarations et compétences selon les travaux.',
     'Contrôle DT/DICT et des pièces justificatives à développer.', ()),
    ('chantier', 'Phasage et sécurité du chantier',
     r'\b(chantier\w*|phasage|balisage|deviation\w*|maintien\w* des acces)\b',
     'Maintien des accès, cheminements temporaires et cohérence du phasage.',
     'Organisation du chantier et plans temporaires non contrôlés intégralement.', ()),
    ('commande', 'Clauses et spécifications du marché',
     r'\b(marque\w*|equivalent\w*|specification\w*|ccap|ccag|cctg|bpu|dpgf)\b',
     'Références à des marques, équivalence, performances et cohérence entre pièces.',
     'Contrôle juridique des clauses de commande publique à développer.', ()),
    ('local', 'Règles et documents locaux',
     r'\b(municipal\w*|arrete\w*|plan\w* de mobilite|plu|plui|reglement\w* de voirie)\b',
     'Identifier les documents locaux applicables et obtenir leurs versions.',
     'Une mention dans le CCTP ne prouve pas que la pièce locale a été examinée.', ()),
    ('derogation', 'Dérogations et exceptions',
     r'\b(derogation\w*|impossibilite technique|exception\w*)\b',
     'Justification, procédure, décision et portée des exceptions invoquées.',
     'Contrôle ciblé de certaines dérogations d’accessibilité.', ('derogation_par_visa',)),
)

PIECES = (
    ('plans', 'Plans et coupes', r'\b(plan\w*|coupe\w*)\b',
     'Relier chaque prescription à un emplacement et aux dimensions du projet.'),
    ('ccap', 'CCAP et acte d’engagement', r'\b(ccap|acte d.engagement)\b',
     'Examiner les pièces contractuelles, leur priorité et les éventuelles contradictions.'),
    ('prix', 'BPU ou DPGF', r'\b(bpu|dpgf|bordereau\w* de\w* prix)\b',
     'Comparer les prestations décrites avec les postes de prix.'),
    ('local', 'Décisions et règles locales', r'\b(municipal\w*|arrete\w*|plan\w* de mobilite|plui?|reglement\w* de voirie)\b',
     'Vérifier le document pertinent, sa date et son champ d’application.'),
    ('technique', 'Référentiels techniques cités', r'\b(nf|en \d|dtu|cerema|cctg|rer.?v|norme\w*)\b',
     'Obtenir la version des référentiels retenus ; une citation seule ne fournit pas leur contenu.'),
)

QUESTIONS = {
    'champ_application_documente': 'Quels travaux sont prévus, sur quelle voirie, et dans quel périmètre public ou privé ?',
    'etat_projet': 'Cette valeur décrit-elle l’ouvrage prévu par les travaux ou uniquement l’existant ?',
    'conditions_du_seuil': 'La largeur réduite est-elle libre de mur et d’obstacle de part et d’autre ?',
    'citation_exacte_page_native': 'Quel passage lisible du document confirme cette donnée et son emplacement ?',
    'objet_et_mesure_explicites': 'La dimension concerne-t-elle l’objet contrôlé, sans mélange avec une autre mesure ?',
    'unite_et_conversion_coherentes': 'Quelle valeur et quelle unité sont effectivement prescrites ?',
    'lecture_sans_ambiguite': 'Quelle prescription retenir parmi les passages contradictoires ou ambigus ?',
    'sources_datees_disponibles': 'Quelle version officielle du texte est applicable à la date du dossier ?',
}


def build_review(readings, analysis):
    """Inventory exact extracted passages and actual recorded criterion results.

    No missing keyword is turned into a missing mandatory clause. A referenced
    annex is never counted as an uploaded/examined annex. Human confirmations
    do not change the automatic coverage counts.
    """
    pages = readings.get('text') or []
    if not isinstance(pages, list) or any(not isinstance(p, str) for p in pages):
        raise ValueError('Texte extrait attendu sous forme de liste de pages.')
    passages = [(page, paragraph.strip()) for page, text in enumerate(pages, 1)
                for paragraph in re.split(r'\n\s*\n', text) if paragraph.strip()]
    rows = analysis.get('lignes') or []
    enabled = analysis.get('controle_juridique', True) is True
    themes = []
    for key, title, pattern, question, coverage, types in THEMES:
        matched = [(page, text) for page, text in passages if re.search(pattern, normalized(text))]
        associated = [row for row in rows if row.get('fait', {}).get('type_fait') in types]
        accepted = [row for row in associated if enabled and
                    (row.get('statut_automatique', row.get('statut')) == 'critere_auto_respecte' or
                     (row.get('statut_automatique', row.get('statut')) == 'ecart_confirme_sur_critere'
                      and row.get('mode_verification') == 'automatique'))
                    and row.get('source') and row.get('regle')
                    and type(row.get('comparaison')) is bool]
        status = ('lecture_seule' if not enabled else 'controle_partiel' if accepted
                  else 'repere_sans_verdict' if matched or associated else 'non_repere')
        themes.append(dict(id=key, titre=title, statut=status, question=question,
            couverture_actuelle=coverage, passages_reperes=len(matched),
            pages=sorted({page for page, _ in matched}),
            criteres_automatiques=len(accepted),
            ecarts_signales=sum(enabled and row.get('statut_automatique', row.get('statut')) in
                               ('ecart_potentiel', 'ecart_confirme_sur_critere') for row in associated),
            faits_ids=[row['fait']['id'] for row in associated],
            extraits=[dict(page=page, citation=text[:800], extrait_tronque=len(text) > 800)
                      for page, text in matched[:3]],
            extraits_non_affiches=max(0, len(matched)-3),
            conformite_theme_etablie=False))
    text = normalized('\n'.join(pages))
    pieces = [dict(id=key, titre=title, mentionnee=bool(re.search(pattern, text)),
                   contenu_verifie=False, statut='contenu_non_etabli', utilite=why,
                   exigibilite='selon_projet_et_pieces_contractuelles')
              for key, title, pattern, why in PIECES]
    questions = []
    if enabled:
        for key, question in QUESTIONS.items():
            affected = [row['fait']['id'] for row in rows
                        if row.get('statut_automatique', row.get('statut')) not in
                        ('critere_auto_respecte', 'ecart_confirme_sur_critere', 'lecture_rejetee', 'hors_perimetre')
                        and key in ((row.get('verification_automatique') or {}).get('missing') or [])]
            if affected:
                questions.append(dict(id=key, question=question, faits_ids=affected))
    return dict(version='mobilite-urbaine-1', domaine_prioritaire='Mobilité urbaine',
        date_reference=analysis.get('date_reference'), controle_juridique=enabled,
        methode='Repérage lexical dans le texte extrait et inventaire des contrôles enregistrés',
        document_principal=readings.get('filename') or 'Document analysé',
        pages_texte_extrait=sum(bool(p.strip()) for p in pages),
        pages_sans_texte=[i for i, p in enumerate(pages, 1) if not p.strip()],
        themes=themes, pieces=pieces, questions_ciblees=questions,
        conclusion='Lecture documentaire uniquement.' if not enabled else
          'Des contrôles ciblés sont disponibles. La revue juridique complète du dossier n’est pas établie.',
        conformite_globale_etablie=False, revue_juridique_complete=False,
        limites=['Un thème non repéré ne signifie ni absence d’obligation ni inapplicabilité.',
                 'Une pièce citée n’est pas une pièce fournie et vérifiée.',
                 'Les plans intégrés, l’OCR et les images restent soumis à leurs contrôles de lecture.',
                 'Ce catalogue de questions n’est pas une liste exhaustive du droit de la mobilité urbaine.'])


STATUS_LABELS = dict(controle_partiel='Contrôles ciblés enregistrés',
                     repere_sans_verdict='Repéré · contrôle à compléter',
                     non_repere='Non repéré dans le texte', lecture_seule='Lecture seule')


def presented_review(review, analysis):
    """Annotate a view with recorded comparisons; never rewrite coverage proof."""
    import copy
    result = copy.deepcopy(review)
    comparisons = []
    for row in analysis.get('lignes') or []:
        check = row.get('verification_technique') or {}
        gates, reference = check.get('checks') or {}, check.get('reference') or {}
        if (check.get('eligible') is True and gates and all(v is True for v in gates.values())
                and check.get('outcome') in ('respecte', 'ecart') and check.get('calcul')
                and (check.get('critere') or {}).get('citation')
                and reference.get('titre') and reference.get('page') is not None):
            comparisons.append(dict(fait_id=(row.get('fait') or {}).get('id'),
                titre=reference['titre'], page=reference['page'],
                citation=check['critere']['citation']))
    if comparisons:
        for piece in result.get('pieces') or []:
            if piece.get('id') == 'technique':
                piece['comparaisons_techniques_affichees'] = comparisons
                refs = {}
                for item in comparisons:
                    refs.setdefault(item['titre'], set()).add(item['page'])
                sources = '; '.join(title + ' (pages ' + ', '.join(map(str, sorted(pages))) + ')'
                                    for title, pages in refs.items())
                piece['presentation_contenu'] = ('Contenu consulté pour ' + str(len(comparisons))
                    + ' comparaisons de critères : ' + sources + '. Examen limité aux passages cités ; '
                    'aucune validation globale de ces référentiels ni des autres pièces techniques.')
    return result


def piece_detail(piece):
    return piece.get('presentation_contenu') or ('Examen du contenu non établi. ' + piece['utilite'])


def html_review(review):
    h = lambda value: escape(str(value))
    out = ['<section class="v5 urban-review"><h2>Revue du dossier · mobilité urbaine</h2>',
           '<p>'+h(review['conclusion'])+'</p>',
           '<p>Les résultats portent sur des critères précis. Repérer un thème ne vérifie pas toutes ses obligations.</p>']
    if review.get('questions_ciblees'):
        out += ['<h3>Informations à préciser pour poursuivre les contrôles</h3><ul>']
        out += ['<li>'+h(q['question'])+' — '+h(', '.join(q['faits_ids']))+'</li>'
                for q in review['questions_ciblees']]
        out += ['</ul>']
    for theme in review['themes']:
        out += ['<details><summary>'+h(theme['titre'])+' · '+h(STATUS_LABELS[theme['statut']])+'</summary>',
                '<p>'+h(theme['question'])+'</p>', '<p>'+h(theme['couverture_actuelle'])+'</p>',
                '<p>Critères automatiques enregistrés : '+str(theme['criteres_automatiques'])+
                ' · Écarts signalés : '+str(theme['ecarts_signales'])+'</p>']
        for excerpt in theme['extraits']:
            out += ['<blockquote>Page '+str(excerpt['page'])+' : '+h(excerpt['citation'])+
                    ('… [extrait tronqué]' if excerpt['extrait_tronque'] else '')+'</blockquote>']
        out += ['</details>']
    out += ['<h3>Pièces à rapprocher du CCTP, selon le projet</h3><ul>']
    for piece in review['pieces']:
        out += ['<li><strong>'+h(piece['titre'])+'</strong> · '+
                ('Mention repérée' if piece['mentionnee'] else 'Mention non repérée')+
                ' ; '+h(piece_detail(piece))+'</li>']
    return ''.join(out+['</ul></section>'])
