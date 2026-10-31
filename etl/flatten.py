"""Aplatissement d'un Bundle FHIR R4 en lignes de faits cliniques.

La règle de codage est appliquée ici, une seule fois : SNOMED pour les
diagnostics, LOINC pour les mesures, RxNorm pour les médicaments. Le libellé
retenu est celui du codage choisi, afin qu'il décrive le code stocké.
"""

from collections import Counter
from dataclasses import dataclass

from app.errors import FlattenError
from app.identifiers import FHIR_ID

SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"

PREFERRED_CONDITION = (SNOMED, ICD10, "http://hl7.org/fhir/sid/icd-10")
PREFERRED_OBSERVATION = (LOINC,)
PREFERRED_MEDICATION = (RXNORM, SNOMED)

MAPPED_TYPES = {
    "Patient",
    "Encounter",
    "Condition",
    "Observation",
    "MedicationRequest",
    "MedicationStatement",
}
ALLOWED_GENDER = {"male", "female", "other", "unknown"}


@dataclass(frozen=True)
class PatientRecord:
    id: str
    family_name: str | None
    given_name: str | None
    birth_date: str | None
    gender: str | None


@dataclass(frozen=True)
class EncounterRecord:
    id: str
    status: str | None
    class_code: str | None
    class_system: str | None
    class_display: str | None
    type_code: str | None
    type_system: str | None
    type_display: str | None
    reason_code: str | None
    reason_system: str | None
    reason_display: str | None
    period_start: str | None
    period_end: str | None


@dataclass(frozen=True)
class ConditionRecord:
    id: str
    encounter_id: str | None
    clinical_status: str | None
    code: str | None
    code_system: str | None
    code_display: str | None
    onset_at: str | None
    recorded_at: str | None


@dataclass(frozen=True)
class ObservationRecord:
    id: str
    encounter_id: str | None
    parent_observation_id: str | None
    status: str | None
    code: str | None
    code_system: str | None
    code_display: str | None
    value_numeric: float | None
    value_unit: str | None
    value_text: str | None
    value_code: str | None
    value_code_system: str | None
    effective_at: str | None


@dataclass(frozen=True)
class MedicationRecord:
    id: str
    encounter_id: str | None
    status: str | None
    intent: str | None
    code: str | None
    code_system: str | None
    code_display: str | None
    dosage_text: str | None
    recorded_at: str | None


@dataclass
class FlatBundle:
    patient: PatientRecord
    encounters: list[EncounterRecord]
    conditions: list[ConditionRecord]
    observations: list[ObservationRecord]
    medications: list[MedicationRecord]
    warnings: list[str]
    skipped: int


def flatten_bundle(bundle: dict) -> FlatBundle:
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise FlattenError("Le document racine doit être un Bundle FHIR.")

    warnings: list[str] = []
    skipped = 0
    patients: list[tuple[dict, str]] = []
    others: list[tuple[dict, str, str]] = []
    ignored: Counter[str] = Counter()

    for entry in _as_list(bundle.get("entry")):
        if not isinstance(entry, dict):
            skipped += 1
            continue
        resource = entry.get("resource")
        if not isinstance(resource, dict):
            skipped += 1
            continue
        resource_type = resource.get("resourceType")
        if not isinstance(resource_type, str):
            skipped += 1
            continue
        resource_id = _extract_id(entry, resource)
        if resource_type == "Patient":
            if resource_id is None or FHIR_ID.fullmatch(resource_id) is None:
                raise FlattenError("Le patient du bundle n'a pas d'identifiant FHIR lisible.")
            patients.append((resource, resource_id))
            continue
        if resource_type not in MAPPED_TYPES:
            ignored[resource_type] += 1
            skipped += 1
            continue
        if resource_id is None or FHIR_ID.fullmatch(resource_id) is None:
            warnings.append(f"{resource_type} ignoré : identifiant absent ou illisible.")
            skipped += 1
            continue
        others.append((resource, resource_type, resource_id))

    if len(patients) != 1:
        raise FlattenError("Chaque fichier doit contenir exactement une ressource Patient.")

    patient_resource, patient_id = patients[0]
    patient = _patient_record(patient_resource, patient_id, warnings)
    encounters: list[EncounterRecord] = []
    conditions: list[ConditionRecord] = []
    observations: list[ObservationRecord] = []
    medications: list[MedicationRecord] = []

    for resource, resource_type, resource_id in others:
        subject = _subject_id(resource)
        if subject is None:
            warnings.append(f"{resource_type}/{resource_id} ignoré : sujet absent.")
            skipped += 1
            continue
        if subject != patient_id:
            warnings.append(
                f"{resource_type}/{resource_id} ignoré : le sujet n'est pas le patient du fichier."
            )
            skipped += 1
            continue
        if resource_type == "Encounter":
            encounters.append(_encounter_record(resource, resource_id, warnings))
        elif resource_type == "Condition":
            conditions.append(_condition_record(resource, resource_id, warnings))
        elif resource_type == "Observation":
            observations.extend(_observation_records(resource, resource_id, warnings))
        else:
            medications.append(_medication_record(resource, resource_id, warnings))

    if ignored:
        kinds = ", ".join(f"{name} ({count})" for name, count in sorted(ignored.items()))
        warnings.append(f"Ressources non chargées : {kinds}.")

    return FlatBundle(
        patient=patient,
        encounters=encounters,
        conditions=conditions,
        observations=observations,
        medications=medications,
        warnings=warnings,
        skipped=skipped,
    )


