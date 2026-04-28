import re
from pathlib import Path
from typing import Any

from app.domain.repo_analyzer.requirement_files.base_analyzer import (
    RequirementFileAnalyzer,
)
from app.schemas.enums.manager import Manager


class GoAnalyzer(RequirementFileAnalyzer):
    """
    Analyzer for Go module manifests (go.mod).

    Extracts direct and indirect module dependencies declared in go.mod files,
    along with module-level metadata such as the Go toolchain version, the
    root module path, and any replace directives. go.sum is intentionally not
    supported here: it is a checksum database used for integrity verification
    and does not carry dependency graph information.
    """

    def __init__(self) -> None:
        super().__init__(manager=Manager.go.value)

    def parse_file(self, repository_path: str, filename: str) -> dict[str, str]:
        """
        Read a go.mod file from disk and return a flat mapping of module path
        to version string.

        This method fulfils the abstract contract defined by
        RequirementFileAnalyzer. Only go.mod is processed; any other filename
        returns an empty dict so the registry can safely call this method
        without prior filename validation.

        Args:
            repository_path: Absolute path to the root of the repository.
            filename: Name of the manifest file to parse (expected: 'go.mod').

        Returns:
            A dictionary mapping each required module path to its declared
            version string (e.g. {'github.com/gin-gonic/gin': 'v1.9.0'}).
            Returns an empty dict on any I/O or parse failure.
        """
        if filename != "go.mod":
            return {}

        file_path = Path(repository_path) / filename
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return {}

        return self._extract_packages_from_mod(content)

    async def analyze(
        self,
        requirement_files: dict[str, dict[str, Any]],
        repository_path: str,
        requirement_file_name: str,
    ) -> dict[str, dict[str, Any]]:
        """
        Perform a full analysis of go.mod, enriching the base extraction with
        Go-specific module metadata.

        Delegates the core package extraction to the parent class implementation
        and then, for go.mod files, augments the result with a 'metadata' key
        containing:
          - go_version:   The minimum Go toolchain version declared via the
                          'go' directive (e.g. '1.21').
          - module_name:  The canonical module path declared via the 'module'
                          directive (e.g. 'github.com/example/myapp').
          - replaces:     A list of replace directives, each describing a
                          module path substitution (old_path → new_path/version).

        Metadata extraction failures are silently swallowed to avoid
        interrupting the broader analysis pipeline.

        Args:
            requirement_files: Accumulated analysis results from prior files.
            repository_path:   Absolute path to the repository root.
            requirement_file_name: Manifest filename being processed.

        Returns:
            The updated requirement_files dictionary with the go.mod entry
            populated, including the 'metadata' sub-key when applicable.
        """
        requirement_files = await super().analyze(
            requirement_files, repository_path, requirement_file_name
        )

        if requirement_file_name == "go.mod":
            try:
                file_path = Path(repository_path) / requirement_file_name
                content = file_path.read_text(encoding="utf-8")

                metadata: dict[str, Any] = {}

                go_match = re.search(
                    r"^\s*go\s+(\d+\.\d+(?:\.\d+)?)", content, re.MULTILINE
                )
                if go_match:
                    metadata["go_version"] = go_match.group(1)

                mod_match = re.search(r"^\s*module\s+(\S+)", content, re.MULTILINE)
                if mod_match:
                    metadata["module_name"] = mod_match.group(1)

                replaces: list[dict[str, str | None]] = []
                replace_pattern = (
                    r"^\s*replace\s+(\S+)(?:\s+(\S+))?\s+=>\s+(\S+)(?:\s+(\S+))?"
                )
                for match in re.finditer(replace_pattern, content, re.MULTILINE):
                    replaces.append(
                        {
                            "old_path": match.group(1),
                            "new_path": match.group(3),
                            "new_version": match.group(4),
                        }
                    )
                if replaces:
                    metadata["replaces"] = replaces

                requirement_files[requirement_file_name]["metadata"] = metadata

            except Exception:
                pass

        return requirement_files

    def _extract_packages_from_mod(self, content: str) -> dict[str, str]:
        """
        Parse the require directives in a go.mod file and return a mapping of
        module path to version string.

        Handles both syntactic forms allowed by the Go module specification:
          - Single-line form:  require github.com/foo/bar v1.2.3
          - Block form:        require ( github.com/foo/bar v1.2.3 )

        Inline comments (// indirect and similar annotations) are stripped
        before extraction so they do not contaminate the version string.
        Pseudo-versions (e.g. v0.0.0-20210101000000-abcdef123456) are treated
        as opaque strings and stored as-is, which is the correct behaviour
        given that the Go toolchain itself manages their resolution.

        Args:
            content: Raw text content of a go.mod file.

        Returns:
            A dictionary mapping module paths to their declared version strings.
        """
        dependencies: dict[str, str] = {}

        pattern = r"^\s*(?:require\s+)?([a-zA-Z0-9\.\-\/]+)\s+(v[0-9\.]+[\-[a-zA-Z0-9\.]*]*)"

        lines = content.split('\n')
        for line in lines:
            line = line.strip()

            if not line or line.startswith(('module', 'go', ')', '//')):
                continue

            if line == "require (":
                continue

            match = re.search(pattern, line)
            if match:
                pkg_name = match.group(1)
                pkg_version = match.group(2)

                if "." in pkg_name:
                    dependencies[pkg_name] = pkg_version
                    print(f"DEBUG: Paquete añadido: {pkg_name}")

        print(f"DEBUG: Total dependencias finales: {len(dependencies)}")
        return dependencies


def create_go_analyzer() -> GoAnalyzer:
    """
    Factory function for GoAnalyzer.

    Provided for consistency with the instantiation pattern used by other
    analyzers in the codebase and to facilitate dependency injection in tests.
    """
    return GoAnalyzer()
