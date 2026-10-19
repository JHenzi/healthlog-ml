"""Localised HAE vocabularies for symptoms and medications -> canonical slugs.

Health Auto Export ships symptom names, symptom severities and medication dose
statuses in the phone's language ("Kopfschmerzen", "Leicht", "Eingenommen" on a
German device; see ``tests/fixtures/hae_*_de.json``). Like ``workout_types.py``,
the raw value is always stored and a canonical slug sits next to it, so the
same symptom stays one series across a phone language switch. An unrecognised
value maps to None and is never rejected (ARCHITECTURE.md §4.0); extending a
map and running ``healthlog rederive-symptoms`` / ``rederive-medications``
fills the slug in for rows already stored.

Pure functions, no DB.
"""

from __future__ import annotations

from .workout_types import _normalize_key, slugify

# Apple Health symptom types. English keys are Apple's display names; German
# keys are listed only where an actual HAE export confirmed the spelling, since
# HAE's strings don't always match what the app shows (see workout_types.py).
BUILTIN_SYMPTOMS: dict[str, str] = {
    "abdominal cramps": "abdominal_cramps",
    "acne": "acne",
    "appetite changes": "appetite_changes",
    "bladder incontinence": "bladder_incontinence",
    "bloating": "bloating",
    "breast pain": "breast_pain",
    "chest tightness or pain": "chest_tightness_or_pain",
    "chills": "chills",
    "constipation": "constipation",
    "coughing": "coughing",
    "diarrhea": "diarrhea",
    "dizziness": "dizziness",
    "dry skin": "dry_skin",
    "fainting": "fainting",
    "fatigue": "fatigue",
    "fever": "fever",
    "generalized body ache": "generalized_body_ache",
    "hair loss": "hair_loss",
    "headache": "headache",
    "heartburn": "heartburn",
    "hot flashes": "hot_flashes",
    "lower back pain": "lower_back_pain",
    "loss of smell": "loss_of_smell",
    "loss of taste": "loss_of_taste",
    "memory lapse": "memory_lapse",
    "mood changes": "mood_changes",
    "nausea": "nausea",
    "night sweats": "night_sweats",
    "pelvic pain": "pelvic_pain",
    "rapid, pounding, or fluttering heartbeat": "rapid_pounding_or_fluttering_heartbeat",
    "runny nose": "runny_nose",
    "shortness of breath": "shortness_of_breath",
    "sinus congestion": "sinus_congestion",
    "skipped heartbeat": "skipped_heartbeat",
    "sleep changes": "sleep_changes",
    "sore throat": "sore_throat",
    "vaginal dryness": "vaginal_dryness",
    "vomiting": "vomiting",
    "wheezing": "wheezing",
    # German, confirmed by a real HAE export.
    "kopfschmerzen": "headache",
    "rückenschmerzen": "lower_back_pain",
    "husten": "coughing",
}

# Symptom severity. "present" is the yes/no answer some symptom types use.
BUILTIN_SEVERITIES: dict[str, str] = {
    "not present": "not_present",
    "nicht vorhanden": "not_present",
    "present": "present",
    "vorhanden": "present",
    "mild": "mild",
    "leicht": "mild",
    "moderate": "moderate",
    "mäßig": "moderate",
    "severe": "severe",
    "schwer": "severe",
}

# Medication dose status (Apple Health Medications, iOS 26).
BUILTIN_MEDICATION_STATUSES: dict[str, str] = {
    "taken": "taken",
    "eingenommen": "taken",
    "skipped": "skipped",
    "übersprungen": "skipped",
    "snoozed": "snoozed",
    "not logged": "not_logged",
    "nicht angemeldet": "not_logged",
}


def _lookup(value: object, table: dict[str, str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    mapped = table.get(_normalize_key(value))
    return slugify(mapped) if mapped else None


def canonical_symptom(name: object) -> str | None:
    """Localised symptom name -> canonical slug, or None if unrecognised."""
    return _lookup(name, BUILTIN_SYMPTOMS)


def canonical_severity(severity: object) -> str | None:
    """Localised symptom severity -> ``not_present|present|mild|moderate|severe`` or None."""
    return _lookup(severity, BUILTIN_SEVERITIES)


def canonical_medication_status(status: object) -> str | None:
    """Localised dose status -> ``taken|skipped|snoozed|not_logged`` or None."""
    return _lookup(status, BUILTIN_MEDICATION_STATUSES)
