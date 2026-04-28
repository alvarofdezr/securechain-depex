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
        return VersionFilter.VERSION_RANGE_MAP.get(node_type, (Version, VersionRange))

    @staticmethod
    def filter_versions(node_type: str, versions: list[dict[str, Any]], constraints: str) -> list[dict[str, Any]]:
        if not constraints or constraints == "any":
            return versions

        # FIX GO: En Go, "v1.2.3" implica Minimum Version Selection (>= v1.2.3)
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
            # Si univers no puede parsear la versión (ej. pseudo-versiones de Go),
            # devolvemos todas para que el SMT decida y no provocar un UNSAT artificial.
            return versions
        return filtered_versions
