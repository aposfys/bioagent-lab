"""MCP tooling for the analysis pipelines in this portfolio.

Built on the assumption that the calling agent is unreliable. The provenance layer is not
an audit trail added for convenience -- it sits on the response path, and a value without a
matching execution record never leaves the server.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
