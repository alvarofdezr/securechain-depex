from glob import glob
from os import makedirs
from os.path import exists, isdir, join
from shutil import rmtree

from aiofiles import open

from app.constants import FileTypes
from app.http_session import HTTPSessionManager

from .requirement_files import AnalyzerRegistry


class RepositoryAnalyzer:
    """Analyzes a repository to extract and parse its requirement files.

    This class handles the downloading of repository contents from GitHub
    and delegating the parsing of specific requirement files to registered
    analyzers.
    """

    def __init__(self, http_session: HTTPSessionManager):
        """Initializes the RepositoryAnalyzer.

        Args:
            http_session (HTTPSessionManager): The HTTP session manager to use for requests.
        """
        self.registry = AnalyzerRegistry()
        self.http_session = http_session

    async def analyze(self, owner: str, name: str) -> dict[str, dict[str, dict | str]]:
        """Analyzes a repository and extracts its dependencies.

        Args:
            owner (str): The owner of the repository.
            name (str): The name of the repository.

        Returns:
            dict[str, dict[str, dict | str]]: A dictionary mapping requirement
                file paths to their parsed dependency information.
        """
        requirement_files: dict[str, dict[str, dict | str]] = {}
        repository_path = await self.download_repository(owner, name)

        try:
            requirement_file_names = self.get_req_files_names(repository_path)

            for requirement_file_name in requirement_file_names:
                analyzer = self.registry.get_analyzer(requirement_file_name, repository_path)
                if analyzer:
                    requirement_files = await analyzer.analyze(
                        requirement_files, repository_path, requirement_file_name
                    )
        finally:
            if exists(repository_path):
                rmtree(repository_path)

        return requirement_files

    async def download_repository(self, owner: str, name: str) -> str:
        """Downloads the relevant files from a repository.

        Args:
            owner (str): The owner of the repository.
            name (str): The name of the repository.

        Returns:
            str: The local filesystem path where the repository files were downloaded.
        """
        repository_path = f"repositories/{owner}/{name}"
        if exists(repository_path):
            rmtree(repository_path)
        makedirs(repository_path)

        session = await self.http_session.get_session()
        await self.download_tree_contents(session, owner, name, repository_path)
        return repository_path

    async def download_tree_contents(
        self,
        session,
        owner: str,
        name: str,
        repository_path: str,
    ) -> None:
        """Downloads the repository tree contents containing requirement files.

        Fetches the repository file tree in a single API request and downloads
        only the files that match recognized requirement file extensions.

        Args:
            session: The active aiohttp client session.
            owner (str): The owner of the repository.
            name (str): The name of the repository.
            repository_path (str): The local destination path for downloaded files.
        """
        url = f"https://api.github.com/repos/{owner}/{name}/git/trees/HEAD?recursive=1"
        async with session.get(url) as resp:
            if resp.status != 200:
                return
            data = await resp.json()

        tree = data.get("tree", [])

        for item in tree:
            if item.get("type") != "blob":
                continue

            file_path = item.get("path", "")
            file_name = file_path.rsplit("/", 1)[-1]

            if not any(extension in file_name for extension in FileTypes.ALL_REQUIREMENT_FILES):
                continue

            raw_url = f"https://raw.githubusercontent.com/{owner}/{name}/HEAD/{file_path}"
            async with session.get(raw_url) as file_resp:
                if file_resp.status != 200:
                    continue
                file_content = await file_resp.text()

            filepath = join(repository_path, file_path)
            file_dir = filepath.rsplit("/", 1)[0]
            if not exists(file_dir):
                makedirs(file_dir)
            async with open(filepath, "w") as f:
                await f.write(file_content)

    def get_req_files_names(self, directory_path: str) -> list[str]:
        """Recursively retrieves the paths of all requirement files in a directory.

        Args:
            directory_path (str): The base directory path to search.

        Returns:
            list[str]: A list of relative paths to the discovered requirement files.
        """
        requirement_files = []
        paths = glob(directory_path + "/**", recursive=True)
        for _path in paths:
            if not isdir(_path) and self.is_req_file(_path):
                relative_path = _path.replace(directory_path + "/", "", 1)
                requirement_files.append(relative_path)
        return requirement_files

    def is_req_file(self, requirement_file_name: str) -> bool:
        """Checks if a given file name corresponds to a known requirement file type.

        Args:
            requirement_file_name (str): The name of the file to check.

        Returns:
            bool: True if the file is a recognized requirement file, False otherwise.
        """
        return any(
            extension in requirement_file_name for extension in FileTypes.ALL_REQUIREMENT_FILES
        )
