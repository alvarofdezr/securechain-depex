from typing import Any, ClassVar

from univers.version_range import (
    GemVersionRange,
    MavenVersionRange,
    NpmVersionRange,
    NugetVersionRange,
    PypiVersionRange,
    VersionRange,
)
from univers.versions import (
    MavenVersion,
    NugetVersion,
    PypiVersion,
    RubygemsVersion,
    SemverVersion,
    Version,
)


class VersionFilter:
    """Version constraint filtering using ecosystem-specific version semantics.
    
    Maps package manager node types to their respective version and version range
    implementations from the univers library. Handles constraint parsing and version
    matching across multiple language ecosystems with distinct versioning schemes.
    
    Supported ecosystems:
    - PyPI (Python): PEP 440 versioning
    - NPM (JavaScript): Semantic Versioning (SemVer)
    - Cargo (Rust): Semantic Versioning (SemVer)
    - Maven (Java): Maven versioning scheme
    - RubyGems (Ruby): RubyGems versioning scheme
    - NuGet (.NET): NuGet versioning scheme
    - Go: Semantic Versioning with Minimum Version Selection (MVS)
    
    Attributes:
        VERSION_RANGE_MAP: Class-level mapping of node types to their version classes
            and version range classes from the univers library.
    """

    VERSION_RANGE_MAP: ClassVar[dict[str, tuple[type[Version], type[VersionRange]]]] = {
        "PyPIPackage": (PypiVersion, PypiVersionRange),
        "NPMPackage": (SemverVersion, NpmVersionRange),
        "CargoPackage": (SemverVersion, NpmVersionRange),
        "MavenPackage": (MavenVersion, MavenVersionRange),
        "RubyGemsPackage": (RubygemsVersion, GemVersionRange),
        "NuGetPackage": (NugetVersion, NugetVersionRange),
        "GoPackage": (SemverVersion, NpmVersionRange),
    }

    @staticmethod
    def get_version_range_type(node_type: str) -> tuple[type[Version], type[VersionRange]]:
        """Retrieves the version and version range classes for a given package manager.
        
        Maps a node type to its corresponding univers Version and VersionRange classes,
        enabling ecosystem-specific constraint parsing and version matching.
        
        Args:
            node_type: The package manager node type identifier
                (e.g., 'PyPIPackage', 'NPMPackage', 'MavenPackage').
        
        Returns:
            A tuple of (Version class, VersionRange class). Falls back to generic
            univers classes if node_type is not recognized.
        """
        return VersionFilter.VERSION_RANGE_MAP.get(node_type, (Version, VersionRange))

    @staticmethod
    def filter_versions(node_type: str, versions: list[dict[str, Any]], constraints: str) -> list[dict[str, Any]]:
        """Filters a list of versions against ecosystem-specific constraints.
        
        Parses version constraint specifications using the appropriate constraint
        dialect for the given package manager, then evaluates each version against
        the constraint using univers library implementations.
        
        Special handling for Go packages: version strings without explicit operators
        are interpreted as Minimum Version Selection (MVS) constraints (>= version),
        per Go module semantics.
        
        Graceful fallback: If constraint parsing fails (e.g., pseudo-versions,
        non-standard formats), returns all versions to allow downstream analysis
        (e.g., SMT solver) to make constraint satisfaction decisions rather than
        prematurely filtering versions.
        
        Args:
            node_type: The package manager node type identifier
                (e.g., 'PyPIPackage', 'NPMPackage', 'GoPackage').
            versions: List of version dictionaries with required 'name' key
                and optional metadata (serial_number, impact metrics, etc.).
            constraints: Version constraint specification string
                (e.g., '>=1.0.0', '^2.1.0', '~3.0'). If empty or 'any', returns all versions.
        
        Returns:
            List of version dictionaries matching the constraint specification.
            If constraint parsing fails, returns the original versions list.
        
        Raises:
            No exceptions raised. Parsing failures are caught and result in
            returning all versions for downstream processing.
        """
        if not constraints or constraints == "any":
            return versions

        if node_type == "GoPackage":
            if not any(op in constraints for op in (">", "<", "=", "~", "^")):
                constraints = f">={constraints}"

        version_type, version_range_type = VersionFilter.get_version_range_type(node_type)
        filtered_versions: list[dict[str, Any]] = []
        try:
            univers_range = version_range_type.from_native(constraints)
            for version in versions:
                name = version.get("name")
                if not name:
                    continue
                univers_version = version_type(name)
                if univers_version in univers_range:
                    filtered_versions.append(version)
        except Exception as _:
            return versions
        return filtered_versions
