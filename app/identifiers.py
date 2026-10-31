"""Identifiants FHIR utilisés comme clés des données ingérées."""

import re

# Identifiant FHIR R4 : lettres, chiffres, point, tiret, 64 caractères maximum.
FHIR_ID = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")


class InvalidIdentifier(ValueError):
    """La chaîne n'est pas un identifiant FHIR."""


def check_resource_id(value: str) -> str:
    if not isinstance(value, str) or FHIR_ID.fullmatch(value) is None:
        raise InvalidIdentifier(value)
    return value
