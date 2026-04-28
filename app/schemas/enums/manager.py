from enum import Enum


class Manager(str, Enum):
    """Enumeration of supported package manager systems.

    Defines canonical representations for package managers across different
    programming language ecosystems. Used for repository classification,
    version filtering, and vendor-specific constraint handling.

    Attributes:
        rubygems: Ruby package manager (rubygems.org).
        cargo: Rust package manager and build system.
        nuget: .NET Framework package manager (nuget.org).
        pypi: Python Package Index (Python package repository).
        npm: Node Package Manager (JavaScript/Node.js ecosystem).
        maven: Java build tool and package manager (Maven Central).
        go: Go language package manager (Go modules).
    """

    rubygems = "RubyGems"
    cargo = "Cargo"
    nuget = "NuGet"
    pypi = "PyPI"
    npm = "NPM"
    maven = "Maven"
    go = "Go"
