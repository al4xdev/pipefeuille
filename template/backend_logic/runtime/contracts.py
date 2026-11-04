"""The use cases this family answers. Each type lives in the package that owns it."""

lazy from .application.contracts import PrepareResources

# One member today; the union is where a second lifetime-owned resource would be added.
type RuntimeRequest = PrepareResources
