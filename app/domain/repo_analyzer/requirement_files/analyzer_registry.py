from asyncio import run
from json import load
from typing import ClassVar
from xml.etree.ElementTree import parse

from .base_analyzer import RequirementFileAnalyzer
from .cargo_lock_analyzer import CargoLockAnalyzer
from .cargo_toml_analyzer import CargoTomlAnalyzer
from .cyclonedx_sbom_analyzer import CycloneDxSbomAnalyzer
from .gemfile_analyzer import GemfileAnalyzer
from .gemfile_lock_analyzer import GemfileLockAnalyzer
from .go_analyzer import GoAnalyzer
from .package_config_analyzer import PackageConfigAnalyzer
from .package_json_analyzer import PackageJsonAnalyzer
from .package_lock_json_analyzer import PackageLockJsonAnalyzer
from .pom_xml_analyzer import PomXmlAnalyzer
from .pyproject_toml_analyzer import PyprojectTomlAnalyzer
from .requirements_txt_analyzer import RequirementsTxtAnalyzer
from .setup_cfg_analyzer import SetupCfgAnalyzer
from .setup_py_analyzer import SetupPyAnalyzer
from .spdx_sbom_analyzer import SpdxSbomAnalyzer


class AnalyzerRegistry:
    """Singleton registry that maintains and provides specific requirement file analyzers.

    This class handles the initialization and resolution of the correct analyzer
    strategy based on file names, extensions, or file content (e.g., for SBOMs).
    """

    instance: ClassVar[AnalyzerRegistry | None] = None
    analyzers: dict[str, RequirementFileAnalyzer]

    def __new__(cls) -> AnalyzerRegistry:
        """Creates or returns the singleton instance of the AnalyzerRegistry.

        Returns:
            AnalyzerRegistry: The singleton instance.
        """
        if cls.instance is None:
            cls.instance = super().__new__(cls)
            cls.instance.initialize()
        return cls.instance

    def initialize(self) -> None:
        """Initializes the dictionary of supported requirement file analyzers."""
        self.analyzers = {
            "Cargo.lock": CargoLockAnalyzer(),
            "Cargo.toml": CargoTomlAnalyzer(),
            "cyclonedx": CycloneDxSbomAnalyzer(),
            "spdx": SpdxSbomAnalyzer(),
            "Gemfile": GemfileAnalyzer(),
            "Gemfile.lock": GemfileLockAnalyzer(),
            "packages.config": PackageConfigAnalyzer(),
            "package.json": PackageJsonAnalyzer(),
            "package-lock.json": PackageLockJsonAnalyzer(),
            "pom.xml": PomXmlAnalyzer(),
            "pyproject.toml": PyprojectTomlAnalyzer(),
            "requirements.txt": RequirementsTxtAnalyzer(),
            "go.mod": GoAnalyzer(),
            "setup.cfg": SetupCfgAnalyzer(),
            "setup.py": SetupPyAnalyzer(),
        }

    def get_analyzer(
        self, filename: str, repository_path: str
    ) -> RequirementFileAnalyzer | None:
        """Retrieves the appropriate analyzer for a given filename.

        Uses exact matching first, then falls back to heuristic matching for
        common file patterns or deep content inspection for SBOM files.

        Args:
            filename (str): The name or relative path of the file to analyze.
            repository_path (str): The base path of the repository.

        Returns:
            RequirementFileAnalyzer | None: The matching analyzer instance,
                or None if no suitable analyzer is found.
        """
        file_basename = filename.split("/")[-1]

        if file_basename in self.analyzers:
            return self.analyzers[file_basename]

        file_lower = file_basename.lower()

        if "requirements" in file_lower and file_basename.endswith(".txt"):
            return self.analyzers["requirements.txt"]

        if "gemfile" in file_lower and not file_basename.endswith((".lock", ".txt")):
            return self.analyzers.get("Gemfile")

        if (
            "package" in file_lower
            and file_basename.endswith(".json")
            and "lock" not in file_lower
        ):
            return self.analyzers.get("package.json")

        if "package-lock" in file_lower and file_basename.endswith(".json"):
            return self.analyzers.get("package-lock.json")

        if self.is_sbom_file(file_basename):
            sbom_format = self.detect_sbom_format(filename, repository_path)
            if sbom_format:
                return self.analyzers.get(sbom_format)

        return None

    def is_sbom_file(self, filename: str) -> bool:
        """Determines if a filename suggests it might be a Software Bill of Materials (SBOM).

        Args:
            filename (str): The name of the file to check.

        Returns:
            bool: True if the file name matches common SBOM patterns, False otherwise.
        """
        file_lower = filename.lower()
        return (
            "sbom" in file_lower
            or "bom" in file_lower
            or "cyclonedx" in file_lower
            or "cdx" in file_lower
            or "spdx" in file_lower
        )

    def detect_sbom_format(self, filename: str, repository_path: str) -> str | None:
        """Detects the specific SBOM format (CycloneDX or SPDX) based on file extension and content.

        Args:
            filename (str): The relative path of the SBOM file.
            repository_path (str): The local path to the repository root.

        Returns:
            str | None: The detected format ('cyclonedx' or 'spdx'), or None if undetected.
        """
        filepath = f"{repository_path}/{filename}"

        try:
            if filename.endswith(".json"):
                return self.detect_json_sbom_format(filepath)
            elif filename.endswith(".xml"):
                return self.detect_xml_sbom_format(filepath)
        except Exception:
            pass

        return None

    def detect_json_sbom_format(self, filepath: str) -> str | None:
        """Parses a JSON file to determine its SBOM format.

        Args:
            filepath (str): The absolute local path to the JSON file.

        Returns:
            str | None: The detected format ('cyclonedx' or 'spdx'), or None if undetected.
        """
        try:
            with open(filepath, encoding="utf-8") as file:
                data = load(file)

                if data.get("bomFormat") == "CycloneDX":
                    return "cyclonedx"

                if data.get("spdxVersion"):
                    return "spdx"

        except Exception:
            pass

        return None

    def detect_xml_sbom_format(self, filepath: str) -> str | None:
        """Parses an XML file to determine its SBOM format based on namespaces.

        Args:
            filepath (str): The absolute local path to the XML file.

        Returns:
            str | None: The detected format ('cyclonedx' or 'spdx'), or None if undetected.
        """
        try:
            tree = parse(filepath)
            root = tree.getroot()

            namespace = ""
            if root.tag.startswith("{"):
                namespace = root.tag.split("}")[0] + "}"

            if "cyclonedx.org" in namespace.lower() and root.tag.endswith("bom"):
                return "cyclonedx"

            if "spdx.org" in namespace.lower():
                return "spdx"

        except Exception:
            pass

        return None

    def analyze(
        self,
        requirement_files: dict[str, dict[str, dict | str]],
        repository_path: str,
        filename: str,
    ) -> dict[str, dict[str, dict | str]]:
        """Synchronously analyzes a requirement file using the appropriate registered analyzer.

        Args:
            requirement_files (dict[str, dict[str, dict | str]]): The current dictionary
                of processed requirement files and their dependencies.
            repository_path (str): The local base path of the repository.
            filename (str): The relative path of the file to analyze.

        Returns:
            dict[str, dict[str, dict | str]]: The updated requirement files dictionary.
        """
        analyzer: RequirementFileAnalyzer | None = self.get_analyzer(
            filename, repository_path
        )
        if analyzer:
            return run(analyzer.analyze(requirement_files, repository_path, filename))
        return requirement_files
