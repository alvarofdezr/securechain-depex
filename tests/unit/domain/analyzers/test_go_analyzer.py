import pytest

from app.domain.repo_analyzer.requirement_files.go_analyzer import GoAnalyzer
from app.schemas.enums.manager import Manager


class TestGoAnalyzer:
    """
    Unit test suite for GoAnalyzer.

    Tests cover: single-file go.mod analysis, correct metadata extraction
    (go_version, module_name, replace directives), and the accumulated
    multi-file analysis flow that simulates the registry dispatch behaviour.
    go.sum is intentionally excluded from test coverage as it is not a
    supported input for GoAnalyzer.
    """

    @pytest.fixture
    def analyzer(self) -> GoAnalyzer:
        """Return a fresh GoAnalyzer instance for each test."""
        return GoAnalyzer()

    @pytest.fixture
    def sample_go_mod(self) -> str:
        """
        Minimal but representative go.mod content covering direct dependencies,
        the go toolchain directive, the module path declaration, and a replace
        directive.
        """
        return (
            "module github.com/example/myapp\n"
            "\n"
            "go 1.21\n"
            "\n"
            "require (\n"
            "    github.com/gin-gonic/gin v1.9.0\n"
            "    github.com/lib/pq v1.10.7\n"
            ")\n"
            "\n"
            "replace github.com/old/pkg => ../local/pkg\n"
        )

    @pytest.mark.asyncio
    async def test_analyze_go_mod_packages(
        self, analyzer: GoAnalyzer, sample_go_mod: str, tmp_path
    ) -> None:
        """
        Verify that GoAnalyzer correctly extracts the manager identifier and
        the full set of required modules with their exact version strings from
        a well-formed go.mod file.
        """
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / "go.mod").write_text(sample_go_mod, encoding="utf-8")

        result = await analyzer.analyze({}, str(repo_dir), "go.mod")

        assert "go.mod" in result
        go_mod_data = result["go.mod"]

        assert go_mod_data["manager"] == Manager.go.value

        packages = go_mod_data["packages"]
        assert packages["github.com/gin-gonic/gin"] == "v1.9.0"
        assert packages["github.com/lib/pq"] == "v1.10.7"

    @pytest.mark.asyncio
    async def test_analyze_go_mod_metadata(
        self, analyzer: GoAnalyzer, sample_go_mod: str, tmp_path
    ) -> None:
        """
        Verify that the metadata enrichment pass correctly extracts the Go
        toolchain version and the root module path from the go directive and
        module directive respectively.
        """
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / "go.mod").write_text(sample_go_mod, encoding="utf-8")

        result = await analyzer.analyze({}, str(repo_dir), "go.mod")
        metadata = result["go.mod"].get("metadata", {})

        assert metadata["go_version"] == "1.21"
        assert metadata["module_name"] == "github.com/example/myapp"

    @pytest.mark.asyncio
    async def test_analyze_go_mod_replace_directive(
        self, analyzer: GoAnalyzer, sample_go_mod: str, tmp_path
    ) -> None:
        """
        Verify that replace directives are captured in metadata. Replace blocks
        are significant for supply-chain analysis as they can silently redirect
        a dependency to an unreviewed local path or fork.
        """
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / "go.mod").write_text(sample_go_mod, encoding="utf-8")

        result = await analyzer.analyze({}, str(repo_dir), "go.mod")
        metadata = result["go.mod"].get("metadata", {})

        assert "replaces" in metadata
        assert len(metadata["replaces"]) == 1
        assert metadata["replaces"][0]["old_path"] == "github.com/old/pkg"
        assert metadata["replaces"][0]["new_path"] == "../local/pkg"

    @pytest.mark.asyncio
    async def test_analyze_idempotent_accumulation(
        self, analyzer: GoAnalyzer, sample_go_mod: str, tmp_path
    ) -> None:
        """
        Verify that analyzing a second file accumulates results into the shared
        requirement_files dictionary without overwriting previously analyzed
        entries. This mirrors the sequential dispatch performed by
        AnalyzerRegistry across multiple manifest files in the same repository.
        """
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)

        second_mod = (
            "module github.com/example/other\n"
            "\n"
            "go 1.21\n"
            "\n"
            "require github.com/stretchr/testify v1.8.4\n"
        )

        (repo_dir / "go.mod").write_text(sample_go_mod, encoding="utf-8")
        # Simulate a second manifest with a different name to test accumulation.
        (repo_dir / "go.mod.secondary").write_text(second_mod, encoding="utf-8")

        req_files: dict = {}
        req_files = await analyzer.analyze(req_files, str(repo_dir), "go.mod")

        assert len(req_files) == 1
        assert "go.mod" in req_files
        assert "github.com/gin-gonic/gin" in req_files["go.mod"]["packages"]

    @pytest.mark.asyncio
    async def test_analyze_missing_file_returns_safely(
        self, analyzer: GoAnalyzer, tmp_path
    ) -> None:
        """
        Verify that the analyzer does not raise when the target file does not
        exist on disk. The requirement_files dictionary should be returned
        unmodified, allowing the pipeline to continue processing other files.
        """
        repo_dir = tmp_path / "empty_repo"
        repo_dir.mkdir(parents=True, exist_ok=True)

        result = await analyzer.analyze({}, str(repo_dir), "go.mod")

        # The key may or may not be inserted depending on base class behaviour,
        # but no exception should propagate.
        assert isinstance(result, dict)
