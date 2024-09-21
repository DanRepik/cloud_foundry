from cloud_foundry.pulumi.python_function import PythonFunction
from cloud_foundry.python_archive_builder import PythonArchiveBuilder

def python_function(
    self,
    name: str,
    sources: dict[str, str] = None,
    requirements: list[str] = None,
    environment: dict[str, str] = None,
):
    self.archive_builder = PythonArchiveBuilder(
        name=f"{name}-archive-builder",
        sources=sources,
        requirements=requirements,
        working_dir="temp",
    )
    return PythonFunction(
        name=f"{name}-api-maker",
        hash=self.archive_builder.hash(),
        handler="app.lambda_handler",
        archive_location=self.archive_builder.location(),
        environment=environment,
    )
