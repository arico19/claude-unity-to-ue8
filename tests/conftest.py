from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "SampleUnityProject"


@pytest.fixture(scope="session")
def sample_project() -> Path:
    return FIXTURE


@pytest.fixture(scope="session")
def converted(tmp_path_factory, sample_project):
    from unity2ue.config import ConversionConfig
    from unity2ue.pipeline import convert_project

    out = tmp_path_factory.mktemp("ue")
    result = convert_project(sample_project, out, ConversionConfig(project_name="Sample Game"), log=lambda _m: None)
    return result
