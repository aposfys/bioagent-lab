"""The tools this server actually exposes.

Only backends that are genuinely present get registered. :func:`build_registry` reports what
it skipped and why, rather than registering a tool that will fail on first use -- an agent
cannot tell the difference between "this tool is broken" and "this analysis found nothing",
so the distinction is made here, at startup, where a human can see it.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from typing import Any

from bioagent.limits import ResourceLimits, run_bounded
from bioagent.registry import PermissionClass, Registry, Tool, ToolResult

TOOL_VERSION = "0.1.0"


def _rdkit_available() -> bool:
    try:
        import rdkit  # noqa: F401
    except ImportError:
        return False
    return True


def _fpsearch_binary() -> str | None:
    """Path to the `fpsearch` CLI, if it is installed."""
    return os.environ.get("FPSEARCH_BIN") or shutil.which("fpsearch")


def _fpsearch_index() -> str | None:
    """Path to a prebuilt fpsearch index, if the session was pointed at one."""
    path = os.environ.get("FPSEARCH_INDEX")
    return path if path and os.path.exists(path) else None


# --------------------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------------------


def molecule_properties(arguments: Mapping[str, Any]) -> ToolResult:
    """RDKit descriptors for one SMILES string."""
    from rdkit import Chem, RDLogger
    from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors

    RDLogger.DisableLog("rdApp.*")
    smiles = arguments["smiles"]
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        # An unparseable molecule is a failure, not an empty result set. Marking it
        # incomplete is what stops it being reported as "no properties found".
        return ToolResult(
            payload={"error": f"RDKit could not parse {smiles!r}", "smiles": smiles},
            exit_status=1,
            complete=False,
        )
    return ToolResult(
        payload={
            "smiles": smiles,
            "canonical_smiles": Chem.MolToSmiles(mol),
            "molecular_weight": round(Descriptors.MolWt(mol), 3),
            "clogp": round(Crippen.MolLogP(mol), 3),
            "tpsa": round(rdMolDescriptors.CalcTPSA(mol), 3),
            "h_bond_donors": rdMolDescriptors.CalcNumHBD(mol),
            "h_bond_acceptors": rdMolDescriptors.CalcNumHBA(mol),
            "rotatable_bonds": rdMolDescriptors.CalcNumRotatableBonds(mol),
            "rings": rdMolDescriptors.CalcNumRings(mol),
            "heavy_atoms": mol.GetNumHeavyAtoms(),
        }
    )


def fingerprint(arguments: Mapping[str, Any]) -> ToolResult:
    """ECFP fingerprint of one SMILES string, as hex."""
    from rdkit import Chem, DataStructs, RDLogger
    from rdkit.Chem import rdFingerprintGenerator

    RDLogger.DisableLog("rdApp.*")
    smiles = arguments["smiles"]
    n_bits = int(arguments.get("n_bits", 2048))
    radius = int(arguments.get("radius", 2))

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return ToolResult(
            payload={"error": f"RDKit could not parse {smiles!r}", "smiles": smiles},
            exit_status=1,
            complete=False,
        )
    generator = rdFingerprintGenerator.GetMorganGenerator(radius=radius, fpSize=n_bits)
    bitvect = generator.GetFingerprint(mol)
    if bitvect.GetNumOnBits() == 0:
        return ToolResult(
            payload={"error": "fingerprint has no bits set; similarity is undefined"},
            exit_status=1,
            complete=False,
        )
    return ToolResult(
        payload={
            "smiles": smiles,
            "n_bits": n_bits,
            "radius": radius,
            "on_bits": bitvect.GetNumOnBits(),
            "hex": DataStructs.BitVectToBinaryText(bitvect).hex(),
        }
    )


def similarity_search(arguments: Mapping[str, Any]) -> ToolResult:
    """Top-k Tanimoto neighbours from a prebuilt fpsearch index.

    The hit list and the pruning statistics both come out of the subprocess. Nothing is
    recomputed here, so what the agent can report is exactly what the engine produced.
    """
    binary = _fpsearch_binary()
    index = _fpsearch_index()
    if binary is None or index is None:
        return ToolResult(
            payload={"error": "fpsearch binary or index is not configured"},
            exit_status=1,
            complete=False,
        )

    query_hex = arguments["query_hex"]
    threshold = float(arguments.get("threshold", 0.7))
    top_k = int(arguments.get("top_k", 10))

    result = run_bounded(
        [
            binary,
            "query",
            index,
            query_hex,
            "--threshold",
            str(threshold),
            "--top-k",
            str(top_k),
        ],
        limits=ResourceLimits(wall_clock_seconds=60.0),
    )
    if not result.complete:
        return ToolResult(
            payload={
                "error": result.stderr.strip() or "fpsearch failed",
                "exit": result.exit_status,
            },
            exit_status=result.exit_status,
            complete=False,
        )

    hits = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        identifier, score = line.split("\t")
        hits.append({"id": int(identifier), "tanimoto": float(score)})

    return ToolResult(
        payload={
            "threshold": threshold,
            "top_k": top_k,
            "hits": hits,
            # The engine prints its pruning statistics to stderr. Carried through verbatim
            # so a reported query time can be checked against what actually ran.
            "engine_report": result.stderr.strip(),
        }
    )


# --------------------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------------------

_SMILES_PROPERTY = {"type": "string", "description": "SMILES string of the molecule"}


def build_registry(
    log=None, enabled_permissions: set[PermissionClass] | None = None
) -> tuple[Registry, list[str]]:
    """Register every tool whose backend is present.

    Returns the registry and a list of human-readable notes about what was skipped.
    """
    registry = Registry(log=log, enabled_permissions=enabled_permissions)
    skipped: list[str] = []

    if _rdkit_available():
        registry.register(
            Tool(
                name="molecule_properties",
                version=TOOL_VERSION,
                description="Compute RDKit descriptors for a SMILES string.",
                input_schema={
                    "type": "object",
                    "properties": {"smiles": _SMILES_PROPERTY},
                    "required": ["smiles"],
                },
                handler=molecule_properties,
                permission=PermissionClass.READ_ONLY,
            )
        )
        registry.register(
            Tool(
                name="fingerprint",
                version=TOOL_VERSION,
                description="Compute an ECFP fingerprint for a SMILES string, as hex.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "smiles": _SMILES_PROPERTY,
                        "n_bits": {"type": "integer", "minimum": 64, "maximum": 8192},
                        "radius": {"type": "integer", "minimum": 1, "maximum": 4},
                    },
                    "required": ["smiles"],
                },
                handler=fingerprint,
                permission=PermissionClass.READ_ONLY,
            )
        )
    else:
        skipped.append("molecule_properties, fingerprint: RDKit is not installed")

    if _fpsearch_binary() and _fpsearch_index():
        registry.register(
            Tool(
                name="similarity_search",
                version=TOOL_VERSION,
                description=(
                    "Top-k Tanimoto neighbours from the configured fpsearch index. "
                    "Returns the engine's own pruning report alongside the hits."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query_hex": {"type": "string", "description": "Fingerprint as hex"},
                        "threshold": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 1000},
                    },
                    "required": ["query_hex"],
                },
                handler=similarity_search,
                permission=PermissionClass.READ_ONLY,
                limits=ResourceLimits(wall_clock_seconds=60.0),
            )
        )
    else:
        missing = []
        if not _fpsearch_binary():
            missing.append("FPSEARCH_BIN (or fpsearch on PATH)")
        if not _fpsearch_index():
            missing.append("FPSEARCH_INDEX")
        skipped.append(f"similarity_search: {' and '.join(missing)} not set")

    return registry, skipped
