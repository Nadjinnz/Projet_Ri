"""Erreurs métier du dossier clinique."""


class ClinicalRecordImmutabilityError(Exception):
    """Tentative de modification ou de suppression d'un enregistrement figé."""


class PatientNotFound(Exception):
    """Le patient demandé n'est pas dans la base."""


class ReferenceNotFound(Exception):
    """La cible d'un commentaire n'appartient pas au dossier."""


class FlattenError(ValueError):
    """Le bundle FHIR ne peut pas être aplati."""
