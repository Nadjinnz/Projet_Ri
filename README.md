# Dossier clinique FHIR

Pipeline ETL et API REST pour des bundles HL7 FHIR R4 (un fichier JSON par patient, format Synthea). Les faits cliniques deviennent des tables. L'API les lit. Elle ne les réécrit pas.

## Choix : ETL

FHIR R4 est un format d'échange. Un Bundle est une liste polymorphe : `CodeableConcept.coding` contient souvent plusieurs codes, `value[x]` est un choix de type, et les liens sont des chaînes (`Patient/id` ou `urn:uuid:`). Ce document n'est pas un modèle qu'on interroge tel quel.

Le pipeline **extrait** le JSON, **transforme** chaque fait en colonnes (code, système, libellé, date, valeur, unité), puis **charge** des lignes. La règle de codage est unique et testée : SNOMED CT pour un diagnostic, LOINC pour une mesure, RxNorm pour un médicament. Le libellé retenu est celui du codage choisi, pas celui d'un code local voisin.

Un ELT qui stockerait le Bundle et le réinterpréterait en SQL à chaque lecture laisserait cette règle dans les requêtes. Deux lectures pourraient alors afficher deux libellés pour le même diagnostic, et une évolution du SQL changerait un dossier déjà versé. Ce mode convient à l'exploration d'un lac de données. Il ne convient pas à un fait clinique qui doit rester stable une fois versé au dossier.

Le compromis est assumé : un nouveau type de ressource FHIR demande une évolution du pipeline. C'est le contrat de l'API. La trace vers le fichier source est le journal `ingestion_runs` (nom du fichier, SHA-256, horodatage, volumes insérés). Rejouer un fichier n'écrase rien : une clé FHIR déjà présente est ignorée.

## Modèle

| Ressource FHIR | Table | Clé |
| --- | --- | --- |
| Patient | `patients` | id FHIR, ou UUID émis par l'API |
| Encounter | `encounters` | id FHIR |
| Condition | `conditions` | id FHIR |
| Observation, y compris chaque `component` | `observations` | id FHIR ; une composante reçoit `{id du panneau}.{code}` |
| MedicationRequest, MedicationStatement | `medications` | id FHIR |
| Commentaire d'API | `comments` | UUID émis par le serveur |
| Journal de chargement | `ingestion_runs` | entier technique |

Le DDL est dans [`sql/schema.sql`](sql/schema.sql). Les modèles SQLAlchemy de [`app/models.py`](app/models.py) lisent ces tables.

Un commentaire pointe vers exactement une cible (le patient, une rencontre, un diagnostic, une observation ou un médicament) par clé étrangère. Il enregistre l'auteur, le rôle `clinician`, l'horodatage UTC et le texte. Les triggers SQLite interdisent `UPDATE` et `DELETE` sur toutes ces tables. La session ORM refuse la même opération avant même d'émettre le SQL.

`POST /patients` crée une identité administrative vide (`source = api`). Ce n'est pas une correction de fait clinique.

## Lancer

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m etl.run
uvicorn app.main:app --reload
```

La documentation interactive est sur [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). Authorize demande `X-Role` et `X-Actor-Id`.

```powershell
curl.exe -H "X-Role: clinician" -H "X-Actor-Id: dr-bernard" "http://127.0.0.1:8000/patients/anne-dupont/observations?code=8480-6"
```

Les deux bundles de `data/fhir/` sont synthétiques, au format d'un export Synthea réduit. Pour un export réel, déposer un JSON par patient dans ce dossier et relancer `python -m etl.run`.

```powershell
pytest
```

## Accès

Les en-têtes simulent une session. En production, le rôle viendrait d'un jeton OIDC de l'hôpital, pas d'un en-tête choisi par le client.

| Route | clinician | patient | data_manager |
| --- | --- | --- | --- |
| `GET /patients` | oui | non | oui |
| `GET /patients/{id}` et les lectures du dossier | oui | son seul dossier | oui |
| `POST /patients/{id}/comments` | oui | non | non |
| `POST /patients` | non | non | oui |

Un patient qui demande un autre identifiant reçoit **403**, que ce dossier existe ou non. Un code d'observation inconnu dans un dossier qui existe reçoit **200** et une liste vide. Un identifiant mal formé reçoit **400**. Une méthode `PUT`, `PATCH` ou `DELETE` reçoit **405**.

Jeu d'essai après l'ETL : Anne Dupont (`anne-dupont`, pression systolique LOINC `8480-6`, 128 mmHg) et Paul Martin (`paul-martin`).
