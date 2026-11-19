# CCTP Clair

CCTP Clair lit un cahier des clauses techniques particulières sur votre PC et rapproche ses prescriptions des articles juridiques disponibles. Son rapport indique le passage examiné, la règle retenue et le résultat du contrôle.

## Ouvrir CCTP Clair sur Windows

1. **[Téléchargez CCTP-Clair-Windows.zip](https://github.com/HafidIdrissi/cctp-clair/releases/latest/download/CCTP-Clair-Windows.zip)**.
2. Dans **Téléchargements**, faites un clic droit sur le ZIP, cliquez sur **Extraire tout**, puis sur **Extraire**. Ouvrez le dossier extrait.
3. Double-cliquez sur **Lancer CCTP Clair.cmd**. Windows peut masquer la terminaison « .cmd ». Le premier lancement installe les composants manquants avec le Gestionnaire de paquets Windows et télécharge le modèle. Gardez la fenêtre ouverte jusqu’à l’ouverture du navigateur.
4. Cliquez sur **Tester avec l’exemple**. Dans **Mes rapports**, attendez **Rapport prêt**, puis cliquez sur **Lire le rapport**. Le bouton **Me guider** montre ces commandes à l’écran.

Les fois suivantes, utilisez le même fichier de lancement. Gardez le dossier extrait au même emplacement pour retrouver votre historique.

![Du premier clic à la lecture du rapport dans le navigateur](guide/premier-essai.gif)

## Faire un premier contrôle

Le [PDF fictif fourni](demo/Exemple.pdf) décrit un cheminement piéton de **1,10 m**. Le bouton d’essai remplit le contexte et choisit le **1er juillet 2024** comme date de référence. Le test est terminé lorsque vous pouvez ouvrir le rapport et télécharger le PDF. Le moteur effectue une nouvelle analyse à chaque essai. Un passage peut rester sans décision lorsque les preuves ou les conditions d’application sont insuffisantes.

Pour examiner votre document, cliquez sur **Choisir un fichier**, renseignez le **lieu** et la **date**, puis cliquez sur **Lancer l’analyse**. Les PDF sont limités à 15 pages. Les fichiers PDF, PNG ou JPEG peuvent peser jusqu’à 25 Mo. La lecture visuelle automatique sélectionne au maximum six pages. Lorsqu’une décision juridique est étayée, le rapport HTML annoté permet d’examiner la ligne au survol ou au clavier.

## Refaire les essais avec les contrats fictifs

**Pour commencer, essayez Rennes B, puis Rennes A.** Dans le dossier extrait, ouvrez `demo/contrats` pour retrouver les PDF. Dans CCTP Clair, cliquez sur **Fichier PDF ou image**, choisissez Rennes B, saisissez **Rennes** et la date du **1er juillet 2024**, puis cliquez sur **Lancer l’analyse**. Recommencez avec Rennes A en gardant la même date et le même modèle.

| Contrat à ouvrir | Pages | Ce que vous pouvez vérifier |
| --- | ---: | --- |
| [Rennes B · liaison des Aulnes avec défauts](demo/contrats/CCTP_Rennes_liaison_cyclable_B_avec_defauts_4_pages.pdf) | 4 | Sur la coupe de la page 2, la largeur piétonne indiquée est de **1,10 m**. Dans le rapport, cherchez cette valeur, sa page et l’article cité. |
| [Rennes A · même liaison, corrigée](demo/contrats/CCTP_Rennes_liaison_cyclable_A_version_corrigee_4_pages.pdf) | 4 | Au même endroit, la largeur passe à **1,60 m**. Les deux plans diffèrent sur cinq points. Après l’essai, comparez vos résultats à la [clé de lecture des pages 2 et 3](demo/contrats/Rennes-cle-de-test.md). |
| [Nantes · liaison cyclable des Ateliers](demo/contrats/CCTP_fictif_Nantes_piste_cyclable_images.pdf) | 12 | Saisissez **Nantes** et le **1er juillet 2024**. Ouvrez les annexes des pages 7 à 11, puis regardez quelles cotes et quelles traversées le moteur a retrouvées. |
| [Rennes · éclairage et largeur](demo/contrats/CCTP_test_parametres_nouveaux_Rennes.pdf) | 2 | À la même date, vérifiez si le rapport distingue la largeur (mètres), l’éclairement (lux) et la température de couleur (kelvins). |

Ces documents sont des scénarios pédagogiques. Nantes et Rennes désignent les lieux simulés. Pour comparer deux résultats, gardez aussi la même version du corpus juridique. La clé de Rennes décrit les cinq différences introduites dans les plans. Elle se consulte après les deux analyses.

**Autres essais disponibles**

- **Montfleury, 3 pages par version.** Comparez les clauses et l’annexe de plan de deux lots de voirie avant et après révision. [Contrat initial](demo/contrats/Contrat_fictif_mobilite_initial.pdf) · [Contrat corrigé](demo/contrats/Contrat_fictif_mobilite_corrige.pdf)
- **Valmont-sur-Rive, 1 page.** Suivez les prescriptions d’une liaison cyclable sur un document court. [Liaison des Tilleuls](demo/contrats/CCTP_synthetique_Valmont_liaison_Tilleuls.pdf)
- **Huit dossiers d’évaluation, de 3 à 4 pages.** Ils isolent des difficultés de lecture comme une cote absente, des unités équivalentes ou un itinéraire contradictoire. [Parcourir les cas EV01 à EV08](demo/contrats/evaluation)
- **Fourniture de biens, 1 page.** Cette clause d’engagement perpétuel permet d’observer la couverture du corpus en dehors de la voirie. [Contrat de fourniture](demo/contrats/Essai_fictif_fourniture_duree_perpetuelle.pdf)

## Ce qu’il faut sur le PC

- Windows 10 ou 11, 64 bits, un navigateur et Internet pour la première installation. Prévoyez plusieurs gigaoctets libres. Le temps de traitement dépend du PC.
- Le lanceur utilise Python 3.11, Ollama et **Ministral 3B**. Les bibliothèques Python s’installent dans le dossier .venv. Les modèles Ollama déjà présents sont réutilisés. **Choisir le modèle local** permet de sélectionner un autre modèle de comparaison. La lecture des images utilise Ministral 3B.
- Si le gestionnaire de paquets Windows manque, installez Python 3.11 et Ollama depuis leurs sites officiels, puis relancez le fichier. Sur un poste géré par votre organisation, votre support peut installer ces deux composants. [Python pour Windows](https://www.python.org/downloads/windows/) · [Ollama pour Windows](https://ollama.com/download/windows)
- Si le navigateur tarde à s’ouvrir, attendez la fin du téléchargement affiché dans la fenêtre. Si le lanceur signale un problème de port, consultez le fichier local/erreur.log. Une fois le service lancé, [ouvrir CCTP Clair sur ce PC](http://127.0.0.1:8789).

## Quels textes sont utilisés ?

L’édition portable livre **trois XML officiels** extraits du stock LEGI du 13 juillet 2025. Le moteur crée un petit index local au premier lancement. Ce périmètre permet de tester la voirie et l’accessibilité à une date historique. Le corpus complet et le relais PISTE utilisés sur le poste de développement sont propres à cette installation. Un rapport couvre uniquement les critères effectivement contrôlés. [Fichiers et provenance](demo/SOURCES.md)

Les fichiers soumis, les requêtes du modèle et les rapports sont conservés dans le dossier local/ de votre installation, y compris le document soumis sous forme encodée. Un lien Légifrance ouvre le site officiel dans votre navigateur.

## Utilisation avec n8n (facultatif)

Le double-clic démarre le moteur directement. Pour le déclencher depuis **n8n installé sur le même Windows**, ouvrez un workflow vide, choisissez **Import from File** dans le menu du workflow, puis sélectionnez [Tester CCTP Clair.json](n8n/Tester%20CCTP%20Clair.json). Cliquez sur **Execute workflow**. Le dernier nœud lance la même analyse et renvoie le lien de suivi du rapport. Le service écoute sur la boucle locale du PC. Ce workflow vise une instance n8n native sur ce PC.

## Vérification de cette édition

Le démarrage a été testé dans un dossier Windows neuf avec un environnement Python neuf, Python et Ollama déjà présents sur le poste. Le PDF fictif a été soumis depuis le navigateur. L’installation automatique des deux prérequis sur un Windows entièrement vierge reste à vérifier.
## Élargir le corpus de mobilité (facultatif)

Après le premier lancement, terminez les analyses en cours, puis double-cliquez sur **Actualiser les textes DILA.cmd**. L’outil demande confirmation, télécharge le stock officiel LEGI et ses mises à jour disponibles et construit un index filtré pour les CCTP de mobilité. Prévoyez plusieurs Go et une opération longue. Cette actualisation réseau est distincte du test rapide avec trois articles.

## Partie technique — comment fonctionne le SLM ?

Le **SLM** (*Small Language Model*, ou petit modèle de langage) intervient dans une chaîne de traitement locale. Par défaut, **Ollama** exécute le modèle `ministral-3:3b` sur le PC. Le modèle aide à lire les plans et à rapprocher une prescription d’une règle. Le programme Python recherche les sources, vérifie les comparaisons qu’il sait calculer et assemble le rapport.

| Étape | Ce que fait l’application | Où lire le code |
| --- | --- | --- |
| 1. Recevoir le document | Le navigateur envoie le fichier, le lieu, la date juridique et le modèle choisi à `POST /jobs` sur `127.0.0.1:8789`. Le service renvoie un identifiant qui permet de suivre l’analyse. Le workflow n8n de démonstration appelle ce même point d’entrée. | [Serveur HTTP](clair.py) · [Orchestration](tools/slm_core_service.py) |
| 2. Lire les pages | Le lecteur extrait le texte du PDF. La reconnaissance de caractères (OCR) et la lecture visuelle des pages sélectionnées aident à retrouver les inscriptions dans les plans. Le moteur décompose les passages en faits à contrôler et conserve leur page et leur citation. | [Lecture du document](tools/v4_8_document_service.py) · [Découpage en faits](tools/slm_core_atoms.py) |
| 3. Trouver un article | Au premier lancement, le programme lit les XML du fonds LEGI de la DILA et indexe les articles, leurs identifiants et leurs dates dans SQLite. La recherche plein texte (FTS5) et les références connues permettent de retrouver des articles candidats à la date du projet. L’édition portable utilise ses sources locales. | [Index et recherche DILA](tools/dila_local_store.py) · [Recherche initiale](tools/slm_core_initial_retrieval.py) |
| 4. Comparer | Le moteur rapproche le fait de l’extrait juridique et examine les conditions d’application. Pour les critères chiffrés pris en charge, Python vérifie la valeur, l’unité et le seuil. Le sélecteur de l’interface change le modèle de comparaison. La lecture des images conserve son propre modèle. | [Comparaison](tools/slm_core_engine.py) · [Contrôles numériques](tools/slm_core_numeric.py) · [Sélection du modèle](tools/clair_model_choice.py) |
| 5. Expliquer le résultat | Le service enregistre les preuves et produit le PDF ainsi que le rapport HTML annoté. L’inspection JSON permet de retrouver les lectures, les étapes et les sources pour examiner une décision. | [Composition du rapport](tools/slm_core_compact_report.py) · [Annotations](tools/clair_annotations.py) |

**Exemple de bout en bout.** Dans Rennes B, la cote **1,10 m** figure dans une image de la page 2. Il faut d’abord l’associer au **cheminement piéton**. L’article 1 de l’arrêté du 15 janvier 2007 fixe une largeur libre de **1,40 m**, avec une réduction possible à **1,20 m** en l’absence de mur ou d’obstacle de part et d’autre. Même avec cette réduction, 1,10 m reste insuffisant. Dans Rennes A, **1,60 m** satisfait ce critère de largeur. Le verdict porte sur ce critère précis. [Article 1, 3°, dans sa version applicable au 1er juillet 2024](https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000049320039/2024-07-01)

**Comprendre un passage sans décision.** Si la cote est illisible, si son objet est ambigu ou si le corpus ne fournit aucun article applicable, la comparaison peut rester sans décision. Pour diagnostiquer ce cas, ouvrez l’inspection et vérifiez successivement la lecture de la page, le fait extrait et la source retenue. Un modèle plus grand peut améliorer la lecture ou l’interprétation. Il faut le tester sur les mêmes PDF et le même corpus pour mesurer le gain. Un article absent du corpus reste à ajouter.