def pick_coding(
    concept: object, preferred_systems: tuple[str, ...]
) -> tuple[str | None, str | None, str | None]:
    """Retourne (code, système, libellé) du codage préféré, sinon le premier code."""
    if not isinstance(concept, dict):
        return None, None, None
    codings = [item for item in _as_list(concept.get("coding")) if isinstance(item, dict)]
    chosen: dict | None = None
    for system in preferred_systems:
        chosen = next(
            (
                coding
                for coding in codings
                if coding.get("system") == system and isinstance(coding.get("code"), str)
            ),
            None,
        )
        if chosen is not None:
            break
    if chosen is None:
        chosen = next((coding for coding in codings if isinstance(coding.get("code"), str)), None)
    text = concept.get("text") if isinstance(concept.get("text"), str) else None
    if chosen is None:
        return None, None, _clean(text)
    display = chosen.get("display") if isinstance(chosen.get("display"), str) else None
    system = chosen.get("system") if isinstance(chosen.get("system"), str) else None
    return _clean(chosen.get("code")), _clean(system), _clean(display) or _clean(text)


def parse_reference(reference: object) -> str | None:
    """Extrait l'id d'une référence Patient/id ou urn:uuid:id."""
    if not isinstance(reference, str):
        return None
    value = reference.strip()
    if not value:
        return None
    if value.startswith("urn:uuid:"):
        return value[len("urn:uuid:") :]
    if "/" in value:
        return value.rsplit("/", 1)[-1]
    return value


def _patient_record(resource: dict, patient_id: str, warnings: list[str]) -> PatientRecord:
    family_name, given_name = _extract_name(resource)
    raw_gender = resource.get("gender")
    gender = raw_gender.strip().lower() if isinstance(raw_gender, str) else None
    if gender not in ALLOWED_GENDER:
        if gender:
            warnings.append(f"Sexe administratif illisible pour {patient_id}.")
        gender = None
    birth_date = _birth_date(resource.get("birthDate"))
    if resource.get("birthDate") and birth_date is None:
        warnings.append(f"Date de naissance illisible pour {patient_id}.")
    return PatientRecord(
        id=patient_id,
        family_name=family_name,
        given_name=given_name,
        birth_date=birth_date,
        gender=gender,
    )


def _encounter_record(resource: dict, resource_id: str, warnings: list[str]) -> EncounterRecord:
    klass = resource.get("class") if isinstance(resource.get("class"), dict) else {}
    type_code, type_system, type_display = pick_coding(
        _first_dict(resource.get("type")), PREFERRED_CONDITION
    )
    reason_code, reason_system, reason_display = pick_coding(
        _first_dict(resource.get("reasonCode")), PREFERRED_CONDITION
    )
    period = resource.get("period") if isinstance(resource.get("period"), dict) else {}
    return EncounterRecord(
        id=resource_id,
        status=_string(resource.get("status")),
        class_code=_string(klass.get("code")),
        class_system=_string(klass.get("system")),
        class_display=_string(klass.get("display")),
        type_code=type_code,
        type_system=type_system,
        type_display=type_display,
        reason_code=reason_code,
        reason_system=reason_system,
        reason_display=reason_display,
        period_start=_instant(period.get("start"), f"Encounter/{resource_id} début", warnings),
        period_end=_instant(period.get("end"), f"Encounter/{resource_id} fin", warnings),
    )


