from typing import Protocol, Dict, Any, Optional


class DatasetProvider(Protocol):
    """Interface for providing dataset contracts to the analysis engine.

    Module_2 provides the concrete implementation.
    Module_3 depends only on this protocol.
    """

    def get_dataset(self, dataset_id: int) -> Dict[str, Any]:
        """Return dataset contract dict for analysis.

        Must include at minimum:
        - dataset_id
        - dataset_name
        - dataset_type
        - file_path
        - bounds (west, south, east, north)
        - crs
        - files (list of file info dicts)
        - ready_for_analysis (bool)
        - errors (list)
        """
        ...
