from typing import Any, Dict, List, Optional
from pathlib import Path


FieldProvenance = Dict[str, Any]


def _field(value: Any, source: str, confidence: str, evidence: Optional[str] = None) -> FieldProvenance:
    return {
        "value": value,
        "source": source,
        "confidence": confidence,
        "evidence": evidence or source,
    }


class MetadataResolver:
    def __init__(self):
        self.fields: Dict[str, FieldProvenance] = {}
        self.conflicts: List[Dict[str, Any]] = []

    def set(self, field: str, value: Any, source: str, confidence: str, evidence: Optional[str] = None, overwrite: bool = False) -> None:
        existing = self.fields.get(field)
        if existing and not overwrite:
            if existing.get("value") != value:
                self.conflicts.append({
                    "field": field,
                    "existing_value": existing.get("value"),
                    "existing_source": existing.get("source"),
                    "new_value": value,
                    "new_source": source,
                })
            return
        self.fields[field] = _field(value, source, confidence, evidence)

    def get(self, field: str) -> Optional[Any]:
        prov = self.fields.get(field)
        return prov.get("value") if prov else None

    def get_provenance(self, field: str) -> Optional[FieldProvenance]:
        return self.fields.get(field)

    def to_flat(self) -> Dict[str, Any]:
        flat: Dict[str, Any] = {}
        for field, prov in self.fields.items():
            flat[field] = prov["value"]
            flat[f"{field}_source"] = prov["source"]
            flat[f"{field}_confidence"] = prov["confidence"]
            flat[f"{field}_evidence"] = prov.get("evidence")
        return flat
