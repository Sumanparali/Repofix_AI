# RepoFix runner images

Build the Python test image from the repository root:

```powershell
docker build -f docker/python-runner.Dockerfile -t repofix-python-runner:0.1 .
docker build -f docker/java-runner.Dockerfile -t repofix-java-runner:0.1 .
docker build -f docker/node-runner.Dockerfile -t repofix-node-runner:0.1 .
```

The CLI launches this image with networking disabled, all Linux capabilities dropped,
`no-new-privileges`, a non-root user, and CPU, memory, process, and wall-clock limits.

Dependency installation is not performed during the test phase. For Python `requirements.txt`,
`repofix --prepare` builds a cached repository-specific image in a separate preparation phase.