def _condition_record(resource: dict, resource_id: str, warnings: list[str]) -> ConditionRecord:
    status_code, _, _ = pick_coding(resource.get("clinicalStatus"), ())
    code, system, display = pick_coding(resource.get("code"), PREFERRED_CONDITION)
    onset = resource.get("onsetDateTime")
    if onset is None and isinstance(resource.get("onsetPeriod"), dict):
        onset = resource["onsetPeriod"].get("start")
    return ConditionRecord(
        id=resource_id,
        encounter_id=_encounter_id(resource),
        clinical_status=status_code,
        code=code,
        code_system=system,
        code_display=display,
        onset_at=_instant(onset, f"Condition/{resource_id} onset", warnings),
        recorded_at=_instant(
            resource.get("recordedDate"), f"Condition/{resource_id} recorded", warnings
        ),
    )


def _observation_records(
    resource: dict, resource_id: str, warnings: list[str]
) -> list[ObservationRecord]:
    code, system, display = pick_coding(resource.get("code"), PREFERRED_OBSERVATION)
    encounter_id = _encounter_id(resource)
    effective = _effective(resource, resource_id, warnings)
    status = _string(resource.get("status"))
    value = _extract_value(resource)
    rows = [
        ObservationRecord(
            id=resource_id,
            encounter_id=encounter_id,
            parent_observation_id=None,
            status=status,
            code=code,
            code_system=system,
            code_display=display,
            effective_at=effective,
            **value,
        )
    ]
    used = {resource_id}
    for index, component in enumerate(_as_list(resource.get("component")), start=1):
        if not isinstance(component, dict):
            continue
        component_code, component_system, component_display = pick_coding(
            component.get("code"), PREFERRED_OBSERVATION
        )
        component_key = _component_id(resource_id, component_code, index, used)
        rows.append(
            ObservationRecord(
                id=component_key,
                encounter_id=encounter_id,
                parent_observation_id=resource_id,
                status=status,
                code=component_code,
                code_system=component_system,
                code_display=component_display,
                effective_at=effective,
                **_extract_value(component),
            )
        )
    return rows


def _medication_record(resource: dict, resource_id: str, warnings: list[str]) -> MedicationRecord:
    concept = resource.get("medicationCodeableConcept")
    if not isinstance(concept, dict):
        warnings.append(
            f"Medication/{resource_id} : médicament référencé et non codé, code laissé vide."
        )
        concept = None
    code, system, display = pick_coding(concept, PREFERRED_MEDICATION)
    dosage = None
    for instruction in _as_list(resource.get("dosageInstruction")):
        if isinstance(instruction, dict) and isinstance(instruction.get("text"), str):
            dosage = instruction["text"].strip() or None
            break
    recorded = None
    for key in ("authoredOn", "effectiveDateTime", "dateAsserted"):
        if resource.get(key) is not None:
            recorded = resource.get(key)
            break
    return MedicationRecord(
        id=resource_id,
        encounter_id=_encounter_id(resource),
        status=_string(resource.get("status")),
        intent=_string(resource.get("intent")),
        code=code,
        code_system=system,
        code_display=display,
        dosage_text=dosage,
        recorded_at=_instant(recorded, f"Medication/{resource_id}", warnings),
    )


def _extract_value(resource: dict) -> dict[str, float | str | None]:
    empty: dict[str, float | str | None] = {
        "value_numeric": None,
        "value_unit": None,
        "value_text": None,
        "value_code": None,
        "value_code_system": None,
    }
    quantity = resource.get("valueQuantity")
    if isinstance(quantity, dict):
        number = quantity.get("value")
        numeric = float(number) if isinstance(number, (int, float)) and not isinstance(number, bool) else None
        unit = quantity.get("unit") if isinstance(quantity.get("unit"), str) and quantity.get("unit") else None
        if unit is None and isinstance(quantity.get("code"), str):
            unit = quantity["code"]
        empty["value_numeric"] = numeric
        empty["value_unit"] = unit
        return empty
    if isinstance(resource.get("valueInteger"), int) and not isinstance(resource.get("valueInteger"), bool):
        empty["value_numeric"] = float(resource["valueInteger"])
        return empty
    if isinstance(resource.get("valueString"), str):
        empty["value_text"] = resource["valueString"]
        return empty
    if isinstance(resource.get("valueCodeableConcept"), dict):
        code, system, display = pick_coding(resource["valueCodeableConcept"], ())
        empty["value_code"] = code
        empty["value_code_system"] = system
        empty["value_text"] = display
    return empty


