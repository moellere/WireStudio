"""Component recommendation: rank the library against a capability query."""

from wirestudio.recommend.recommender import (
    Recommendation,
    recommend_components,
)

__all__ = ["recommend_components", "Recommendation"]
