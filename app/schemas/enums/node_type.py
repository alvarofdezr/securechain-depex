from enum import Enum


class NodeType(str, Enum):
    """Enumeration of package node types in the dependency graph.
    
    Maps package manager systems to their corresponding graph node classifications.
    Each node type represents a package entity within a specific ecosystem,
    used for querying, traversing, and analyzing the dependency network.
    
    Attributes:
        rubygems_package: Ruby package node (RubyGems ecosystem).
        cargo_package: Rust package node (Cargo ecosystem).
        nuget_package: .NET package node (NuGet ecosystem).
        npm_package: JavaScript/Node.js package node (NPM ecosystem).
        maven_package: Java package node (Maven Central ecosystem).
        go_package: Go language package node (Go modules ecosystem).
    """
    rubygems_package = "RubyGemsPackage"
    cargo_package = "CargoPackage"
    nuget_package = "NuGetPackage"
    pypi_package = "PyPIPackage"
    npm_package = "NPMPackage"
    maven_package = "MavenPackage"
    go_package = "GoPackage"
