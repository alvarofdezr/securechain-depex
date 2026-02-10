# Depex

[![License](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Lint & Test](https://github.com/securechaindev/securechain-depex/actions/workflows/lint-test.yml/badge.svg)]()
[![GHCR](https://img.shields.io/badge/GHCR-securechain--depex-blue?logo=docker)](https://github.com/orgs/securechaindev/packages/container/package/securechain-depex)

## What is Depex?

Depex is a tool that allows you to reason over the entire configuration space of the Software Supply Chain of an open-source software repository.

### Key Features

- 🔍 **Multi-ecosystem support:** Analyzes Python, JavaScript, Ruby, Rust, Java, and PHP dependencies, plus CycloneDX and SPDX SBOM files
- 🧮 **SMT-based reasoning:** Uses Z3 solver to find optimal dependency configurations
- 📊 **Graph analysis:** Visualize and query dependency graphs using Neo4j
- ⚡ **High performance:** Async architecture with Redis caching for SSC ingestion with Dagster

## Development requirements

1. [Docker](https://www.docker.com/) to deploy the tool.
2. [Docker Compose](https://docs.docker.com/compose/) for container orchestration.
3. It is recommended to use a GUI such as [MongoDB Compass](https://www.mongodb.com/en/products/compass).
4. The Neo4J browser interface to visualize the graph built from the data is in [localhost:7474](http://0.0.0.0:7474/browser/) when the container is running.
5. Python 3.14 or higher.

## Deployment with docker

### 1. Clone the repository
Clone the repository from the official GitHub repository:
```bash
git clone https://github.com/securechaindev/securechain-depex.git
cd securechain-depex
```

### 2. Configure environment variables
Create a `.env` file from the `.env.template` file and place it in the `app/` directory.

#### Get API Keys

- How to get a *GitHub* [API key](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).

- Modify the **Json Web Token (JWT)** secret key and algorithm with your own. You can generate your own secret key with the command **openssl rand -base64 32**.

### 3. Create Docker network
Ensure you have the `securechain` Docker network created. If not, create it with:
```bash
docker network create securechain
```

### 4. Databases containers

For graphs and vulnerabilities information you need to download the zipped [data dumps](https://doi.org/10.5281/zenodo.16739080) from **Zenodo**. Once you have unzipped the dumps, inside the root folder run the command:
```bash
docker compose up --build
```

The containerized databases will also be seeded automatically.

### 5. Start the application
Run the command from the project root:
```bash
docker compose -f dev/docker-compose.yml up --build
```

### 6. Access the application
The API will be available at [http://localhost:8002](http://localhost:8002). You can access the API documentation at [http://localhost:8002/docs](http://localhost:8002/docs). Also, in [http://localhost:8001/docs](http://localhost:8001/docs) you can access the auth API documetation.

### 7. Visualize the graph database
Access Neo4j browser interface at [http://localhost:7474](http://localhost:7474/browser/) to visualize and query the dependency graphs.

### 8. Monitor databases
- **MongoDB Compass:** Connect to MongoDB at `mongodb://localhost:27017` to browse documents
- **Redis:** Connect to `localhost:6379` to monitor cache

## Python Environment
The project uses Python 3.14 and [uv](https://github.com/astral-sh/uv) as the package manager for faster and more reliable dependency management.

### Setting up the development environment with uv

1. **Install uv** (if not already installed):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Activate the virtual environment** (uv creates it automatically):
   ```bash
   uv venv
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   uv sync
   ```

## Testing

```bash
# Install test dependencies
uv sync --extra test

# Run all tests
uv run pytest

# Run tests with coverage report
uv run pytest --cov=app --cov-report=term-missing --cov-report=html

# Run specific test file
uv run pytest tests/unit/controllers/test_graph_controller.py -v

# Run only unit tests
uv run pytest tests/unit/ -v
```

## Code Quality

```bash
# Install linter
uv sync --extra dev

# Linting
uv run ruff check app/

# Formatting
uv run ruff format app/
```

## Contributing

Pull requests are welcome! To contribute follow this [guidelines](https://securechaindev.github.io/contributing.html).

## License

[GNU General Public License 3.0](https://www.gnu.org/licenses/gpl-3.0.html)

## Links
- [Secure Chain Team](mailto:hi@securechain.dev)
- [Secure Chain Organization](https://github.com/securechaindev)
- [Secure Chain Documentation](https://securechaindev.github.io/)
