## Contribution Guidelines

To ensure a consistent and high-quality codebase, all contributors are required
to follow these rules:

- **Dependency Management:** Use [uv](https://github.com/astral-sh/uv) to
manage all Python dependencies. Do not modify `requirements.txt` or
`pyproject.toml` manually; instead, use uv commands to add, remove, or update
packages.

- **Code Formatting:** All code must be formatted using
[ruff](https://docs.astral.sh/ruff/), according to the configuration provided
in the repository. Run `ruff format [your_files.py]` on your files before
submitting any changes to ensure compliance.

- **Commit Messages:** Follow the [Conventional
Commits](https://www.conventionalcommits.org/) specification for all commit
messages. This helps automate changelogs and maintain clarity in the project
history.

- **Testing:** Ensure that all new features and bug fixes include appropriate
unit tests. Run the full test suite locally before submitting a pull request.

- **Pull Requests:** (skip this before the initial production release) Open a
pull request for every change, even for small fixes. Each pull request should
be reviewed by at least one other contributor before merging. 

- **Documentation:** Update or add documentation as needed when introducing new
features or making significant changes. This includes docstrings, README
updates, and relevant comments in the code.

- **Linting:** Run `ruff check [your_files.py]` on your files and resolve all
reported issues before submitting your code.

- **Secrets:** Do not commit sensitive information such as API keys, passwords,
or personal data. Use environment variables for local development, in
production and CI/CD pipelines secrets will be pouplated automatically from AWS
Secrets Manager. Use tools like [git-secrets](ghcr.io/gitleaks/gitleaks:latest)
and [truffleHog](trufflesecurity/trufflehog:latest) to scan for secrets before
committing.

- **Branching Strategy:** Follow trunk-based development over gitflow. Commits
to main will be automatically built and deployed to staging. 

By following these guidelines, we can maintain a clean, reliable, and
collaborative project environment. Thank you for contributing!
