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
