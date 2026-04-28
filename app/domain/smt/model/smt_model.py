from typing import Any

from z3 import ArithRef, AstVector, Real, parse_smt2_string

from app.utils import VersionFilter


class SMTModel:
    """Encodes dependency constraints into an SMT (Satisfiability Modulo Theories) model.
    
    Transforms package dependency data into Z3 satisfiability constraints for risk analysis.
    Handles both direct (primary requirement file) and indirect (transitive) dependencies,
    aggregates their impact metrics, and generates SMT-LIB2 formulas for constraint solving.
    
    The model establishes variables for each package version, impact values, and logical
    implications between parent-child relationships in the dependency graph.
    
    Attributes:
        source_data: Raw dependency data containing package versions, requirements, and impacts.
        aggregator: The metric field name used to aggregate risk/impact from versions.
        node_type: The package manager type (e.g., 'NPM', 'PIP', 'MAVEN').
        domain: Parsed Z3 AST vector representing the SMT domain.
        func_obj: Z3 Real variable representing the file-level risk objective function.
        impacts: Set of variable names aggregating impact contributions.
        childs: Mapping of direct dependencies to their parent constraints.
        parents: Mapping of indirect dependencies to their parent constraints.
        directs: List of direct dependency variable names.
        var_domain: Set of SMT variable declarations.
        indirect_vars: Set of indirect dependency variable names.
        ctc_domain: Concatenated SMT constraint expressions.
        ctcs: Mapping of variables to impact-based version constraints.
        filtered_versions: Mapping of packages to filtered version serial numbers.
    """

    def __init__(self, source_data: dict[str, Any], node_type: str, aggregator: str) -> None:
        """Initializes an SMT model for a package or requirement file.
        
        Args:
            source_data: Dictionary containing 'name', 'have' (package versions), 
                and 'require' (dependencies with 'direct' and 'indirect' keys).
            node_type: Package manager classification (e.g., 'NPM', 'PIP', 'MAVEN').
            aggregator: The field name in version data to use for impact aggregation.
        """
        self.source_data = source_data
        self.aggregator = aggregator
        self.node_type = node_type
        self.domain: AstVector | None = None
        self.func_obj: ArithRef | None = None
        self.impacts: set[str] = set()
        self.childs: dict[str, dict[str, set[int]]] = {}
        self.parents: dict[str, dict[str, set[int]]] = {}
        self.directs: list[str] = []
        self.var_domain: set[str] = set()
        self.indirect_vars: set[str] = set()
        self.ctc_domain: str = ""
        self.ctcs: dict[str, dict[float, set[int]]] = {}
        self.filtered_versions: dict[str, list[int]] = {}

    def convert(self, model_text: str) -> None:
        """Parses an SMT-LIB2 formatted string into a Z3 AST domain.
        
        Initializes the objective function as a Real variable named 'file_risk_<package_name>'.
        
        Args:
            model_text: SMT-LIB2 formatted constraint string.
        
        Raises:
            Z3Exception: If the SMT-LIB2 string is syntactically invalid.
        """
        self.domain = parse_smt2_string(model_text)
        name = self.source_data.get('name') or 'unknown'
        self.func_obj = Real(f"file_risk_{name}")

    def transform(self) -> str:
        """Transforms dependency data into an SMT-LIB2 constraint model.
        
        Processes direct and indirect dependencies, builds constraint domains,
        declares variables for indirect impacts, and generates a complete SMT formula.
        
        Returns:
            The complete SMT-LIB2 model text with all variable declarations and constraints.
        
        Raises:
            Exception: If dependency processing or constraint building fails.
        """
        for key in ["direct", "indirect"]:
            for require in self.source_data.get("require", {}).get(key, []):
                getattr(self, f"transform_{key}_package")(require)

        name = self.source_data.get('name') or 'unknown'
        file_risk_name = f"file_risk_{name}"
        self.var_domain.add(f"(declare-const {file_risk_name} Real)")
        self.build_indirect_constraints()
        self.build_impact_constraints()
        str_sum = self.build_impact_sum()
        self.ctc_domain += f"(= {file_risk_name} {str_sum})"
        for indirect_var in self.indirect_vars:
            self.var_domain.add(f"(declare-const |{indirect_var}| Int)")
            self.var_domain.add(f"(declare-const |impact_{indirect_var}| Real)")
        model_text = f"{' '.join(self.var_domain)} (assert (and {self.ctc_domain}))"
        self.domain = parse_smt2_string(model_text)
        self.func_obj = Real(file_risk_name)
        return model_text

    def transform_direct_package(self, require: dict[str, Any]) -> None:
        """Transforms a direct dependency into SMT constraints and impact variables.
        
        Filters compatible versions based on constraints, creates Z3 variables
        for the package version and its impact contribution, and builds the
        corresponding constraint group.
        
        Args:
            require: Dictionary with 'package' (str) and 'constraints' (version spec).
        
        Raises:
            Exception: If version filtering or constraint building fails.
        """
        package = require.get("package") or ""
        constraints = require.get("constraints") or ""

        versions_impacts = self.get_filtered_versions_impacts(package, constraints)
        versions_names = list(versions_impacts.keys())

        self.directs.append(f"|{package}|")
        var_impact = f"|impact_{package}|"
        self.impacts.add(var_impact)
        self.var_domain.add(f"(declare-const |{package}| Int)")
        self.var_domain.add(f"(declare-const {var_impact} Real)")
        self.build_direct_constraint(package, versions_names)
        self.filtered_versions[package] = versions_names
        self.transform_versions(versions_impacts, package)

    def transform_indirect_package(self, require: dict[str, Any]) -> None:
        """Transforms an indirect (transitive) dependency into constrained variables.
        
        Processes version-to-version relationships between parent and child packages.
        Handles null safety for Neo4j nullable fields, filtering valid version combinations,
        and recording indirect impact variables for constraint generation.
        
        Args:
            require: Dictionary with 'package', 'constraints', 'parent_version_name', 
                and 'parent_serial_number' keys.
        
        Raises:
            Exception: If version filtering or constraint appending fails.
        """
        package = require.get("package") or ""
        constraints = require.get("constraints") or ""

        parent_version_name = require.get("parent_version_name") or ""
        parent_serial_number = require.get("parent_serial_number")
        parent_serial_number = parent_serial_number if parent_serial_number is not None else -1

        versions_impacts = self.get_filtered_versions_impacts(package, constraints)
        versions_names = list(versions_impacts.keys())

        self.append_indirect_constraint(
            package,
            versions_names,
            parent_version_name,
            parent_serial_number,
        )
        self.filtered_versions[package] = versions_names
        self.transform_versions(versions_impacts, package, require)

    def get_filtered_versions_impacts(self, package: str, constraints: str) -> dict[int, float]:
        """Filters package versions by constraint and retrieves their aggregated impact values.
        
        Applies version filtering logic, handles null safety for serial numbers and impacts,
        and returns a mapping of version serial numbers to impact scores.
        
        Args:
            package: The package identifier.
            constraints: Version constraint specification (e.g., '>=1.0.0', '^2.1').
        
        Returns:
            Dictionary mapping version serial number (int) to aggregated impact (float).
            Uses -1 for null serial numbers and 0.0 for null impacts.
        """
        package_versions = self.source_data.get("have", {}).get(package) or []

        filtered_versions = VersionFilter.filter_versions(
            self.node_type,
            package_versions,
            constraints
        )

        result = {}
        for version in filtered_versions:
            sn = version.get("serial_number")
            impact = version.get(self.aggregator)

            safe_sn = sn if sn is not None else -1
            safe_impact = float(impact) if impact is not None else 0.0

            result[safe_sn] = safe_impact

        return result

    def transform_versions(self, versions: dict[int, float], var: str, require: dict[str, Any] | None = None) -> None:
        """Builds impact constraints for version-to-impact mappings.
        
        Registers indirect variables and establishes the mapping between concrete version
        values and their associated impact contributions. Validates parent version presence
        for indirect dependencies before registering constraints.
        
        Args:
            versions: Mapping of version serial numbers to impact values.
            var: The variable name representing the package.
            require: Optional requirement dictionary containing parent version info. 
                If provided, indicates an indirect dependency.
        
        Raises:
            Exception: If constraint registration fails.
        """
        parent_version_name = require.get("parent_version_name") if require else None
        parent_serial_number = require.get("parent_serial_number") if require else None
        if parent_serial_number is None:
            parent_serial_number = -1

        if not require or (
            parent_version_name in self.filtered_versions and
            parent_serial_number in self.filtered_versions.get(parent_version_name, [])
        ):
            impact_version_group = {}
            if require:
                package = require.get('package') or ""
                self.impacts.add(f"|impact_{package}|")
                self.indirect_vars.add(var)
                if parent_version_name:
                    self.indirect_vars.add(parent_version_name)
                impact_version_group = {0.0: {-1}}
            for version, impact in versions.items():
                self.ctcs.setdefault(var, impact_version_group).setdefault(impact, set()).add(version)

    def append_indirect_constraint(
        self, child: str, versions: list[int], parent: str, version: int
    ) -> None:
        """Records a parent-child dependency relationship for constraint generation.
        
        Establishes bidirectional constraints: implications from parent to child,
        and negation implications ensuring child is -1 when parent is invalid.
        Only appends constraints for valid, filtered version combinations.
        
        Args:
            child: The child package name.
            versions: List of valid child version serial numbers.
            parent: The parent package name or version identifier.
            version: The parent version serial number.
        """
        if versions and parent in self.filtered_versions and version in self.filtered_versions.get(parent, []):
            self.childs.setdefault(
                self.group_versions(child, versions, False), {}
            ).setdefault(parent, set()).add(version)
            if child not in self.directs:
                self.parents.setdefault(child, {}).setdefault(parent, set()).add(
                    version
                )

    def build_direct_constraint(self, var: str, versions: list[int]) -> None:
        """Builds an SMT constraint for direct dependencies.
        
        Groups version serial numbers into continuous ranges and creates disjunctive
        equality constraints. If no valid versions exist, assigns -1 as a safe sentinel.
        
        Args:
            var: The variable name.
            versions: List of valid version serial numbers.
        """
        if versions:
            self.ctc_domain += f"{self.group_versions(var, versions, False)} "
        else:
            self.ctc_domain += f"(= |{var}| -1) "

    def build_indirect_constraints(self) -> None:
        """Builds SMT implications for indirect (transitive) dependencies.
        
        For each child-parent relationship, generates implication constraints that
        enforce parent version presence as a precondition for child validity,
        and negation constraints that set child to -1 when parent is invalid.
        """
        for versions, _ in self.childs.items():
            for parent, parent_versions in _.items():
                self.ctc_domain += f"(=> {self.group_versions(parent, list(parent_versions), True)} {versions}) "
        for child, _ in self.parents.items():
            for parent, parent_versions in _.items():
                self.ctc_domain += f"(=> (not {self.group_versions(parent, list(parent_versions), True)}) (= |{child}| -1)) "

    def build_impact_constraints(self) -> None:
        """Builds SMT implications mapping versions to their impact values.
        
        For each variable and its version-to-impact mapping, generates implication
        constraints that set the impact variable when the corresponding version is active.
        """
        for var, _ in self.ctcs.items():
            for impact, versions in _.items():
                self.ctc_domain += f"(=> {self.group_versions(var, list(versions), True)} (= |impact_{var}| {impact})) "

    def group_versions(
        self,
        var: str,
        versions: list[int],
        ascending: bool
    ) -> str:
        """Groups version serial numbers into continuous ranges for efficient constraint encoding.
        
        Partitions a list of version numbers into consecutive sequences and generates
        SMT constraints that express membership in these ranges. Single versions produce
        equality constraints; ranges produce conjunction constraints.
        
        Args:
            var: The variable name (will be enclosed in pipes for SMT escaping).
            versions: Sorted list of version serial numbers to group.
            ascending: If True, assumes ascending sort; if False, descending sort.
        
        Returns:
            An SMT-LIB2 constraint expression (string) representing the grouped versions.
            For single groups, returns a plain constraint; for multiple, returns (or ...).
        """
        if not versions:
            return ""
        constraints: list[str] = []
        current_group = [versions[0]]
        step = 1 if ascending else -1
        for i in range(1, len(versions)):
            if versions[i] == versions[i - 1] + step:
                current_group.append(versions[i])
            else:
                constraints.append(self.create_constraint_for_group(f"|{var}|", current_group, ascending))
                current_group = [versions[i]]
        constraints.append(self.create_constraint_for_group(f"|{var}|", current_group, ascending))
        return constraints[0] if len(constraints) == 1 else f"(or {' '.join(constraints)})"

    @staticmethod
    def create_constraint_for_group(var: str, group: list[int], ascending: bool) -> str:
        """Creates an SMT constraint for a continuous range of version serial numbers.
        
        Generates either an equality constraint (single version) or a conjunction
        constraint specifying the min and max bounds (version range).
        
        Args:
            var: The SMT variable name (already escaped with pipes).
            group: List of consecutive version serial numbers.
            ascending: If True, min/max order is (min, max); if False, (max, min).
        
        Returns:
            An SMT-LIB2 constraint expression for this version group.
        """
        if len(group) == 1:
            return f"(= {var} {group[0]})"
        min_val, max_val = (group[0], group[-1]) if ascending else (group[-1], group[0])
        return f"(and (>= {var} {min_val}) (<= {var} {max_val}))"

    def build_impact_sum(self) -> str:
        """Generates an SMT expression summing all impact variable contributions.
        
        Returns:
            SMT arithmetic expression (string) that sums all registered impact variables,
            or "0.0" if no impacts are registered.
        """
        return f"(+ {' '.join(self.impacts)})" if self.impacts else "0.0"
