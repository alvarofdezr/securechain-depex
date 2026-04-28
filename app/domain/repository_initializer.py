from datetime import UTC, datetime
from typing import Any

from app.dependencies import ServiceContainer
from app.schemas import PackageMessageSchema
from app.services import (
    PackageService,
    RepositoryService,
    RequirementFileService,
)
from app.utils import ManagerNodeTypeMapper, RedisQueue

from .repo_analyzer import RepositoryAnalyzer


class RepositoryInitializer:
    """Orchestrates the initialization and update lifecycle of software repositories.
    
    Manages repository creation, requirement file extraction, package queuing,
    and incremental updates. Coordinates between repository analysis, database
    persistence, and asynchronous package processing through a Redis queue.
    
    Attributes:
        redis_queue: Message queue for package processing.
        repository_service: Service for repository CRUD operations.
        requirement_file_service: Service for requirement file management.
        package_service: Service for package operations.
        repo_analyzer: Analyzer for discovering requirement files in repositories.
    """

    def __init__(self):
        """Initializes the repository initializer with required service dependencies."""
        container = ServiceContainer()
        self.redis_queue: RedisQueue = container.get_redis_queue()
        self.repository_service: RepositoryService = container.get_repository_service()
        self.requirement_file_service: RequirementFileService = container.get_requirement_file_service()
        self.package_service: PackageService = container.get_package_service()
        self.repo_analyzer: RepositoryAnalyzer = RepositoryAnalyzer(container.get_http_session())

    async def init_repository(
        self,
        owner: str,
        name: str,
        user_id: str,
        repository: dict[str, Any] | None,
        last_commit_date: datetime,
    ) -> str:
        """Initializes or updates a repository with the specified owner and name.
        
        Creates a new repository record if one does not exist, or performs an 
        incremental update if the repository exists and has newer commits.
        Establishes the user-repository relationship upon completion.
        
        Args:
            owner: The repository owner identifier (e.g., GitHub organization).
            name: The repository name.
            user_id: The user ID requesting the repository initialization.
            repository: Existing repository record, or None if creating new.
            last_commit_date: The timestamp of the latest commit in the repository.
        
        Returns:
            The repository identifier (UUID).
        
        Raises:
            ValueError: If repository data is invalid or creation fails.
            Exception: Propagates exceptions from underlying services.
        """
        raw_requirement_files = await self.repo_analyzer.analyze(owner, name)

        if repository is None:
            repository_data = {
                "owner": owner,
                "name": name,
                "moment": last_commit_date,
                "is_complete": False,
                "user_id": user_id,
            }
            repository_id = await self.repository_service.create_repository(repository_data)

            await self.extract_repository(raw_requirement_files, repository_id)

            await self.repository_service.update_repository_is_complete(repository_id, True)
        else:
            repository_id = repository.get("id", "")

            needs_update = (
                not repository["moment"]
                or repository["moment"].replace(tzinfo=UTC)
                < last_commit_date.replace(tzinfo=UTC)
            )

            if needs_update:
                await self.repository_service.update_repository_is_complete(repository_id, False)

                await self.replace_repository(raw_requirement_files, repository_id)

                await self.repository_service.update_repository_is_complete(repository_id, True)

        await self.repository_service.create_user_repository_rel(repository_id, user_id)

        return repository_id

    async def extract_repository(
        self,
        raw_requirement_files: dict,
        repository_id: str
    ) -> None:
        """Extracts and processes all requirement files from a newly discovered repository.
        
        Iterates through raw requirement file data and creates corresponding
        persistent records and package queue entries.
        
        Args:
            raw_requirement_files: Dictionary mapping requirement file names to their parsed content.
            repository_id: The target repository identifier.
        
        Raises:
            Exception: Propagates exceptions from requirement file processing.
        """
        for name, file_data in raw_requirement_files.items():
            await self.process_requirement_file(name, file_data, repository_id)

    async def replace_repository(
        self,
        raw_requirement_files: dict,
        repository_id: str
    ) -> None:
        """Performs an incremental update of an existing repository's requirement files.
        
        Compares current repository state with newly discovered files. Deletes
        files no longer present, updates existing files with new constraints,
        and queues newly discovered files for processing.
        
        Args:
            raw_requirement_files: Dictionary mapping requirement file names to their parsed content.
            repository_id: The target repository identifier.
        
        Raises:
            Exception: Propagates exceptions from database or file operations.
        """
        existing_files = await self.requirement_file_service.read_requirement_files_by_repository(repository_id)

        for file_name, requirement_file_id in existing_files.items():
            if file_name not in raw_requirement_files:
                await self.requirement_file_service.delete_requirement_file(repository_id, file_name)
            else:
                await self.update_requirement_file(
                    requirement_file_id,
                    raw_requirement_files[file_name],
                )
                raw_requirement_files.pop(file_name)

        if raw_requirement_files:
            for name, file_data in raw_requirement_files.items():
                await self.process_requirement_file(name, file_data, repository_id)

        await self.repository_service.update_repository_moment(repository_id)

    async def update_requirement_file(
        self,
        requirement_file_id: str,
        file_data: dict,
    ) -> None:
        """Updates an existing requirement file with new package constraints.
        
        Performs a three-way merge: updates constraints for existing packages,
        removes packages no longer present, and queues newly discovered packages
        for processing.
        
        Args:
            requirement_file_id: The target requirement file identifier.
            file_data: Dictionary containing 'packages' (dict) and 'manager' (str) keys.
        
        Raises:
            Exception: Propagates exceptions from package or database operations.
        """
        existing_packages = await self.package_service.read_packages_by_requirement_file(requirement_file_id)
        new_packages = file_data.get("packages", {})

        for package_name, constraints in existing_packages.items():
            if package_name in new_packages:
                if constraints != new_packages[package_name]:
                    await self.requirement_file_service.update_requirement_rel_constraints(
                        requirement_file_id,
                        package_name,
                        new_packages[package_name]
                    )
                new_packages.pop(package_name)
            else:
                await self.requirement_file_service.delete_requirement_file_rel(requirement_file_id, package_name)

        if new_packages:
            manager = file_data.get("manager", "UNKNOWN")
            await self.queue_packages(new_packages, manager, requirement_file_id)

        await self.requirement_file_service.update_requirement_file_moment(requirement_file_id)

    async def process_requirement_file(
        self,
        name: str,
        file_data: dict,
        repository_id: str
    ) -> None:
        """Processes a discovered requirement file by creating a record and queuing its packages.
        
        Acts as a convenience wrapper that creates a persistent requirement file
        record and initiates asynchronous package processing.
        
        Args:
            name: The requirement file name or path within the repository.
            file_data: Dictionary containing 'manager' and 'packages' keys.
            repository_id: The parent repository identifier.
        
        Raises:
            Exception: Propagates exceptions from file creation or package queuing.
        """
        manager = file_data.get("manager", "UNKNOWN")
        packages = file_data.get("packages", {})

        req_file_id = await self.create_requirement_file(
            name, manager, repository_id
        )

        await self.queue_packages(packages, manager, req_file_id)

    async def create_requirement_file(
        self,
        name: str,
        manager: str,
        repository_id: str
    ) -> str:
        """Creates a persistent requirement file record in the database.
        
        Args:
            name: The requirement file name or path.
            manager: The package manager type (e.g., 'pip', 'npm', 'maven', 'UNKNOWN').
            repository_id: The parent repository identifier.
        
        Returns:
            The created requirement file identifier (UUID).
        
        Raises:
            Exception: Propagates exceptions from database operations.
        """
        req_file_dict = {
            "name": name,
            "manager": manager,
            "moment": datetime.now(),
        }
        return await self.requirement_file_service.create_requirement_file(req_file_dict, repository_id)

    async def queue_packages(
        self,
        packages: dict[str, Any],
        manager: str,
        req_file_id: str
    ) -> None:
        """Queues packages for asynchronous processing via Redis.
        
        Separates packages into existing (which are directly related to the requirement file)
        and new (which are queued for discovery and analysis). For the 'ANY' manager type,
        extracts the manager prefix from the package key to determine node type.
        
        Args:
            packages: Dictionary mapping package identifiers to version constraints.
            manager: The package manager type; if 'ANY', package keys contain manager prefix.
            req_file_id: The parent requirement file identifier.
        
        Raises:
            Exception: Propagates exceptions from queue or package service operations.
        """
        packages_by_type: dict[str, list] = {}

        for package_key, constraints in packages.items():
            if manager == "ANY":
                manager_prefix, package_name = package_key.split(":", 1)
                node_type = ManagerNodeTypeMapper.manager_to_node_type(manager_prefix)
            else:
                node_type = ManagerNodeTypeMapper.manager_to_node_type(manager)
                package_name = package_key

            if node_type is None:
                continue

            if not await self.package_service.exists_package(node_type, package_name):
                message = PackageMessageSchema(
                    node_type=node_type,
                    package=package_name,
                    vendor="n/a",
                    repository_url="",
                    constraints=constraints,
                    parent_id=req_file_id,
                    parent_version=None,
                    refresh=False,
                )
                await self.redis_queue.add_package_message(message)
            else:
                packages_by_type.setdefault(node_type, []).append({"name": package_name, "constraints": constraints})

        for node_type, pkg_list in packages_by_type.items():
            if pkg_list:
                await self.package_service.relate_packages(
                    node_type,
                    req_file_id,
                    pkg_list,
                )