def _component_id(parent_id: str, code: str | None, index: int, used: set[str]) -> str:
    suffix = code if code else f"c{index}"
    raw = f"{parent_id}.{suffix}"
    candidate = raw if len(raw) <= 64 and FHIR_ID.fullmatch(raw) else None
    if candidate is None:
        digest = f"{index:02d}{suffix}"
        candidate = f"{parent_id[:50]}.{digest}"[:64]
    while candidate in used or FHIR_ID.fullmatch(candidate) is None:
        candidate = f"{parent_id[:40]}.c{index}"[:64]
        index += 1
    used.add(candidate)
    return candidate


def _effective(resource: dict, resource_id: str, warnings: list[str]) -> str | None:
    for key in ("effectiveDateTime", "effectiveInstant", "issued"):
        if resource.get(key) is not None:
            return _instant(resource.get(key), f"Observation/{resource_id}", warnings)
    period = resource.get("effectivePeriod")
    if isinstance(period, dict):
        return _instant(period.get("start"), f"Observation/{resource_id}", warnings)
    return None


def _encounter_id(resource: dict) -> str | None:
    encounter = resource.get("encounter")
    if not isinstance(encounter, dict):
        return None
    return parse_reference(encounter.get("reference"))


def _subject_id(resource: dict) -> str | None:
    subject = resource.get("subject")
    if not isinstance(subject, dict):
        return None
    return parse_reference(subject.get("reference"))


def _extract_id(entry: dict, resource: dict) -> str | None:
    resource_id = resource.get("id")
    if isinstance(resource_id, str) and resource_id.strip():
        return resource_id.strip()
    return parse_reference(entry.get("fullUrl"))


def _extract_name(resource: dict) -> tuple[str | None, str | None]:
    names = [item for item in _as_list(resource.get("name")) if isinstance(item, dict)]
    if not names:
        return None, None
    chosen = next((item for item in names if item.get("use") == "official"), names[0])
    family = _clean(chosen.get("family")) if isinstance(chosen.get("family"), str) else None
    given = [
        part.strip()
        for part in _as_list(chosen.get("given"))
        if isinstance(part, str) and part.strip()
    ]
    return family, " ".join(given) or None


def _birth_date(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        day = text[:10]
        if _instant_ok(day):
            return day
    return None


def _instant(value: object, label: str, warnings: list[str]) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and _instant_ok(value.strip()):
        return value.strip()
    if value != "":
        warnings.append(f"Date illisible ({label}).")
    return None


def _instant_ok(value: str) -> bool:
    if len(value) < 4 or not value[:4].isdigit():
        return False
    rest = value[4:]
    if not rest:
        return True
    if rest[0] != "-":
        return False
    # AAAA, AAAA-MM, AAAA-MM-JJ, puis une heure FHIR facultative.
    month = rest[1:]
    if len(month) >= 2 and month[:2].isdigit():
        tail = month[2:]
    else:
        return False
    if not tail:
        return True
    if tail[0] != "-":
        return False
    if len(tail) < 3 or not tail[1:3].isdigit():
        return False
    clock = tail[3:]
    if not clock:
        return True
    if not clock.startswith("T"):
        return False
    body = clock[1:]
    if body.endswith("Z"):
        body = body[:-1]
    elif len(body) >= 6 and body[-6] in "+-" and body[-3] == ":":
        body = body[:-6]
    pieces = body.split(":")
    if len(pieces) > 3:
        return False
    for piece in pieces:
        number = piece.split(".", 1)[0]
        if not number.isdigit():
            return False
    return True


def _first_dict(value: object) -> dict | None:
    for item in _as_list(value):
        if isinstance(item, dict):
            return item
    return None


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _clean(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
